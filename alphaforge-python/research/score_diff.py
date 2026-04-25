"""Score-path diagnostic: at one fixed decision bar, dump scores from
both paths side-by-side.

Path P1: MomentumFactor.compute_js + cross-sectional z-score
         (what real_engine uses).
Path P2: MomentumLongShort._score
         (what EventDrivenEngine uses via the strategy ABC).

If rankings are identical at the same bar, the picks divergence is
ENTIRELY a rebalance-date alignment artifact. If they're not, the
factor formulas drift.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtest.event_driven import BarHistory, MomentumLongShort
from data.real_dataset import load_real_history
from data.synthetic import safe_div, mean, stddev, sanitize_number
from factors.registry import load_factor


def main():
    history = load_real_history(
        sector="Technology", lookback=252 + 252 + 30,
        end_date=date(2025, 12, 31), align="inner", min_rows=352,
    )
    tickers = sorted(history.keys())
    n = min(len(df) for df in history.values())
    print(f"tickers={tickers} bars={n}")

    decision_idx = 280  # arbitrary point well past warmup
    decision_ts = history[tickers[0]].index[decision_idx]
    print(f"\ndecision_idx={decision_idx} decision_ts={decision_ts}")

    # ── Path P1: real_engine's scoring ──
    factor = load_factor("Momentum (12-1)")
    raw_p1 = {}
    for tk in tickers:
        prices = history[tk]["Close"].iloc[: decision_idx + 1].to_numpy(dtype=np.float64)
        volumes = history[tk]["Volume"].iloc[: decision_idx + 1].to_numpy(dtype=np.float64)
        returns = np.zeros_like(prices)
        returns[1:] = np.diff(prices) / np.maximum(prices[:-1], 1e-10)
        raw_p1[tk] = factor.compute_js(prices, volumes, returns, lookback=300)
    vals = np.asarray(list(raw_p1.values()))
    mu, sigma = mean(vals), max(1e-8, stddev(vals))
    z_p1 = {tk: sanitize_number(safe_div(raw_p1[tk] - mu, sigma, 0.0), 0.0) for tk in tickers}

    # ── Path P2: ED strategy's scoring ──
    sliced = {tk: history[tk].iloc[: decision_idx + 1] for tk in tickers}
    bh = BarHistory(as_of=decision_ts, frames=sliced)
    strat = MomentumLongShort(lookback_days=252, skip_days=21,
                              long_pct=0.20, short_pct=0.20)
    raw_p2 = {tk: strat._score(bh, tk) for tk in tickers}

    print(f"\n{'ticker':<8} {'P1_raw':>12} {'P1_z':>10} {'P2_raw':>12}  rank_P1 rank_P2")
    print("-" * 60)
    sorted_p1 = sorted(tickers, key=lambda t: raw_p1[t], reverse=True)
    sorted_p2 = sorted(tickers, key=lambda t: raw_p2[t] if raw_p2[t] is not None else -1e18, reverse=True)
    rank_p1 = {tk: i for i, tk in enumerate(sorted_p1)}
    rank_p2 = {tk: i for i, tk in enumerate(sorted_p2)}
    for tk in tickers:
        print(f"{tk:<8} {raw_p1[tk]:>12.4f} {z_p1[tk]:>10.3f} "
              f"{(raw_p2[tk] if raw_p2[tk] is not None else float('nan')):>12.4f}  "
              f"{rank_p1[tk]:>7} {rank_p2[tk]:>7}")

    print(f"\nP1 long (top 2): {sorted_p1[:2]}")
    print(f"P2 long (top 2): {sorted_p2[:2]}")
    print(f"P1 short (bot 2): {sorted_p1[-2:]}")
    print(f"P2 short (bot 2): {sorted_p2[-2:]}")

    n_disagree = sum(1 for tk in tickers if rank_p1[tk] != rank_p2[tk])
    print(f"\nrank disagreements: {n_disagree}/{len(tickers)}")


if __name__ == "__main__":
    main()
