"""ARCHIVED 2026-04-29: historical panel-vs-engine reconciliation.

Reconcile EventDrivenEngine + PanelStrategy against factor_study.quintile_backtest.

The legacy `quintile_backtest()` is a vectorized pipeline:
  weights[t] = decided at close of bar t (from factor row at t)
  return[t]  = weights.shift(1) × close.pct_change()
  cost[t]    = turnover × bps + impact × turnover²

Equivalent in event-driven terms:
  - Strategy emits weights at close of bar t   (== PanelStrategy + same as_of)
  - Fill happens at close of bar t              (== SameBarCloseExecutionHandler)
  - NAV marks at close of bar t+1               (next-bar mark)

If the two paths agree to floating-point on a panel-driven Momentum
strategy, then the engine is mechanically equivalent to the legacy
backtest under matched conventions, and the path is open to migrate the
factor study onto the engine.

Cost model in this reconciliation: zero, on both sides. The legacy
`ls_net` adds turnover×bps post-hoc; the engine path doesn't apply it
yet. Day-by-day GROSS returns are what we reconcile.

This script is preserved as Phase 2 provenance. It is not part of the
active Tier 1 path.

Output: research/out/factor_study_engine_recon.md + .json
"""

from __future__ import annotations

import json
import math
import sys
from datetime import date
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtest.event_driven import (
    DataHandler,
    EngineConfig,
    EventDrivenEngine,
    FlatSlippageModel,
    PanelStrategy,
    Portfolio,
    SameBarCloseExecutionHandler,
)
from data.real_dataset import load_real_history
from research.factor_study import (
    HOLDING_PERIOD_DAYS,
    N_QUINTILES,
    build_factor_panels,
    quintile_backtest,
)

OUT_DIR = ROOT / "research" / "out"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def _ann_sharpe(r: pd.Series) -> float:
    if len(r) < 2 or r.std(ddof=1) == 0:
        return 0.0
    return float(r.mean() / r.std(ddof=1) * math.sqrt(252))


