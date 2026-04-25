"""Tests for broker dataclasses and PaperBroker."""

import pytest

from execution.broker import AccountState, Order, Position
from execution.paper_broker import PaperBroker


# ── Dataclass Properties ────────────────────────────────────────────────────

class TestPosition:
    def test_market_value(self):
        p = Position(ticker="AAPL", quantity=10, avg_cost=150.0, current_price=160.0)
        assert p.market_value == 1600.0

    def test_pnl_positive(self):
        p = Position(ticker="AAPL", quantity=10, avg_cost=150.0, current_price=160.0)
        assert p.pnl == 100.0

    def test_pnl_negative(self):
        p = Position(ticker="AAPL", quantity=5, avg_cost=200.0, current_price=180.0)
        assert p.pnl == -100.0

    def test_zero_quantity(self):
        p = Position(ticker="AAPL", quantity=0, avg_cost=150.0, current_price=160.0)
        assert p.market_value == 0.0
        assert p.pnl == 0.0


class TestAccountState:
    def test_equity_cash_only(self):
        acct = AccountState(nav=100_000, cash=100_000)
        assert acct.equity == 100_000

    def test_equity_with_positions(self):
        pos = {"AAPL": Position("AAPL", 10, 150.0, 160.0)}
        acct = AccountState(nav=101_600, cash=100_000, positions=pos)
        assert acct.equity == 101_600.0

    def test_gross_exposure(self):
        pos = {
            "AAPL": Position("AAPL", 10, 150.0, 160.0),
            "MSFT": Position("MSFT", 5, 300.0, 310.0),
        }
        acct = AccountState(nav=0, cash=0, positions=pos)
        assert acct.gross_exposure == 1600.0 + 1550.0

    def test_empty_positions(self):
        acct = AccountState(nav=50_000, cash=50_000)
        assert acct.gross_exposure == 0.0


# ── PaperBroker ─────────────────────────────────────────────────────────────

class TestPaperBroker:
    def _broker(self, cash=100_000.0, slippage=5.0):
        return PaperBroker(starting_cash=cash, slippage_bps=slippage)

    def test_buy_creates_position(self):
        b = self._broker()
        b.update_prices({"AAPL": 150.0})
        order = Order(ticker="AAPL", side="BUY", quantity=10)
        result = b.submit_order(order)
        assert result.status == "FILLED"
        assert result.fill_quantity == 10
        assert "AAPL" in b.get_positions()

    def test_buy_slippage_applied(self):
        b = self._broker(slippage=10.0)
        b.update_prices({"AAPL": 100.0})
        order = Order(ticker="AAPL", side="BUY", quantity=1)
        result = b.submit_order(order)
        expected_fill = 100.0 * (1 + 10 / 10_000)
        assert abs(result.fill_price - expected_fill) < 1e-6

    def test_sell_slippage_applied(self):
        b = self._broker(slippage=10.0)
        b.update_prices({"AAPL": 100.0})
        b.submit_order(Order(ticker="AAPL", side="BUY", quantity=10))
        result = b.submit_order(Order(ticker="AAPL", side="SELL", quantity=5))
        expected_fill = 100.0 * (1 - 10 / 10_000)
        assert abs(result.fill_price - expected_fill) < 1e-6

    def test_sell_closes_position(self):
        b = self._broker()
        b.update_prices({"AAPL": 150.0})
        b.submit_order(Order(ticker="AAPL", side="BUY", quantity=10))
        b.submit_order(Order(ticker="AAPL", side="SELL", quantity=10))
        assert "AAPL" not in b.get_positions()

    def test_sell_without_position_rejected(self):
        b = self._broker()
        b.update_prices({"AAPL": 150.0})
        result = b.submit_order(Order(ticker="AAPL", side="SELL", quantity=10))
        assert result.status == "REJECTED"

    def test_sell_more_than_held_rejected(self):
        b = self._broker()
        b.update_prices({"AAPL": 150.0})
        b.submit_order(Order(ticker="AAPL", side="BUY", quantity=5))
        result = b.submit_order(Order(ticker="AAPL", side="SELL", quantity=10))
        assert result.status == "REJECTED"

    def test_sell_float_rounding_tolerance(self):
        """Sell quantity within 0.01 of position size should be clamped, not rejected."""
        b = self._broker()
        b.update_prices({"AAPL": 150.0})
        b.submit_order(Order(ticker="AAPL", side="BUY", quantity=10))
        result = b.submit_order(Order(ticker="AAPL", side="SELL", quantity=10.005))
        assert result.status == "FILLED"
        assert "AAPL" not in b.get_positions()

    def test_buy_insufficient_cash_reduces_quantity(self):
        b = self._broker(cash=500.0)
        b.update_prices({"AAPL": 150.0})
        order = Order(ticker="AAPL", side="BUY", quantity=100)
        result = b.submit_order(order)
        assert result.status == "FILLED"
        assert result.fill_quantity < 100
        assert b._cash >= -1e-10  # float precision tolerance

    def test_buy_no_price_rejected(self):
        b = self._broker()
        result = b.submit_order(Order(ticker="AAPL", side="BUY", quantity=10))
        assert result.status == "REJECTED"

    def test_buy_adds_to_existing_position(self):
        b = self._broker()
        b.update_prices({"AAPL": 100.0})
        b.submit_order(Order(ticker="AAPL", side="BUY", quantity=10))
        b.submit_order(Order(ticker="AAPL", side="BUY", quantity=5))
        pos = b.get_positions()["AAPL"]
        assert abs(pos.quantity - 15) < 0.01

    def test_get_account_nav(self):
        b = self._broker(cash=100_000.0)
        b.update_prices({"AAPL": 150.0})
        b.submit_order(Order(ticker="AAPL", side="BUY", quantity=10))
        acct = b.get_account()
        assert acct.nav > 0
        assert acct.cash < 100_000

    def test_update_prices_updates_positions(self):
        b = self._broker()
        b.update_prices({"AAPL": 150.0})
        b.submit_order(Order(ticker="AAPL", side="BUY", quantity=10))
        b.update_prices({"AAPL": 200.0})
        pos = b.get_positions()["AAPL"]
        assert pos.current_price == 200.0

    def test_multiple_tickers(self):
        b = self._broker()
        b.update_prices({"AAPL": 150.0, "MSFT": 300.0})
        b.submit_order(Order(ticker="AAPL", side="BUY", quantity=5))
        b.submit_order(Order(ticker="MSFT", side="BUY", quantity=3))
        positions = b.get_positions()
        assert len(positions) == 2

    def test_order_gets_uuid(self):
        b = self._broker()
        b.update_prices({"AAPL": 150.0})
        result = b.submit_order(Order(ticker="AAPL", side="BUY", quantity=1))
        assert len(result.order_id) == 8

    def test_position_removal_threshold(self):
        """Positions with qty < 0.001 should be removed."""
        b = self._broker()
        b.update_prices({"AAPL": 150.0})
        b.submit_order(Order(ticker="AAPL", side="BUY", quantity=0.001))
        # Sell almost all
        b.submit_order(Order(ticker="AAPL", side="SELL", quantity=0.001))
        assert "AAPL" not in b.get_positions()
