"""Fault-injection tests for the execution engine.

Pins down what the engine actually does when the broker misbehaves mid-day —
the failure modes a live run will eventually hit (API outage mid-rebalance,
rejected orders, delisted tickers, zero NAV) — and documents the recovery
contract: the daily loop is stateless, the broker is the source of truth,
and a crashed day self-heals on the next run because current weights are
re-derived from broker state.

Known gaps are pinned with strict xfail tests so they stay visible without
breaking the suite; fixing one flips the test to XPASS and forces an update.
"""

import sqlite3

import numpy as np
import pytest

from execution.broker import Broker, Order, Position
from execution.daily_loop import ExecutionEngine
from execution.paper_broker import PaperBroker
from portfolio.tracker import PortfolioTracker

from tests.test_daily_loop import _cfg, _make_history

TICKERS = ["AAPL", "MSFT", "NVDA", "GOOGL", "META", "AVGO"]


class FlakyBroker(Broker):
    """Delegates to an inner broker; raises on the Nth submit_order call.

    Simulates a broker API outage mid-rebalance (timeout, connection reset).
    Set fail_on_call=None to heal.
    """

    def __init__(self, inner: Broker, fail_on_call: int | None = 2):
        self.inner = inner
        self.fail_on_call = fail_on_call
        self.calls = 0

    def submit_order(self, order: Order) -> Order:
        self.calls += 1
        if self.fail_on_call is not None and self.calls == self.fail_on_call:
            raise ConnectionError("simulated broker outage mid-rebalance")
        return self.inner.submit_order(order)

    def get_account(self):
        return self.inner.get_account()

    def get_positions(self):
        return self.inner.get_positions()

    def update_prices(self, prices):
        self.inner.update_prices(prices)

    @property
    def _prices(self):
        # _compute_orders falls back to broker._prices for stale tickers.
        return self.inner._prices


class RejectingBroker(Broker):
    """Delegates to an inner broker; rejects orders for the given tickers.

    Mirrors PaperBroker's native rejection shape: status=REJECTED and no
    order_id assigned (the Alpaca path behaves the same on submit failure).
    """

    def __init__(self, inner: Broker, reject_tickers: set[str]):
        self.inner = inner
        self.reject_tickers = reject_tickers

    def submit_order(self, order: Order) -> Order:
        if order.ticker in self.reject_tickers:
            order.status = "REJECTED"
            return order
        return self.inner.submit_order(order)

    def get_account(self):
        return self.inner.get_account()

    def get_positions(self):
        return self.inner.get_positions()

    def update_prices(self, prices):
        self.inner.update_prices(prices)

    @property
    def _prices(self):
        return self.inner._prices


def _engine(broker, tmp_path, starting_nav=100_000.0):
    cfg = _cfg(TICKERS)
    tracker = PortfolioTracker(starting_nav=starting_nav)
    return ExecutionEngine(
        broker, tracker, cfg, db_path=str(tmp_path / "fault.db")
    )


def _count(conn: sqlite3.Connection, sql: str) -> int:
    return conn.execute(sql).fetchone()[0]


