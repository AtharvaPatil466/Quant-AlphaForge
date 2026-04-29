"""ARCHIVED 2026-04-29: historical audit for retiring `backtest.real_engine`.

Reconcile EventDrivenEngine against real_engine on identical data.

Both engines are pointed at the same parquet slice, the same momentum
strategy (12-1), the same rebalance cadence, and (as far as their cost
contracts allow) the same costs. We then compare:

  - total return
  - annualized Sharpe
  - max drawdown
  - daily-return correlation
  - cumulative NAV drift over time

A small residual is expected and is itself a finding to report — the two
engines have legitimately different fill-timing contracts. The point of
this script is to bound that residual and surface anything larger that
would indicate an actual bug in one engine or the other.

This script is preserved as provenance for the Phase 2 consolidation
decision in `backtest/ENGINE_CONSOLIDATION_DESIGN.md`. It is no longer
part of the active research path and may fail against the current
codebase because `backtest.real_engine` has been intentionally deleted.

Output: research/out/engine_reconciliation.md + .json + .csv
"""

from __future__ import annotations

import json
import math
import os
import sys
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtest.synthetic_demo import BacktestConfig
from backtest.event_driven import (
    DataHandler,
    EngineConfig,
    EventDrivenEngine,
    ExecutionHandler,
    FlatSlippageModel,
    MomentumLongShort,
    Portfolio,
)
from backtest.real_engine import run_real_backtest
from data.real_dataset import load_real_history

OUT_DIR = ROOT / "research" / "out"
OUT_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class EngineSummary:
    name: str
    total_return: float
    ann_sharpe: float
    max_drawdown: float
    n_marks: int


def _ann_sharpe(daily_returns: pd.Series) -> float:
    if daily_returns.empty:
        return float("nan")
    mu = daily_returns.mean()
    sd = daily_returns.std(ddof=1)
    if sd == 0 or not math.isfinite(sd):
        return 0.0
    return float(mu / sd * math.sqrt(252))


def _max_drawdown(nav: pd.Series) -> float:
    if nav.empty:
        return 0.0
    peak = nav.cummax()
    dd = (peak - nav) / peak
    return float(dd.max())


def _summary_from_nav(name: str, nav: pd.Series) -> EngineSummary:
    rets = nav.pct_change().dropna()
    return EngineSummary(
        name=name,
        total_return=float(nav.iloc[-1] / nav.iloc[0] - 1),
        ann_sharpe=_ann_sharpe(rets),
        max_drawdown=_max_drawdown(nav),
        n_marks=len(nav),
    )


def run_event_driven(
    frames: Dict[str, pd.DataFrame],
    rebalance_freq: int,
    long_pct: float,
    short_pct: float,
) -> pd.Series:
    dh = DataHandler(frames)
    eh = ExecutionHandler(FlatSlippageModel(slippage_bps=0.0, commission_bps=0.0))
    strat = MomentumLongShort(
        lookback_days=252, skip_days=21, long_pct=long_pct, short_pct=short_pct,
        gross_leverage=1.0,
    )
    engine = EventDrivenEngine(
        data_handler=dh,
        strategy=strat,
        execution_handler=eh,
        config=EngineConfig(
            rebalance_freq=rebalance_freq,
            initial_cash=1_000_000.0,
            warmup_bars=253,
        ),
    )
    result = engine.run()
    return result.portfolio.nav_series()


def run_real(
    sector: str,
    lookback: int,
    holding_period: int,
    long_pct_int: int,
    end_date: date,
) -> pd.Series:
    cfg = BacktestConfig(
        sector=sector,
        lookback=lookback,
        factor_name="Momentum (12-1)",
        holding_period=holding_period,
        position_size=long_pct_int,
        stop_loss=100.0,
        tx_cost_bps=0,
        long_short=True,
    )
    res = run_real_backtest(cfg, end_date=end_date)
    if res.error:
        raise RuntimeError(f"real_engine: {res.error}")
    # NAV index: synthesize a daily index aligned with the run.
    nav = pd.Series(res.nav, name="nav_real")
    return nav


