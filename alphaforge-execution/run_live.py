"""Run a single live paper trading day via Alpaca.

Usage:
    python3 run_live.py                        # uses default config (broker must be "alpaca")
    python3 run_live.py --config live.yaml     # custom config
    python3 run_live.py --db live_trading.db   # custom database

Designed to be called once per trading day (e.g., via cron at 8:00 PM IST / 2:30 PM ET).
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from config import load_config
from execution.daily_loop import run_live_day
from market_calendar import is_market_day

HALT_FILE = Path(".halt")


def main():
    parser = argparse.ArgumentParser(description="AlphaForge — Live Paper Trading")
    parser.add_argument("--config", type=str, default=None, help="Config YAML path")
    parser.add_argument("--db", type=str, default="live_trading.db", help="SQLite database path")
    parser.add_argument("--force", action="store_true", help="Run even on weekends/holidays")
    parser.add_argument(
        "--strategy", choices=["momentum", "marl"], default=None,
        help="Override strategy type (default: use config)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(f"live_{date.today().isoformat()}.log"),
        ],
    )
    logger = logging.getLogger(__name__)

    if HALT_FILE.exists():
        reason = HALT_FILE.read_text().strip()
        logger.info(f"Trading halted: {reason}. Remove .halt file or POST /resume to resume.")
        return

    if not args.force and not is_market_day():
        logger.info("Not a trading day (weekend or NYSE holiday). Use --force to override.")
        return

    cfg = load_config(args.config)

    # Override strategy type if specified on CLI
    if args.strategy:
        if "strategy" not in cfg:
            cfg["strategy"] = {}
        cfg["strategy"]["type"] = args.strategy

    # Ensure broker is set to alpaca
    broker_type = cfg.get("execution", {}).get("broker", "paper")
    if broker_type != "alpaca":
        logger.warning(
            f"Config broker is '{broker_type}', not 'alpaca'. "
            "Set execution.broker to 'alpaca' in your config or use run_backtest.py for paper simulation."
        )
        sys.exit(1)

    tickers = cfg["universe"]["tickers"]
    today = date.today().isoformat()
    strat_name = cfg.get("strategy", {}).get("type", "momentum")

    print(f"\n{'='*60}")
    print(f"  AlphaForge — Live Paper Trading")
    print(f"  Date:     {today}")
    print(f"  Strategy: {strat_name}")
    print(f"  Tickers:  {tickers}")
    print(f"  Broker:   Alpaca Paper")
    print(f"  Database: {args.db}")
    print(f"{'='*60}\n")

    try:
        snap = run_live_day(cfg, db_path=args.db)
    except Exception as e:
        logger.error(f"Live trading failed: {e}", exc_info=True)
        sys.exit(1)

    if snap:
        print(f"\n{'='*60}")
        print(f"  Day Complete — {today}")
        print(f"  NAV:          ${snap.nav:,.2f}")
        print(f"  Daily Return: {snap.daily_return:+.2%}")
        print(f"  Drawdown:     {snap.drawdown:.2%}")
        print(f"  Positions:    {snap.n_positions}")
        print(f"  Sharpe YTD:   {snap.sharpe_to_date:.2f}")
        print(f"{'='*60}\n")
    else:
        logger.warning("No snapshot returned — engine may have been halted")


if __name__ == "__main__":
    main()
