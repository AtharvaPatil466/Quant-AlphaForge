"""ARCHIVED 2026-04-29: Phase 2 bug-hunt for the retired `real_engine`.

Bug-hunt: localize the disagreement between EventDrivenEngine and real_engine.

Strategy: re-run the same momentum strategy on the same data three ways.

  variant A — real_engine, original (with the daily clamp(±20%))
  variant B — real_engine logic, clamp REMOVED
  variant C — EventDrivenEngine (next-bar-open fills)

If A and B match, the clamp is irrelevant.
If A and B differ but B and C match, the clamp is the bug.
If B and C differ, the bug is elsewhere — fill timing or scoring path.

We also dump per-rebalance long/short picks for each variant. If B and C
pick identical legs at every rebalance, then any residual must be NAV-math
or fill-timing related, not signal-related.

This script is preserved as provenance for the consolidation decision
documented in `backtest/ENGINE_CONSOLIDATION_DESIGN.md`. It is no
longer part of the active research path.

Output: research/out/engine_diff.md + .json
"""

from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtest.event_driven import (
    DataHandler,
    EngineConfig,
    EventDrivenEngine,
    ExecutionHandler,
    FlatSlippageModel,
    MomentumLongShort,
    Portfolio,
)
from data.real_dataset import load_real_history
from data.synthetic import PriceSeries, safe_div, sanitize_number, clamp, mean, stddev
from factors.registry import load_factor

OUT_DIR = ROOT / "research" / "out"
OUT_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class RebalancePicks:
    bar_idx: int
    longs: List[str]
    shorts: List[str]


@dataclass
class VariantResult:
    name: str
    nav: List[float]
    daily_returns: List[float]
    picks: List[RebalancePicks] = field(default_factory=list)


def _score_cross_section(history_slice: Dict[str, pd.DataFrame], lookback: int) -> Dict[str, float]:
    """Faithful port of real_engine._score_cross_section."""
    factor = load_factor("Momentum (12-1)")
    raw_scores: Dict[str, float] = {}
    for ticker, df in history_slice.items():
        prices = df["Close"].to_numpy(dtype=np.float64)
        volumes = df["Volume"].to_numpy(dtype=np.float64)
        returns = np.zeros_like(prices)
        if len(prices) > 1:
            returns[1:] = np.diff(prices) / np.maximum(prices[:-1], 1e-10)
        raw_scores[ticker] = factor.compute_js(prices, volumes, returns, lookback)
    values = np.asarray(list(raw_scores.values()), dtype=np.float64)
    mu = mean(values)
    sigma = max(1e-8, stddev(values))
    return {
        ticker: sanitize_number(safe_div(raw_scores[ticker] - mu, sigma, 0.0), 0.0)
        for ticker in raw_scores
    }


def run_real_engine_variant(
    history: Dict[str, pd.DataFrame],
    *,
    apply_daily_clamp: bool,
    lookback: int,
    holding_period: int = 21,
    position_size_pct: int = 20,
    label: str = "",
) -> VariantResult:
    """Hand-rolled port of real_engine's loop with a flag to disable the clamp."""
    tickers = sorted(history.keys())
    n_days = min(len(df) for df in history.values())
    warmup_days = max(252, lookback)
    backtest_days = min(lookback, n_days - warmup_days - 1)
    start_idx = n_days - backtest_days - 1

    nav = [100.0]
    daily_returns: List[float] = []
    picks: List[RebalancePicks] = []
    current_long: List[str] = []
    current_short: List[str] = []

    for offset, decision_idx in enumerate(range(start_idx, n_days - 1), start=1):
        if not current_long or (offset - 1) % max(1, holding_period) == 0:
            slice_ = {
                tk: history[tk].iloc[: decision_idx + 1] for tk in tickers
            }
            scores = _score_cross_section(slice_, lookback)
            ranked = sorted(scores, key=scores.get, reverse=True)
            leg_size = max(1, int(len(ranked) * position_size_pct / 100))
            current_long = ranked[:leg_size]
            current_short = ranked[-leg_size:]
            picks.append(
                RebalancePicks(bar_idx=decision_idx,
                               longs=list(current_long),
                               shorts=list(current_short))
            )

        next_idx = decision_idx + 1
        port_return = 0.0
        for ticker in current_long:
            px = history[ticker]["Close"].iloc[decision_idx]
            nxt = history[ticker]["Close"].iloc[next_idx]
            ret = safe_div(nxt - px, px, 0.0)
            port_return += safe_div(ret, len(current_long), 0.0)
        for ticker in current_short:
            px = history[ticker]["Close"].iloc[decision_idx]
            nxt = history[ticker]["Close"].iloc[next_idx]
            ret = safe_div(nxt - px, px, 0.0)
            port_return += safe_div(-ret, len(current_short), 0.0)

        if apply_daily_clamp:
            new_nav = nav[-1] * (1 + clamp(port_return, -0.20, 0.20))
        else:
            new_nav = nav[-1] * (1 + port_return)
        nav.append(max(0.01, sanitize_number(new_nav, nav[-1])))
        daily_returns.append(port_return)

    return VariantResult(name=label or ("real_clamped" if apply_daily_clamp else "real_unclamped"),
                         nav=nav, daily_returns=daily_returns, picks=picks)