def reconcile(
    sector: str = "Technology",
    end_date: date = date(2025, 12, 31),
    rebalance_freq: int = 21,
    long_pct: float = 0.20,
):
    print(f"[reconcile] sector={sector} end={end_date} "
          f"rebalance={rebalance_freq} long_pct={long_pct}")

    history = load_real_history(
        sector=sector, lookback=252 + 252 + 30,
        end_date=end_date, align="inner", min_rows=252 + 100,
    )
    if not history:
        raise RuntimeError("no real data loaded")
    tickers = sorted(history.keys())
    print(f"[reconcile] {len(tickers)} tickers loaded: {tickers}")

    n_days = min(len(df) for df in history.values())
    print(f"[reconcile] {n_days} bars per ticker after inner-align")

    # ── Event-driven engine ──
    frames = {tk: history[tk].copy() for tk in tickers}
    nav_ed = run_event_driven(frames, rebalance_freq, long_pct, long_pct)

    # ── Real engine ──
    long_pct_int = int(round(long_pct * 100))
    nav_re = run_real(
        sector=sector, lookback=n_days - 252 - 5,
        holding_period=rebalance_freq,
        long_pct_int=long_pct_int, end_date=end_date,
    )

    # ── Summaries ──
    ed_sum = _summary_from_nav("event_driven", nav_ed)
    # Convert real-engine nav (list-indexed) to a Series with a comparable
    # length-based index so we can correlate against the event-driven
    # daily returns, even if the absolute timestamps differ slightly due
    # to warmup choices.
    nav_re_idx = pd.Series(
        nav_re.values,
        index=pd.RangeIndex(start=0, stop=len(nav_re)),
        name="nav_real",
    )
    re_sum = _summary_from_nav("real_engine", nav_re_idx)

    # ── Daily-return correlation ──
    ed_ret = nav_ed.reset_index(drop=True).pct_change().dropna()
    re_ret = nav_re_idx.pct_change().dropna()
    n = min(len(ed_ret), len(re_ret))
    if n > 0:
        ed_tail = ed_ret.iloc[-n:].reset_index(drop=True)
        re_tail = re_ret.iloc[-n:].reset_index(drop=True)
        corr = float(ed_tail.corr(re_tail))
    else:
        corr = float("nan")

    # ── Drift summary ──
    nav_drift_pct = abs(ed_sum.total_return - re_sum.total_return) * 100
    sharpe_drift = abs(ed_sum.ann_sharpe - re_sum.ann_sharpe)

    # ── Persist ──
    nav_csv = pd.DataFrame({
        "event_driven": nav_ed.reset_index(drop=True),
        "real_engine": nav_re_idx,
    })
    nav_csv.to_csv(OUT_DIR / "engine_reconciliation_nav.csv")

    metrics = {
        "config": {
            "sector": sector,
            "end_date": str(end_date),
            "rebalance_freq": rebalance_freq,
            "long_pct": long_pct,
            "tickers": tickers,
            "n_bars": int(n_days),
            "costs": "zero",
        },
        "event_driven": asdict(ed_sum),
        "real_engine": asdict(re_sum),
        "daily_return_correlation": corr,
        "total_return_drift_pp": nav_drift_pct,
        "sharpe_drift": sharpe_drift,
    }
    (OUT_DIR / "engine_reconciliation.json").write_text(json.dumps(metrics, indent=2))

    # ── Markdown report ──
    md = []
    md.append("# Engine Reconciliation Report\n")
    md.append(f"**Sector:** {sector}  ")
    md.append(f"**End date:** {end_date}  ")
    md.append(f"**Tickers ({len(tickers)}):** {', '.join(tickers)}  ")
    md.append(f"**Bars after inner-align:** {n_days}  ")
    md.append(f"**Rebalance cadence:** every {rebalance_freq} bars  ")
    md.append(f"**Long/short pct:** {long_pct:.0%} / {long_pct:.0%}  ")
    md.append("**Costs:** zero (apples-to-apples)\n")
    md.append("## Headline numbers\n")
    md.append("| Metric | EventDrivenEngine | real_engine | |Δ| |")
    md.append("|---|---:|---:|---:|")
    md.append(
        f"| Total return | {ed_sum.total_return*100:+.2f}% | "
        f"{re_sum.total_return*100:+.2f}% | {nav_drift_pct:.2f} pp |"
    )
    md.append(
        f"| Annualized Sharpe | {ed_sum.ann_sharpe:+.3f} | "
        f"{re_sum.ann_sharpe:+.3f} | {sharpe_drift:.3f} |"
    )
    md.append(
        f"| Max drawdown | {ed_sum.max_drawdown*100:.2f}% | "
        f"{re_sum.max_drawdown*100:.2f}% | "
        f"{abs(ed_sum.max_drawdown - re_sum.max_drawdown)*100:.2f} pp |"
    )
    md.append(f"| NAV marks | {ed_sum.n_marks} | {re_sum.n_marks} | — |\n")
    md.append("## Daily-return correlation\n")
    md.append(f"Pearson ρ over the last {n} overlapping bars: **{corr:.4f}**\n")
    md.append("## Known sources of legitimate residual\n")
    md.append("- **Fill timing:** EventDrivenEngine fills at next-bar OPEN; "
              "real_engine assumes instant repositioning at decision-bar close. "
              "On a typical day this introduces ~½ day of timing slip.")
    md.append("- **Factor index off-by-one:** `MomentumFactor.compute_js` uses "
              "`p[n-21]/p[n-252]` (20-day-old vs 251-day-old close); "
              "`MomentumLongShort` uses `p[-22]/p[-253]` (the academically "
              "correct 12-month-ending-1-month-ago window). This shifts which "
              "tickers land in each leg by exactly one bar.")
    md.append("- **Leg sizing:** real_engine uses "
              "`max(1, int(N * pct/100))`; the new engine rounds to the "
              "nearest integer. Identical at most universe sizes; can differ "
              "by one ticker at small N.\n")
    md.append("## Interpretation\n")
    if corr >= 0.95:
        md.append(f"Daily returns correlate at ρ={corr:.3f} (≥ 0.95). "
                  "The engines agree on signal direction. The Sharpe and "
                  "total-return drift is consistent with the legitimate "
                  "residuals listed above.")
    elif corr >= 0.80:
        md.append(f"Daily returns correlate at ρ={corr:.3f} (in [0.80, 0.95)). "
                  "Borderline — investigate whether the factor off-by-one "
                  "alone explains the residual or whether something else is "
                  "drifting.")
    else:
        md.append(f"Daily returns correlate at only ρ={corr:.3f} (< 0.80). "
                  "**This is too low to dismiss as fill-timing residual.** "
                  "One of the engines has a bug. Audit the factor scoring "
                  "alignment, the rebalance trigger, and the cost path.")

    (OUT_DIR / "engine_reconciliation.md").write_text("\n".join(md))
    print(f"[reconcile] wrote {OUT_DIR / 'engine_reconciliation.md'}")
    print(f"[reconcile] correlation={corr:.4f} drift={nav_drift_pct:.2f}pp")
    return metrics


if __name__ == "__main__":
    reconcile()
