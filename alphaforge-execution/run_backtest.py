"""Run a historical backtest on real market data.

Usage:
    python3 run_backtest.py                              # default: last 6 months
    python3 run_backtest.py --start 2024-01-01 --end 2024-12-31
    python3 run_backtest.py --start 2024-07-01 --end 2024-12-31 --db backtest.db
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta

from config import load_config
from execution.daily_loop import backtest


def main():
    parser = argparse.ArgumentParser(description="AlphaForge Execution Backtest")
    parser.add_argument("--start", type=str, default=None, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, default=None, help="End date (YYYY-MM-DD)")
    parser.add_argument("--config", type=str, default=None, help="Config YAML path")
    parser.add_argument("--db", type=str, default="backtest.db", help="SQLite database path")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    cfg = load_config(args.config)

    end_date = date.fromisoformat(args.end) if args.end else date(2025, 3, 21)
    start_date = date.fromisoformat(args.start) if args.start else end_date - timedelta(days=365)

    tickers = cfg["universe"]["tickers"]
    print(f"\n{'='*60}")
    print(f"  AlphaForge Execution — Historical Backtest")
    print(f"  Tickers:  {tickers}")
    print(f"  Period:   {start_date} to {end_date}")
    print(f"  Strategy: Momentum ranking (5d/21d/MR)")
    print(f"  Position: {cfg['strategy']['position_weight']:.0%} per ticker, top {cfg['strategy']['top_n']}")
    print(f"  Costs:    {cfg['execution']['slippage_bps']} bps slippage")
    print(f"{'='*60}\n")

    tracker = backtest(cfg, start_date, end_date, db_path=args.db)

    print(f"\n{'='*60}")
    print(f"  Backtest Complete")
    print(f"  Trading Days:     {len(tracker.daily_returns)}")
    print(f"  Final NAV:        ${tracker.nav_history[-1]:,.2f}")
    print(f"  Total Return:     {tracker.total_return():+.2%}")
    print(f"  Sharpe (annual):  {tracker.sharpe():.4f}")
    print(f"  Max Drawdown:     {tracker.max_drawdown():.2%}")
    print(f"  Win Rate:         {tracker.win_rate():.2%}")
    print(f"  Database:         {args.db}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
