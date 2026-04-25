"""Persistent trade and snapshot logging."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Optional

from execution.broker import Order
from portfolio.tracker import DailySnapshot
from strategy.momentum import Signal


def log_order(conn: sqlite3.Connection, date: str, order: Order) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO orders
           (order_id, date, ticker, side, quantity, fill_price, fill_quantity,
            status, slippage_bps, tx_cost, submitted_at, filled_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            order.order_id, date, order.ticker, order.side, order.quantity,
            order.fill_price, order.fill_quantity, order.status,
            order.slippage_bps, order.tx_cost, order.submitted_at, order.filled_at,
        ),
    )
    conn.commit()


def log_snapshot(conn: sqlite3.Connection, snap: DailySnapshot) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO snapshots
           (date, nav, daily_return, cumulative_return, drawdown,
            sharpe_to_date, long_exposure, short_exposure, cash,
            n_positions, weights)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            snap.date, snap.nav, snap.daily_return, snap.cumulative_return,
            snap.drawdown, snap.sharpe_to_date, snap.long_exposure,
            snap.short_exposure, snap.cash, snap.n_positions,
            json.dumps(snap.weights),
        ),
    )
    conn.commit()


def log_signals(conn: sqlite3.Connection, date: str, signals: List[Signal]) -> None:
    for sig in signals:
        conn.execute(
            """INSERT OR REPLACE INTO signals
               (date, ticker, mom_5d, mom_21d, mean_rev, composite, rank)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (date, sig.ticker, sig.mom_5d, sig.mom_21d,
             sig.mean_reversion, sig.composite, sig.rank),
        )
    conn.commit()


def get_snapshots(
    conn: sqlite3.Connection,
    limit: int = 252,
) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM snapshots ORDER BY date DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in reversed(rows)]


def get_orders(
    conn: sqlite3.Connection,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
) -> List[Dict[str, Any]]:
    if from_date and to_date:
        rows = conn.execute(
            "SELECT * FROM orders WHERE date BETWEEN ? AND ? ORDER BY date",
            (from_date, to_date),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM orders ORDER BY date").fetchall()
    return [dict(r) for r in rows]