def run_ed_variant(
    history: Dict[str, pd.DataFrame],
    holding_period: int = 21,
    long_pct: float = 0.20,
    warmup_bars: int = 253,
) -> VariantResult:
    dh = DataHandler({tk: history[tk].copy() for tk in sorted(history)})
    eh = ExecutionHandler(FlatSlippageModel(slippage_bps=0.0, commission_bps=0.0))
    strat = MomentumLongShort(
        lookback_days=252, skip_days=21, long_pct=long_pct, short_pct=long_pct,
        gross_leverage=1.0,
    )
    p = Portfolio(initial_cash=1_000_000.0)

    # Capture picks by sniffing the engine's strategy invocations.
    captured: List[RebalancePicks] = []
    original_on_bar = strat.on_bar
    bar_idx_counter = {"i": 0}

    def wrapped_on_bar(history_view):
        signals = original_on_bar(history_view)
        longs = sorted([s.ticker for s in signals if s.target_weight > 0])
        shorts = sorted([s.ticker for s in signals if s.target_weight < 0])
        captured.append(RebalancePicks(bar_idx=bar_idx_counter["i"], longs=longs, shorts=shorts))
        return signals

    strat.on_bar = wrapped_on_bar  # type: ignore

    engine = EventDrivenEngine(
        data_handler=dh, strategy=strat, execution_handler=eh, portfolio=p,
        config=EngineConfig(
            rebalance_freq=holding_period,
            initial_cash=1_000_000.0,
            warmup_bars=warmup_bars,
        ),
    )
    n_bars = len(dh.timestamps)
    for i in range(n_bars):
        bar_idx_counter["i"] = i
        # We're driving the engine via its run() loop — hook is via the wrapped on_bar.
        # Just invoke once at the end of the construction; the engine.run() will iterate.
    result = engine.run()
    nav = list(result.portfolio.nav_series().values)
    nav = [1_000_000.0] + nav  # match real_engine's "initial + marks" length
    rets = list(pd.Series(nav).pct_change().dropna().values)
    return VariantResult(name="event_driven", nav=nav, daily_returns=rets, picks=captured)


def _summary(v: VariantResult) -> Dict:
    nav_arr = np.asarray(v.nav, dtype=np.float64)
    rets = pd.Series(v.daily_returns)
    sharpe = float(rets.mean() / rets.std(ddof=1) * math.sqrt(252)) if rets.std(ddof=1) > 0 else 0.0
    peak = nav_arr.copy()
    for i in range(1, len(peak)):
        peak[i] = max(peak[i], peak[i - 1])
    dd = float(((peak - nav_arr) / peak).max())
    return {
        "name": v.name,
        "total_return_pct": float(nav_arr[-1] / nav_arr[0] - 1) * 100,
        "ann_sharpe": sharpe,
        "max_drawdown_pct": dd * 100,
        "n_bars": len(v.daily_returns),
        "n_rebalances": len(v.picks),
    }


def _picks_diff(a: List[RebalancePicks], b: List[RebalancePicks]) -> Dict:
    """Compare picks between two variants — count rebalances where the
    long-set or short-set as sets differ (ignoring leg size mismatches)."""
    n_compare = min(len(a), len(b))
    long_disagreements = 0
    short_disagreements = 0
    for ra, rb in zip(a[:n_compare], b[:n_compare]):
        if set(ra.longs) != set(rb.longs):
            long_disagreements += 1
        if set(ra.shorts) != set(rb.shorts):
            short_disagreements += 1
    return {
        "n_rebalances_compared": n_compare,
        "long_disagreements": long_disagreements,
        "short_disagreements": short_disagreements,
    }


