"""Tests for Position and Portfolio classes."""

import pytest

from backtest.portfolio import Position, Portfolio


class TestPosition:
    def test_create(self):
        pos = Position(ticker="AAPL", direction=1.0, entry_price=150.0, entry_day=0)
        assert pos.ticker == "AAPL"
        assert pos.entry_price == 150.0
        assert pos.direction == 1.0

    def test_pnl_long(self):
        pos = Position(ticker="AAPL", direction=1.0, entry_price=100.0, entry_day=0, size=1.0)
        assert pos.pnl(110.0) == pytest.approx(0.1)
        assert pos.pnl(90.0) == pytest.approx(-0.1)

    def test_pnl_short(self):
        pos = Position(ticker="AAPL", direction=-1.0, entry_price=100.0, entry_day=0, size=1.0)
        assert pos.pnl(90.0) == pytest.approx(0.1)
        assert pos.pnl(110.0) == pytest.approx(-0.1)

    def test_stop_loss(self):
        pos = Position(ticker="AAPL", direction=1.0, entry_price=100.0, entry_day=0)
        assert not pos.is_stopped_out(96.0, 0.05)  # -4% < 5% threshold
        assert pos.is_stopped_out(94.0, 0.05)  # -6% > 5% threshold


class TestPortfolio:
    def test_initial_state(self):
        port = Portfolio(nav=100.0)
        assert port.nav == 100.0
        assert port.peak_nav == 100.0
        assert len(port.positions) == 0

    def test_open_position(self):
        port = Portfolio(nav=100.0, tx_cost_bps=5)
        port.open_position("AAPL", 1.0, 150.0, day=0, size=0.1)
        assert len(port.positions) == 1
        assert port.positions[0].ticker == "AAPL"

    def test_close_position(self):
        port = Portfolio(nav=100.0, tx_cost_bps=0)
        port.open_position("AAPL", 1.0, 100.0, day=0, size=1.0)
        pos = port.positions[0]
        pnl = port.close_position(pos, 110.0)
        assert pnl == pytest.approx(0.1)
        assert len(port.positions) == 0

    def test_close_all(self):
        port = Portfolio(nav=100.0, tx_cost_bps=0)
        port.open_position("AAPL", 1.0, 100.0, day=0)
        port.open_position("MSFT", -1.0, 200.0, day=0)
        total = port.close_all({"AAPL": 110.0, "MSFT": 190.0})
        assert len(port.positions) == 0
        assert total > 0  # AAPL +10%, MSFT +5% (short)

    def test_check_stop_losses(self):
        port = Portfolio(nav=100.0, tx_cost_bps=0)
        port.open_position("AAPL", 1.0, 100.0, day=0)
        closed = port.check_stop_losses({"AAPL": 80.0}, stop_loss=0.10)
        assert len(closed) == 1  # -20% > 10% stop

    def test_update_nav(self):
        port = Portfolio(nav=100.0)
        port.update_nav(0.05)
        assert port.nav == pytest.approx(105.0)
        assert port.peak_nav == pytest.approx(105.0)

    def test_drawdown(self):
        port = Portfolio(nav=100.0, peak_nav=120.0)
        dd = port.current_drawdown()
        assert dd == pytest.approx(20 / 120)

    def test_daily_pnl(self):
        port = Portfolio(nav=100.0, tx_cost_bps=0)
        port.open_position("AAPL", 1.0, 100.0, day=0, size=1.0)
        pnl = port.daily_pnl({"AAPL": 105.0})
        assert pnl == pytest.approx(0.05)
