"""Pairs-trading study on the real-data universe.

Scans for cointegrated pairs each quarter, trades each at z-score entries,
and reports net Sharpe + stationary-bootstrap CI. The strategy is
structurally dollar-neutral so beta contribution should be near zero.
"""

from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

THIS_DIR = Path(__file__).resolve().parent
PROJECT_DIR = THIS_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from data.market.loader import MarketDataLoader
from data.market.universe import ALL_REAL_TICKERS
from strategies.pairs_trading import PairsConfig, pairs_backtest, find_pairs

OUT_DIR = THIS_DIR / "out"
OUT_DIR.mkdir(exist_ok=True)

STUDY_START = "2016-01-04"
STUDY_END = "2025-12-31"
BOOT_REPS = 1000
BOOT_BLOCKS = 21


def load_close() -> pd.DataFrame:
    loader = MarketDataLoader()
    history: Dict[str, pd.DataFrame] = {}
    for tk in ALL_REAL_TICKERS:
        try:
            df = loader.load_ticker(tk, start_date=STUDY_START, end_date=STUDY_END)
        except Exception:
            continue
        if len(df) >= 252 * 3:
            history[tk] = df
    idx = None
    for df in history.values():
        idx = df.index if idx is None else idx.intersection(df.index)
    close = pd.DataFrame({t: df["Adj Close"].loc[idx] for t, df in history.items()})
    close = close.dropna(axis=1, how="all").ffill(limit=2).dropna(axis=1)
    return close


def ann_sharpe(r: pd.Series) -> float:
    if len(r) < 30 or r.std(ddof=1) == 0:
        return 0.0
    return float(r.mean() / r.std(ddof=1) * math.sqrt(252))


def ann_return(r: pd.Series) -> float:
    nav = (1 + r).prod()
    if nav <= 0 or len(r) == 0:
        return 0.0
    return float(nav ** (252 / len(r)) - 1)


def max_drawdown(r: pd.Series) -> float:
    nav = (1 + r).cumprod()
    return float(((nav - nav.cummax()) / nav.cummax()).min())


def stationary_bootstrap_sharpe(r: np.ndarray, reps: int = BOOT_REPS,
                                mean_block: int = BOOT_BLOCKS, seed: int = 0) -> Dict[str, float]:
    rng = np.random.default_rng(seed)
    n = len(r)
    if n < 30:
        return {"ci_lo": 0.0, "ci_hi": 0.0, "p_positive": 0.0}
    p = 1.0 / mean_block
    out = np.empty(reps)
    for b in range(reps):
        idxs = np.empty(n, dtype=np.int64)
        i = int(rng.integers(0, n))
        for k in range(n):
            if k > 0 and rng.random() < p:
                i = int(rng.integers(0, n))
            else:
                i = (i + 1) % n if k > 0 else i
            idxs[k] = i
        s = r[idxs]; sd = s.std(ddof=1)
        out[b] = (s.mean() / sd * math.sqrt(252)) if sd > 0 else 0.0
    return {"ci_lo": float(np.quantile(out, 0.025)),
            "ci_hi": float(np.quantile(out, 0.975)),
            "p_positive": float((out > 0).mean())}


def main():
    t0 = time.time()
    print(f"[{time.time()-t0:5.1f}s] Loading panel...")
    close = load_close()
    print(f"          universe: {close.shape[1]} tickers, {close.shape[0]} days")

    grid = []
    for entry, exit_ in [(2.0, 0.5), (1.5, 0.25), (2.5, 0.5)]:
        cfg = PairsConfig(entry_z=entry, exit_z=exit_)
        bt = pairs_backtest(close, cfg)
        net = bt["net"].dropna()
        boot = stationary_bootstrap_sharpe(
            net.to_numpy(), seed=abs(hash((entry, exit_))) % (2**31))
        grid.append({
            "entry_z": entry, "exit_z": exit_,
            "gross_sharpe": ann_sharpe(bt["gross"]),
            "net_sharpe": ann_sharpe(net),
            "ann_return": ann_return(net),
            "max_drawdown": max_drawdown(net),
            "ci_lo": boot["ci_lo"], "ci_hi": boot["ci_hi"],
            "p_positive": boot["p_positive"],
            "n_days": int(len(net)),
        })
        print(f"          entry={entry} exit={exit_} net_SR={ann_sharpe(net):+.2f}")

    out_json = OUT_DIR / "pairs_results.json"
    out_json.write_text(json.dumps({
        "config": {"start": STUDY_START, "end": STUDY_END},
        "grid": grid,
    }, indent=2, default=float))

    lines = ["# AlphaForge — Pairs Trading Study", "",
             f"_Engle-Granger cointegration pairs on {close.shape[1]} tickers, "
             f"{STUDY_START} → {STUDY_END}._", "",
             "## Z-score Grid",
             "",
             "| Entry z | Exit z | Gross SR | Net SR | 95% CI | p(SR>0) | Ann Ret | Max DD |",
             "|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for row in grid:
        lines.append(
            f"| {row['entry_z']:.2f} | {row['exit_z']:.2f} | "
            f"{row['gross_sharpe']:+.2f} | {row['net_sharpe']:+.2f} | "
            f"[{row['ci_lo']:+.2f}, {row['ci_hi']:+.2f}] | {row['p_positive']:.2f} | "
            f"{row['ann_return']:+.2%} | {row['max_drawdown']:.2%} |"
        )
    lines += ["", "## Structural Notes", "",
              "Pairs trading is structurally different from momentum/reversal:",
              "",
              "- **Dollar-neutral** at entry — aggregate beta ≈ 0.",
              "- **Idiosyncratic risk** dominates; returns are uncorrelated with market.",
              "- **Cointegration risk**: pairs that stopped cointegrating mid-trade give "
              "the largest losses. The stop-z parameter controls this exposure.",
              "",
              "**Caveat:** the universe here is 50 large-caps across 5 sectors; real pairs "
              "strategies use thousands of names so the pool of cointegrated pairs is "
              "much larger. Results on this small universe should be viewed as a "
              "structural smoke test, not a capacity-credible backtest.",
              ""]
    (OUT_DIR / "pairs_report.md").write_text("\n".join(lines))
    print(f"[{time.time()-t0:5.1f}s] Done.")


if __name__ == "__main__":
    main()
