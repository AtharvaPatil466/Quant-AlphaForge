"""Smoke test: verify Alpaca paper API connectivity and order execution.

Run this AFTER:
  1. Setting up your Alpaca paper account
  2. Adding API keys to .env
  3. Installing alpaca-py: pip install alpaca-py

Usage:
    cd alphaforge-execution
    python3 smoke_test_alpaca.py
"""

from __future__ import annotations

import logging
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    print("\n" + "=" * 60)
    print("  AlphaForge — Alpaca Paper API Smoke Test")
    print("=" * 60 + "\n")

    # Step 1: Test import
    print("[1/6] Importing alpaca-py SDK...")
    try:
        from alpaca.trading.client import TradingClient
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest
        print("  OK — alpaca-py imported\n")
    except ImportError:
        print("  FAIL — alpaca-py not installed. Run: pip install alpaca-py")
        sys.exit(1)

    # Step 2: Test broker initialization
    print("[2/6] Connecting to Alpaca paper account...")
    try:
        from execution.alpaca_broker import AlpacaBroker
        broker = AlpacaBroker(paper=True, fill_timeout=30)
        print("  OK — connected\n")
    except Exception as e:
        print(f"  FAIL — {e}")
        print("  Check your .env file has ALPACA_API_KEY and ALPACA_SECRET_KEY")
        sys.exit(1)

    # Step 3: Test account info
    print("[3/6] Fetching account state...")
    try:
        account = broker.get_account()
        print(f"  NAV:  ${account.nav:,.2f}")
        print(f"  Cash: ${account.cash:,.2f}")
        print(f"  Positions: {len(account.positions)}")
        print()
    except Exception as e:
        print(f"  FAIL — {e}")
        sys.exit(1)

    # Step 4: Test order submission (1 share of AAPL)
    print("[4/6] Submitting test order: BUY 1 AAPL...")
    from execution.broker import Order
    order = Order(ticker="AAPL", side="BUY", quantity=1.0)
    broker.update_prices({"AAPL": 0.0})  # no ref price — slippage will be 0

    try:
        result = broker.submit_order(order)
        if result.status == "FILLED":
            print(f"  FILLED @ ${result.fill_price:.2f}")
            print(f"  Order ID: {result.order_id}")
            print(f"  Slippage: {result.slippage_bps:.1f} bps")
            print()
        else:
            print(f"  Status: {result.status}")
            print("  Note: market may be closed. Try during market hours (9:30-16:00 ET)")
            print()
    except Exception as e:
        print(f"  FAIL — {e}")
        print("  Note: market orders only fill during market hours")
        print()

    # Step 5: Check positions after order
    print("[5/6] Checking positions...")
    try:
        positions = broker.get_positions()
        for ticker, pos in positions.items():
            print(f"  {ticker}: {pos.quantity} shares @ ${pos.avg_cost:.2f} (value: ${pos.market_value:,.2f})")
        if not positions:
            print("  No positions (order may not have filled — market closed?)")
        print()
    except Exception as e:
        print(f"  FAIL — {e}")

    # Step 6: Sell the test position (if it exists)
    if "AAPL" in broker.get_positions():
        print("[6/6] Cleaning up: SELL 1 AAPL...")
        sell_order = Order(ticker="AAPL", side="SELL", quantity=1.0)
        try:
            sell_result = broker.submit_order(sell_order)
            print(f"  {sell_result.status} @ ${sell_result.fill_price:.2f}")
        except Exception as e:
            print(f"  FAIL — {e}")
    else:
        print("[6/6] No cleanup needed (no AAPL position)")

    print("\n" + "=" * 60)
    print("  Smoke test complete!")
    print("  If orders filled: Alpaca paper API is working.")
    print("  If orders pending: run again during market hours.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