def _to_close_panel(history: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    return pd.DataFrame({tk: df["Close"] for tk, df in history.items()}).sort_index()


def _to_volume_panel(history: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    return pd.DataFrame({tk: df["Volume"] for tk, df in history.items()}).sort_index()


def run_engine(
    history: Dict[str, pd.DataFrame],
    panel: pd.DataFrame,
    holding_period: int,
) -> pd.Series:
    dh = DataHandler({tk: df.copy() for tk, df in history.items()})
    eh = SameBarCloseExecutionHandler(
        FlatSlippageModel(slippage_bps=0.0, commission_bps=0.0)
    )
    strat = PanelStrategy(panel, n_quintiles=N_QUINTILES, gross_leverage=1.0)
    p = Portfolio(initial_cash=1_000_000.0)
    engine = EventDrivenEngine(
        data_handler=dh, strategy=strat, execution_handler=eh, portfolio=p,
        config=EngineConfig(
            rebalance_freq=holding_period,
            initial_cash=1_000_000.0,
            warmup_bars=0,  # PanelStrategy gates itself on panel availability
        ),
    )
    engine.run()
    return p.nav_series()


def main():
    history = load_real_history(
        sector="Technology", lookback=252 * 3,
        end_date=date(2025, 12, 31), align="inner", min_rows=400,
    )
    if not history:
        raise RuntimeError("no data")
    print(f"tickers={sorted(history)} bars={min(len(df) for df in history.values())}")

    close = _to_close_panel(history)
    volume = _to_volume_panel(history)

    # Build all factor panels via the legacy code.
    panels = build_factor_panels(close, volume)
    factor_name = "Momentum (12-1)"
    panel = panels[factor_name]

    # ── Path 1: legacy quintile_backtest ──
    bt = quintile_backtest(panel, close, holding_period=HOLDING_PERIOD_DAYS)
    ls_gross = bt["long_short_gross"]
    ls_nav_legacy = (1.0 + ls_gross).cumprod()
    print(f"[legacy] last NAV = {ls_nav_legacy.iloc[-1]:.6f} "
          f"Sharpe = {_ann_sharpe(ls_gross):.4f}")

    # ── Path 2: engine + PanelStrategy ──
    engine_nav = run_engine(history, panel, HOLDING_PERIOD_DAYS)
    if engine_nav.empty:
        print("[engine] no NAV produced — strategy may have rejected all bars")
        return
    engine_nav_norm = engine_nav / engine_nav.iloc[0]
    engine_rets = engine_nav.pct_change().dropna()
    print(f"[engine] last NAV (norm) = {engine_nav_norm.iloc[-1]:.6f} "
          f"Sharpe = {_ann_sharpe(engine_rets):.4f}")

    # ── Compare on overlapping dates ──
    common = ls_nav_legacy.index.intersection(engine_nav_norm.index)
    if len(common) < 10:
        print(f"[recon] only {len(common)} overlapping dates — investigate")
        return

    a = ls_nav_legacy.loc[common]
    b = engine_nav_norm.loc[common]
    abs_diff = (a - b).abs()
    rel_diff = (abs_diff / a.abs().clip(lower=1e-9))
    a_rets = a.pct_change().dropna()
    b_rets = b.pct_change().dropna()
    common_rets = a_rets.index.intersection(b_rets.index)
    corr = float(a_rets.loc[common_rets].corr(b_rets.loc[common_rets])) if len(common_rets) > 1 else float("nan")

    metrics = {
        "n_overlapping_dates": int(len(common)),
        "legacy_total_return": float(a.iloc[-1] - 1.0),
        "engine_total_return": float(b.iloc[-1] - 1.0),
        "legacy_sharpe": _ann_sharpe(a.pct_change().dropna()),
        "engine_sharpe": _ann_sharpe(b.pct_change().dropna()),
        "max_abs_nav_diff": float(abs_diff.max()),
        "median_abs_nav_diff": float(abs_diff.median()),
        "max_rel_nav_diff": float(rel_diff.max()),
        "daily_return_correlation": corr,
    }
    (OUT_DIR / "factor_study_engine_recon.json").write_text(json.dumps(metrics, indent=2))

    md = []
    md.append("# Factor Study Engine Reconciliation\n")
    md.append("`PanelStrategy + EventDrivenEngine + SameBarCloseExecutionHandler` "
              "vs `quintile_backtest()` on Momentum (12-1), zero costs.\n")
    md.append(f"- Overlapping dates: **{metrics['n_overlapping_dates']}**")
    md.append(f"- Legacy total return: **{metrics['legacy_total_return']*100:+.4f}%**, "
              f"Sharpe: **{metrics['legacy_sharpe']:+.4f}**")
    md.append(f"- Engine total return: **{metrics['engine_total_return']*100:+.4f}%**, "
              f"Sharpe: **{metrics['engine_sharpe']:+.4f}**")
    md.append(f"- Daily-return correlation: **{corr:.6f}**")
    md.append(f"- Max |NAV diff|: **{metrics['max_abs_nav_diff']:.6f}**")
    md.append(f"- Max relative NAV diff: **{metrics['max_rel_nav_diff']*100:.4f}%**\n")
    md.append("## Verdict\n")
    if metrics["max_rel_nav_diff"] < 1e-3 and corr > 0.9999:
        md.append("**Reconciled to floating-point.** The engine reproduces the "
                  "legacy quintile_backtest gross NAV under matched conventions. "
                  "The migration is unblocked.")
    elif metrics["max_rel_nav_diff"] < 0.01 and corr > 0.99:
        md.append("**Close, residual under 1% NAV. Likely small mechanical "
                  "differences (rebalance-day cash drag, NAV-mark on first bar). "
                  "Investigate before declaring full reconciliation.**")
    else:
        md.append("**Significant residual.** The engine and legacy paths differ "
                  "more than mechanical conventions can explain. Block the "
                  "migration until this is understood.")

    (OUT_DIR / "factor_study_engine_recon.md").write_text("\n".join(md))
    print(f"[recon] wrote {OUT_DIR / 'factor_study_engine_recon.md'}")
    print(f"[recon] max_rel_nav_diff={metrics['max_rel_nav_diff']:.6e} corr={corr:.6f}")


if __name__ == "__main__":
    main()