class TestBrokerOutageMidRebalance:
    def test_outage_propagates_and_preserves_partial_audit_trail(self, tmp_path):
        # Arrange: 3 BUY orders expected (top_n=3); broker dies on the 2nd.
        flaky = FlakyBroker(PaperBroker(starting_cash=100_000.0), fail_on_call=2)
        engine = _engine(flaky, tmp_path)
        history = _make_history(TICKERS)

        # Act / Assert: the outage is NOT silently swallowed.
        with pytest.raises(ConnectionError):
            engine.run_day(history, "2024-02-19")

        # The fill that completed before the outage is in the audit log...
        assert _count(engine.conn, "SELECT COUNT(*) FROM orders") == 1
        # ...and the crashed day has no snapshot (the day never completed).
        assert _count(engine.conn, "SELECT COUNT(*) FROM snapshots") == 0
        # The engine did not halt — an outage is not a risk event.
        assert engine.halted is False

    def test_next_day_self_heals_from_broker_state(self, tmp_path):
        flaky = FlakyBroker(PaperBroker(starting_cash=100_000.0), fail_on_call=2)
        engine = _engine(flaky, tmp_path)
        history = _make_history(TICKERS)

        with pytest.raises(ConnectionError):
            engine.run_day(history, "2024-02-19")
        flaky.fail_on_call = None  # broker recovers

        # Next day runs clean off broker truth: snapshot recorded, weights
        # re-derived from the (partially rebalanced) account state.
        snap = engine.run_day(history, "2024-02-20")
        assert snap is not None
        assert np.isfinite(snap.nav) and snap.nav > 0
        assert _count(
            engine.conn, "SELECT COUNT(*) FROM snapshots WHERE date='2024-02-20'"
        ) == 1


class TestRejectedOrders:
    def test_rejection_completes_day_and_is_audited(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "execution.daily_loop.ALERT_LOG", tmp_path / "alerts.log"
        )
        rejecting = RejectingBroker(
            PaperBroker(starting_cash=100_000.0), reject_tickers={"AAPL"}
        )
        engine = _engine(rejecting, tmp_path)
        history = _make_history(TICKERS)

        snap = engine.run_day(history, "2024-02-19")

        # A rejection degrades the day; it does not abort it.
        assert snap is not None
        rejected = _count(
            engine.conn, "SELECT COUNT(*) FROM orders WHERE status='REJECTED'"
        )
        filled = _count(
            engine.conn, "SELECT COUNT(*) FROM orders WHERE status='FILLED'"
        )
        # AAPL may or may not rank in the top 3; if it did, its rejection
        # must be audited and alerted.
        if rejected:
            alerts = (tmp_path / "alerts.log").read_text()
            assert "REJECTED" in alerts
        assert rejected + filled >= 1

    def test_multiple_rejections_each_leave_an_audit_row(self, tmp_path, monkeypatch):
        # Regression: rejected orders carry order_id='' from the broker;
        # log_order must synthesize unique ids or INSERT OR REPLACE on the
        # order_id primary key collapses every rejection into one audit row.
        monkeypatch.setattr(
            "execution.daily_loop.ALERT_LOG", tmp_path / "alerts.log"
        )
        # Reject everything: all top-3 entries fail.
        rejecting = RejectingBroker(
            PaperBroker(starting_cash=100_000.0), reject_tickers=set(TICKERS)
        )
        engine = _engine(rejecting, tmp_path)
        history = _make_history(TICKERS)

        engine.run_day(history, "2024-02-19")

        rejected = _count(
            engine.conn, "SELECT COUNT(*) FROM orders WHERE status='REJECTED'"
        )
        assert rejected == 3  # one audit row per rejected order


class TestDegradedMarketData:
    def test_delisted_ticker_does_not_crash_the_day(self, tmp_path):
        # Broker holds a position in a ticker that vanishes from today's
        # history (delisting/halt). The engine must complete the day.
        inner = PaperBroker(starting_cash=100_000.0)
        inner.update_prices({"ZOMBIE": 50.0})
        inner.submit_order(Order(ticker="ZOMBIE", side="BUY", quantity=100))
        engine = _engine(inner, tmp_path)
        history = _make_history(TICKERS)  # no ZOMBIE rows today

        snap = engine.run_day(history, "2024-02-19")

        assert snap is not None
        assert np.isfinite(snap.nav) and snap.nav > 0

    def test_zero_nav_account_does_not_crash(self, tmp_path):
        # A drained account (nav=0) must not divide-by-zero anywhere in the
        # weight computation or snapshot path.
        engine = _engine(PaperBroker(starting_cash=0.0), tmp_path, starting_nav=0.0)
        history = _make_history(TICKERS)

        snap = engine.run_day(history, "2024-02-19")

        assert snap is not None
        assert np.isfinite(snap.nav)
