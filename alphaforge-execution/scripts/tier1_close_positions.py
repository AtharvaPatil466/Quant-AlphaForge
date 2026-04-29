"""Tier 1 Phase 0.3 — close all open Alpaca paper positions.

Flattens both paper accounts (default + MARL) ahead of Tier 1 methodology
validation, so the live loop re-launches against the eventual Tier 1
survivor signal on a clean book rather than a stale legacy strategy.

Markets may be closed when this runs; Alpaca queues the resulting market
orders for the next session open. The `.halt` file ensures the daily
strategy will not place new orders against these accounts during Tier 1.

Run once. Idempotent: re-running with no positions is a no-op.

Usage:
    python3 scripts/tier1_close_positions.py            # execute
    python3 scripts/tier1_close_positions.py --dry-run  # preview only
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
ACCOUNTS = [
    {
        "label": "momentum",
        "db": ROOT / "live_trading.db",
        "api_env": "ALPACA_API_KEY",
        "secret_env": "ALPACA_SECRET_KEY",
    },
    {
        "label": "marl",
        "db": ROOT / "live_marl.db",
        "api_env": "ALPACA_API_KEY_MARL",
        "secret_env": "ALPACA_SECRET_KEY_MARL",
    },
]


def _client(api_key: str, secret_key: str):
    from alpaca.trading.client import TradingClient
    return TradingClient(api_key=api_key, secret_key=secret_key, paper=True)


def _record_close(db_path: Path, ticker: str, qty: float, fill_price: float | None,
                  order_id: str, status: str) -> None:
    if not db_path.exists():
        return
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """INSERT OR REPLACE INTO orders
               (order_id, date, ticker, side, quantity, fill_price,
                fill_quantity, status, slippage_bps, tx_cost,
                submitted_at, filled_at)
               VALUES (?, ?, ?, 'SELL', ?, ?, ?, ?, NULL, NULL, ?, ?)""",
            (
                order_id,
                datetime.utcnow().date().isoformat(),
                ticker,
                qty,
                fill_price,
                qty if status == "FILLED" else 0.0,
                status,
                datetime.utcnow().isoformat(),
                datetime.utcnow().isoformat() if status == "FILLED" else None,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def process_account(label: str, db: Path, api_env: str, secret_env: str,
                    dry_run: bool) -> dict:
    api_key = os.environ.get(api_env)
    secret_key = os.environ.get(secret_env)
    if not api_key or not secret_key:
        return {"label": label, "error": f"missing {api_env}/{secret_env}"}

    client = _client(api_key, secret_key)
    acct = client.get_account()
    positions = client.get_all_positions()

    summary = {
        "label": label,
        "account_id": str(acct.id),
        "equity_before": float(acct.equity),
        "n_positions": len(positions),
        "positions": [
            {
                "ticker": p.symbol,
                "qty": float(p.qty),
                "market_value": float(p.market_value),
                "unrealized_pl": float(p.unrealized_pl),
            }
            for p in positions
        ],
        "actions": [],
    }

    if not positions:
        return summary

    if dry_run:
        for p in positions:
            summary["actions"].append({
                "ticker": p.symbol,
                "qty": float(p.qty),
                "would_submit": "MARKET SELL (queued for next open if market closed)",
            })
        return summary

    # Cancel any open working orders first to avoid conflicts
    try:
        client.cancel_orders()
    except Exception as exc:
        summary["cancel_orders_error"] = str(exc)

    # Close all positions via Alpaca's bulk endpoint
    closed = client.close_all_positions(cancel_orders=True)
    for resp in closed:
        body = resp.body if hasattr(resp, "body") else resp
        ticker = getattr(body, "symbol", None) or (
            body.get("symbol") if isinstance(body, dict) else None
        )
        order_id = getattr(body, "id", None) or (
            body.get("id") if isinstance(body, dict) else None
        )
        status = getattr(body, "status", None) or (
            body.get("status") if isinstance(body, dict) else None
        )
        qty_raw = getattr(body, "qty", None) or (
            body.get("qty") if isinstance(body, dict) else None
        )
        try:
            qty = float(qty_raw) if qty_raw is not None else 0.0
        except (TypeError, ValueError):
            qty = 0.0

        action = {
            "ticker": ticker,
            "qty": qty,
            "order_id": str(order_id) if order_id else None,
            "status": str(status) if status else "submitted",
        }
        summary["actions"].append(action)

        if ticker:
            _record_close(
                db_path=db,
                ticker=ticker,
                qty=qty,
                fill_price=None,
                order_id=str(order_id) if order_id else f"tier1-close-{uuid.uuid4().hex[:8]}",
                status=str(status).upper() if status else "PENDING",
            )

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would happen without submitting orders.")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")

    print(f"Tier 1 Phase 0.3 — flatten paper accounts (dry_run={args.dry_run})")
    print(f"Started: {datetime.utcnow().isoformat()}Z")
    print("-" * 60)

    results = []
    for acct_cfg in ACCOUNTS:
        try:
            res = process_account(
                label=acct_cfg["label"],
                db=acct_cfg["db"],
                api_env=acct_cfg["api_env"],
                secret_env=acct_cfg["secret_env"],
                dry_run=args.dry_run,
            )
        except Exception as exc:
            res = {"label": acct_cfg["label"], "error": f"{type(exc).__name__}: {exc}"}
        results.append(res)
        print(json.dumps(res, indent=2, default=str))
        print("-" * 60)

    log_path = ROOT / f"tier1_close_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    log_path.write_text(json.dumps({
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "dry_run": args.dry_run,
        "results": results,
    }, indent=2, default=str))
    print(f"Audit log: {log_path}")

    if any("error" in r for r in results):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
