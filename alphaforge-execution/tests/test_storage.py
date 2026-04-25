"""Tests for SQLite storage layer."""

import json
import sqlite3

import pytest

from execution.broker import Order
from portfolio.tracker import DailySnapshot
from storage.database import get_connection
from storage.trade_log import (
    get_orders,
    get_snapshots,
    log_order,
    log_signals,
    log_snapshot,
)
from strategy.momentum import Signal


@pytest.fixture
def db():
    """In-memory database for testing."""
    conn = get_connection(":memory:")
    yield conn
    conn.close()


class TestDatabase:
    def test_creates_tables(self, db):
        tables = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        names = {row["name"] for row in tables}
        assert "orders" in names
        assert "snapshots" in names
        assert "signals" in names

    def test_row_factory(self, db):
        db.execute("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                   ("o1", "2024-01-01", "AAPL", "BUY", 10, 150.0, 10, "FILLED", 5.0, 0.075, "", ""))
        db.commit()
        row = db.execute("SELECT * FROM orders WHERE order_id='o1'").fetchone()
        assert row["ticker"] == "AAPL"


class TestLogOrder:
    def test_insert_order(self, db):
        order = Order(
            ticker="AAPL", side="BUY", quantity=10,
            order_id="abc123", status="FILLED",
            fill_price=150.0, fill_quantity=10,
        )
        log_order(db, "2024-01-01", order)
        rows = db.execute("SELECT * FROM orders").fetchall()
        assert len(rows) == 1
        assert rows[0]["ticker"] == "AAPL"

    def test_replace_order(self, db):
        order = Order(ticker="AAPL", side="BUY", quantity=10, order_id="abc123", status="FILLED")
        log_order(db, "2024-01-01", order)
        order.status = "REJECTED"
        log_order(db, "2024-01-01", order)
        rows = db.execute("SELECT * FROM orders").fetchall()
        assert len(rows) == 1
        assert rows[0]["status"] == "REJECTED"


class TestLogSnapshot:
    def test_insert_snapshot(self, db):
        snap = DailySnapshot(
            date="2024-01-01", nav=100_000, daily_return=0.01,
            cumulative_return=0.01, drawdown=0.0, long_exposure=0.25,
            short_exposure=0.0, cash=75_000, n_positions=5,
            sharpe_to_date=1.5, weights={"AAPL": 0.05},
        )
        log_snapshot(db, snap)
        rows = db.execute("SELECT * FROM snapshots").fetchall()
        assert len(rows) == 1
        assert rows[0]["nav"] == 100_000

    def test_weights_stored_as_json(self, db):
        snap = DailySnapshot(
            date="2024-01-01", nav=100_000, daily_return=0.0,
            cumulative_return=0.0, drawdown=0.0, long_exposure=0.0,
            short_exposure=0.0, cash=100_000, n_positions=0,
            sharpe_to_date=0.0, weights={"AAPL": 0.05, "MSFT": 0.03},
        )
        log_snapshot(db, snap)
        row = db.execute("SELECT weights FROM snapshots").fetchone()
        parsed = json.loads(row["weights"])
        assert parsed["AAPL"] == 0.05


class TestLogSignals:
    def test_insert_signals(self, db):
        signals = [
            Signal("AAPL", 0.02, 0.05, -0.01, 0.04, 1),
            Signal("MSFT", 0.01, 0.03, 0.02, 0.03, 2),
        ]
        log_signals(db, "2024-01-01", signals)
        rows = db.execute("SELECT * FROM signals").fetchall()
        assert len(rows) == 2

    def test_replace_signals(self, db):
        sig = Signal("AAPL", 0.02, 0.05, -0.01, 0.04, 1)
        log_signals(db, "2024-01-01", [sig])
        sig2 = Signal("AAPL", 0.10, 0.10, 0.10, 0.10, 1)
        log_signals(db, "2024-01-01", [sig2])
        rows = db.execute("SELECT * FROM signals WHERE ticker='AAPL'").fetchall()
        assert len(rows) == 1
        assert rows[0]["mom_5d"] == 0.10


class TestGetSnapshots:
    def test_chronological_order(self, db):
        for i in range(5):
            snap = DailySnapshot(
                date=f"2024-01-0{i+1}", nav=100_000 + i * 100,
                daily_return=0.001, cumulative_return=0.001 * (i + 1),
                drawdown=0.0, long_exposure=0.0, short_exposure=0.0,
                cash=100_000, n_positions=0, sharpe_to_date=0.0,
            )
            log_snapshot(db, snap)
        rows = get_snapshots(db, limit=10)
        dates = [r["date"] for r in rows]
        assert dates == sorted(dates)

    def test_limit_respected(self, db):
        for i in range(10):
            snap = DailySnapshot(
                date=f"2024-01-{i+1:02d}", nav=100_000,
                daily_return=0.0, cumulative_return=0.0,
                drawdown=0.0, long_exposure=0.0, short_exposure=0.0,
                cash=100_000, n_positions=0, sharpe_to_date=0.0,
            )
            log_snapshot(db, snap)
        rows = get_snapshots(db, limit=5)
        assert len(rows) == 5


class TestGetOrders:
    def test_all_orders(self, db):
        for i in range(3):
            order = Order(ticker="AAPL", side="BUY", quantity=10,
                         order_id=f"o{i}", status="FILLED")
            log_order(db, f"2024-01-0{i+1}", order)
        rows = get_orders(db)
        assert len(rows) == 3

    def test_date_range_filter(self, db):
        for i in range(5):
            order = Order(ticker="AAPL", side="BUY", quantity=10,
                         order_id=f"o{i}", status="FILLED")
            log_order(db, f"2024-01-0{i+1}", order)
        rows = get_orders(db, from_date="2024-01-02", to_date="2024-01-04")
        assert len(rows) == 3