def main():
    sector = "Technology"
    end_date = date(2025, 12, 31)
    history = load_real_history(
        sector=sector, lookback=252 + 252 + 30,
        end_date=end_date, align="inner", min_rows=252 + 100,
    )
    if not history:
        raise RuntimeError("no data")
    n_days = min(len(df) for df in history.values())
    print(f"[diff] tickers={len(history)} bars={n_days}")

    # ── Variant A: real_engine with daily clamp ──
    A = run_real_engine_variant(history, apply_daily_clamp=True,
                                 lookback=n_days - 252 - 5,
                                 label="real_clamped")
    print(f"[A] {A.name}: total={_summary(A)['total_return_pct']:.2f}%")

    # ── Variant B: real_engine, clamp removed ──
    B = run_real_engine_variant(history, apply_daily_clamp=False,
                                 lookback=n_days - 252 - 5,
                                 label="real_unclamped")
    print(f"[B] {B.name}: total={_summary(B)['total_return_pct']:.2f}%")

    # ── Variant C: EventDrivenEngine, rebalance dates aligned with real_engine ──
    # real_engine starts at start_idx = n_days - backtest_days - 1
    real_start_bar = n_days - (n_days - 252 - 5) - 1  # = 257? — let's compute exactly
    warmup_days = max(252, n_days - 252 - 5)
    real_backtest_days = min(n_days - 252 - 5, n_days - warmup_days - 1)
    real_start_idx = n_days - real_backtest_days - 1
    print(f"[align] real_engine start_idx={real_start_idx}; ED warmup_bars={real_start_idx}")
    C = run_ed_variant(history, warmup_bars=real_start_idx)
    print(f"[C] {C.name}: total={_summary(C)['total_return_pct']:.2f}%")

    # ── Picks diff: B vs C ──
    diff_BC = _picks_diff(B.picks, C.picks)
    diff_AB = _picks_diff(A.picks, B.picks)
    print(f"[picks A vs B] {diff_AB}")
    print(f"[picks B vs C] {diff_BC}")

    # ── Daily-return correlations ──
    def corr(x: List[float], y: List[float]) -> float:
        n = min(len(x), len(y))
        if n < 2:
            return float("nan")
        return float(pd.Series(x[-n:]).corr(pd.Series(y[-n:])))

    metrics = {
        "A_real_clamped": _summary(A),
        "B_real_unclamped": _summary(B),
        "C_event_driven": _summary(C),
        "corr_A_B": corr(A.daily_returns, B.daily_returns),
        "corr_A_C": corr(A.daily_returns, C.daily_returns),
        "corr_B_C": corr(B.daily_returns, C.daily_returns),
        "picks_A_vs_B": diff_AB,
        "picks_B_vs_C": diff_BC,
        "n_bars": n_days,
    }
    (OUT_DIR / "engine_diff.json").write_text(json.dumps(metrics, indent=2))

    # ── Report ──
    md = []
    md.append("# Engine Diff Report — bug localization\n")
    md.append("Three variants of the same momentum strategy on the same data, "
              "zero costs:\n")
    md.append("- **A** — `real_engine` with the daily `clamp(±20%)`")
    md.append("- **B** — `real_engine` logic, clamp REMOVED")
    md.append("- **C** — `EventDrivenEngine` (next-bar-open fills)\n")
    md.append("## Headline numbers\n")
    md.append("| Variant | Total return | Ann. Sharpe | Max DD | n_bars | n_rebal |")
    md.append("|---|---:|---:|---:|---:|---:|")
    for v in (A, B, C):
        s = _summary(v)
        md.append(
            f"| {s['name']} | {s['total_return_pct']:+.2f}% | "
            f"{s['ann_sharpe']:+.3f} | {s['max_drawdown_pct']:.2f}% | "
            f"{s['n_bars']} | {s['n_rebalances']} |"
        )
    md.append("")
    md.append("## Pairwise daily-return correlation\n")
    md.append(f"- A vs B (clamp on/off): **{metrics['corr_A_B']:.4f}**")
    md.append(f"- A vs C: **{metrics['corr_A_C']:.4f}**")
    md.append(f"- B vs C (clamp-off vs ED): **{metrics['corr_B_C']:.4f}**\n")
    md.append("## Pick agreement\n")
    md.append(f"- A vs B (same picks expected, identical scoring): "
              f"long_disagreements={diff_AB['long_disagreements']}, "
              f"short_disagreements={diff_AB['short_disagreements']} "
              f"out of {diff_AB['n_rebalances_compared']} rebalances.")
    md.append(f"- B vs C: long_disagreements={diff_BC['long_disagreements']}, "
              f"short_disagreements={diff_BC['short_disagreements']} "
              f"out of {diff_BC['n_rebalances_compared']} rebalances.\n")
    md.append("## Verdict\n")
    if metrics["corr_A_B"] > 0.99 and abs(metrics["A_real_clamped"]["total_return_pct"] - metrics["B_real_unclamped"]["total_return_pct"]) < 1.0:
        md.append("- **Clamp is not the bug.** A and B agree to within 1pp.")
    else:
        delta = (metrics["B_real_unclamped"]["total_return_pct"]
                 - metrics["A_real_clamped"]["total_return_pct"])
        md.append(f"- **Clamp matters: removing it shifts total return by {delta:+.2f}pp.** "
                  "The daily ±20% clamp was silently truncating an asymmetric "
                  "return distribution.")
    if diff_BC["long_disagreements"] == 0 and diff_BC["short_disagreements"] == 0:
        md.append("- **Picks match between B and C.** Any residual disagreement "
                  "between B and C is due to fill-timing (B fills at decision "
                  "close, C fills at next-bar open) or NAV-math, not signal.")
    else:
        md.append(f"- **Picks DIFFER between B and C** at {diff_BC['long_disagreements']} long / "
                  f"{diff_BC['short_disagreements']} short rebalances out of "
                  f"{diff_BC['n_rebalances_compared']}. The factor scoring path "
                  "diverges. Likely culprits: the off-by-one in MomentumFactor.compute_js, "
                  "or the z-score normalization in real_engine vs raw-score sort in ED.")

    (OUT_DIR / "engine_diff.md").write_text("\n".join(md))
    print(f"[diff] wrote {OUT_DIR / 'engine_diff.md'}")


if __name__ == "__main__":
    main()
