"""TSMOM study — time-series momentum on the real-data universe.

Runs the Moskowitz/Ooi/Pedersen TSMOM on the parquet store and reports
net Sharpe / drawdown / stationary-bootstrap CI + capacity-style curve
across a small set of leverage caps. Comparable to `factor_study.py`
but at the portfolio level (no cross-sectional ranking).
"""

from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

THIS_DIR = Path(__file__).resolve().parent
PROJECT_DIR = THIS_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from data.market.loader import MarketDataLoader
from data.market.universe import ALL_REAL_TICKERS
from research._stats import (
    ann_return,
    ann_sharpe,
    max_drawdown,
    stationary_bootstrap_sharpe,
)
from strategies.tsmom import TSMOMConfig, tsmom_backtest

OUT_DIR = THIS_DIR / "out"
OUT_DIR.mkdir(exist_ok=True)

STUDY_START = "2016-01-04"
STUDY_END = "2025-12-31"
LEVERAGE_GRID = [0.5, 1.0, 1.5, 2.0, 3.0]
LOOKBACK_GRID = [126, 252, 504]
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
def main():
    t0 = time.time()
    print(f"[{time.time()-t0:5.1f}s] Loading panel...")
    close = load_close()
    print(f"          universe: {close.shape[1]} tickers, {close.shape[0]} days")

    grid_results = []
    for lev in LEVERAGE_GRID:
        for lb in LOOKBACK_GRID:
            cfg = TSMOMConfig(lookback_days=lb, max_gross_leverage=lev)
            bt = tsmom_backtest(close, cfg)
            net = bt["net"].dropna()
            boot = stationary_bootstrap_sharpe(net.to_numpy(),
                                               reps=BOOT_REPS, mean_block=BOOT_BLOCKS,
                                               seed=abs(hash((lev, lb))) % (2**31))
            grid_results.append({
                "max_gross_leverage": lev,
                "lookback_days": lb,
                "gross_sharpe": ann_sharpe(bt["gross"]),
                "net_sharpe": ann_sharpe(net),
                "net_ann_return": ann_return(net),
                "max_drawdown": max_drawdown(net),
                "ci_lo": boot["ci_lo"],
                "ci_hi": boot["ci_hi"],
                "p_positive": boot["p_positive"],
                "n_days": int(len(net)),
            })
            print(f"          lev={lev:.1f} lb={lb} net_SR={ann_sharpe(net):+.2f} "
                  f"CI=[{boot['ci_lo']:+.2f},{boot['ci_hi']:+.2f}]")

    out_json = OUT_DIR / "tsmom_results.json"
    out_json.write_text(json.dumps({
        "config": {"start": STUDY_START, "end": STUDY_END,
                   "leverage_grid": LEVERAGE_GRID, "lookback_grid": LOOKBACK_GRID},
        "grid": grid_results,
    }, indent=2, default=float))

    lines = ["# AlphaForge — Time-Series Momentum Study", "",
             f"_Moskowitz-Ooi-Pedersen TSMOM on {close.shape[1]} tickers, "
             f"{STUDY_START} → {STUDY_END}._", "",
             "## Grid Sweep",
             "",
             "| Max Gross Lev | Lookback | Gross SR | Net SR | 95% CI | p(SR>0) | Ann Ret | Max DD |",
             "|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for row in grid_results:
        lines.append(
            f"| {row['max_gross_leverage']:.1f} | {row['lookback_days']} | "
            f"{row['gross_sharpe']:+.2f} | {row['net_sharpe']:+.2f} | "
            f"[{row['ci_lo']:+.2f}, {row['ci_hi']:+.2f}] | {row['p_positive']:.2f} | "
            f"{row['net_ann_return']:+.2%} | {row['max_drawdown']:.2%} |"
        )
    lines += ["", "## Structural Notes", "",
              "TSMOM is *qualitatively different* from cross-sectional momentum:",
              "each ticker is evaluated against its own history, not the cross-section. ",
              "That changes three things:",
              "",
              "1. **Beta:** net-beta of the portfolio swings across regimes, not ~0.",
              "2. **Sector tilts:** absent — the signal is per-ticker.",
              "3. **Turnover:** lower than cross-sectional momentum because the sign ",
              "   only flips when a ticker's trailing return crosses zero.",
              ""]
    (OUT_DIR / "tsmom_report.md").write_text("\n".join(lines))
    print(f"[{time.time()-t0:5.1f}s] Done.")


if __name__ == "__main__":
    main()
