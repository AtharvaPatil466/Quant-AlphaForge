"""Unit tests for event-driven engine primitives: events, execution, portfolio.

These tests pin down the architectural invariants that distinguish the
event-driven engine from a vectorized panel sweep:
  - Orders cannot fill on the bar that generated them.
  - Slippage moves the fill price *against* the trade direction.
  - Portfolio cash and positions move atomically and conservatively.
  - NAV marks fail loudly on missing prices rather than silently zeroing.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from backtest.event_driven import (
    ExecutionHandler,
    FillEvent,
    FlatSlippageModel,
    OrderEvent,
    OrderSide,
    Portfolio,
)


# ── Event dataclass invariants ────────────────────────────────────────


class TestEvents:
    def test_order_quantity_must_be_positive(self):
        ts = pd.Timestamp("2024-01-02")
        with pytest.raises(ValueError, match="quantity must be positive"):
            OrderEvent(timestamp=ts, ticker="AAPL", quantity=0.0, side=OrderSide.BUY)
        with pytest.raises(ValueError, match="quantity must be positive"):
            OrderEvent(timestamp=ts, ticker="AAPL", quantity=-10.0, side=OrderSide.BUY)

    def test_fill_signed_quantity(self):
        ts = pd.Timestamp("2024-01-02")
        buy = FillEvent(ts, "AAPL", 10, OrderSide.BUY, 100.0, 1.0, 0.5)
        sell = FillEvent(ts, "AAPL", 10, OrderSide.SELL, 100.0, 1.0, 0.5)
        assert buy.signed_quantity == 10
        assert sell.signed_quantity == -10

    def test_fill_cash_delta_is_negative_for_buy(self):
        ts = pd.Timestamp("2024-01-02")
        buy = FillEvent(ts, "AAPL", 10, OrderSide.BUY, 100.0, 1.0, 0.5)
        # Cash out = -1000 - 1 commission
        assert buy.cash_delta == pytest.approx(-1001.0)

    def test_fill_cash_delta_is_positive_for_sell(self):
        ts = pd.Timestamp("2024-01-02")
        sell = FillEvent(ts, "AAPL", 10, OrderSide.SELL, 100.0, 1.0, 0.5)
        # Cash in = +1000 - 1 commission
        assert sell.cash_delta == pytest.approx(999.0)


# ── Execution: the no-look-ahead invariant ────────────────────────────


class TestExecutionHandler:
    def test_fill_must_use_strictly_later_bar(self):
        eh = ExecutionHandler()
        ts = pd.Timestamp("2024-01-02")
        order = OrderEvent(ts, "AAPL", 10, OrderSide.BUY)
        with pytest.raises(ValueError, match="strictly after"):
            eh.execute(order, next_bar_timestamp=ts, next_bar_open=100.0)
        with pytest.raises(ValueError, match="strictly after"):
            eh.execute(
                order,
                next_bar_timestamp=pd.Timestamp("2024-01-01"),
                next_bar_open=100.0,
            )

    def test_buy_fill_price_above_open(self):
        eh = ExecutionHandler(FlatSlippageModel(slippage_bps=10.0, commission_bps=0.0))
        order = OrderEvent(pd.Timestamp("2024-01-02"), "AAPL", 100, OrderSide.BUY)
        fill = eh.execute(order, pd.Timestamp("2024-01-03"), next_bar_open=100.0)
        assert fill.fill_price == pytest.approx(100.10)
        assert fill.slippage_cost == pytest.approx(0.10 * 100)

    def test_sell_fill_price_below_open(self):
        eh = ExecutionHandler(FlatSlippageModel(slippage_bps=10.0, commission_bps=0.0))
        order = OrderEvent(pd.Timestamp("2024-01-02"), "AAPL", 100, OrderSide.SELL)
        fill = eh.execute(order, pd.Timestamp("2024-01-03"), next_bar_open=100.0)
        assert fill.fill_price == pytest.approx(99.90)

    def test_commission_scales_with_notional(self):
        eh = ExecutionHandler(FlatSlippageModel(slippage_bps=0.0, commission_bps=5.0))
        order = OrderEvent(pd.Timestamp("2024-01-02"), "AAPL", 100, OrderSide.BUY)
        fill = eh.execute(order, pd.Timestamp("2024-01-03"), next_bar_open=100.0)
        # 100 * 100 * 5bps = 5
        assert fill.commission == pytest.approx(5.0)

    def test_zero_or_negative_open_rejected(self):
        eh = ExecutionHandler()
        order = OrderEvent(pd.Timestamp("2024-01-02"), "AAPL", 10, OrderSide.BUY)
        with pytest.raises(ValueError, match="must be positive"):
            eh.execute(order, pd.Timestamp("2024-01-03"), next_bar_open=0.0)
        with pytest.raises(ValueError, match="must be positive"):
            eh.execute(order, pd.Timestamp("2024-01-03"), next_bar_open=-1.0)


# ── Portfolio: position and cash bookkeeping ──────────────────────────


class TestPortfolio:
    def test_initial_state(self):
        p = Portfolio(initial_cash=1_000_000)
        assert p.cash == 1_000_000
        assert p.positions == {}
        assert p.fills == []
        assert p.nav_history == []

    def test_negative_initial_cash_rejected(self):
        with pytest.raises(ValueError):
            Portfolio(initial_cash=0)
        with pytest.raises(ValueError):
            Portfolio(initial_cash=-1)

    def test_buy_then_sell_round_trip(self):
        p = Portfolio(1_000_000)
        ts = pd.Timestamp("2024-01-03")
        p.apply_fill(FillEvent(ts, "AAPL", 100, OrderSide.BUY, 100.0, 1.0, 0.0))
        assert p.positions["AAPL"] == 100
        assert p.cash == pytest.approx(990_000 - 1.0)

        p.apply_fill(
            FillEvent(pd.Timestamp("2024-01-10"), "AAPL", 100, OrderSide.SELL, 110.0, 1.0, 0.0)
        )
        assert "AAPL" not in p.positions
        # cash: 990_000 - 1 + 11_000 - 1 = 1_000_998 (P&L = 1000 - 2 commission)
        assert p.cash == pytest.approx(1_000_998.0)

    def test_partial_close_keeps_position(self):
        p = Portfolio(1_000_000)
        ts = pd.Timestamp("2024-01-03")
        p.apply_fill(FillEvent(ts, "AAPL", 100, OrderSide.BUY, 100.0, 0.0, 0.0))
        p.apply_fill(
            FillEvent(pd.Timestamp("2024-01-10"), "AAPL", 40, OrderSide.SELL, 105.0, 0.0, 0.0)
        )
        assert p.positions["AAPL"] == 60

    def test_short_position_sign(self):
        p = Portfolio(1_000_000)
        ts = pd.Timestamp("2024-01-03")
        p.apply_fill(FillEvent(ts, "AAPL", 50, OrderSide.SELL, 100.0, 0.0, 0.0))
        assert p.positions["AAPL"] == -50
        # Selling adds cash on a short.
        assert p.cash == pytest.approx(1_005_000.0)

    def test_mark_to_market_records_nav(self):
        p = Portfolio(1_000_000)
        p.apply_fill(
            FillEvent(pd.Timestamp("2024-01-03"), "AAPL", 100, OrderSide.BUY, 100.0, 0.0, 0.0)
        )
        mark = p.mark_to_market(pd.Timestamp("2024-01-04"), {"AAPL": 110.0})
        assert mark.nav == pytest.approx(990_000 + 100 * 110)
        assert mark.gross_exposure == pytest.approx(11_000)
        assert mark.net_exposure == pytest.approx(11_000)
        assert len(p.nav_history) == 1

    def test_mark_to_market_short_exposure_signs(self):
        p = Portfolio(1_000_000)
        p.apply_fill(
            FillEvent(pd.Timestamp("2024-01-03"), "TSLA", 50, OrderSide.SELL, 200.0, 0.0, 0.0)
        )
        mark = p.mark_to_market(pd.Timestamp("2024-01-04"), {"TSLA": 180.0})
        # Short closed at +20/share gain on 50 shares = 1000 unrealized
        assert mark.nav == pytest.approx(1_001_000)
        assert mark.gross_exposure == pytest.approx(9_000)  # |short| value
        assert mark.net_exposure == pytest.approx(-9_000)

    def test_mark_to_market_raises_on_missing_price(self):
        p = Portfolio(1_000_000)
        p.apply_fill(
            FillEvent(pd.Timestamp("2024-01-03"), "AAPL", 100, OrderSide.BUY, 100.0, 0.0, 0.0)
        )
        with pytest.raises(KeyError, match="no price for held ticker 'AAPL'"):
            p.mark_to_market(pd.Timestamp("2024-01-04"), {"MSFT": 300.0})

    def test_current_weights_sum_to_invested_fraction(self):
        p = Portfolio(1_000_000)
        p.apply_fill(
            FillEvent(pd.Timestamp("2024-01-03"), "AAPL", 100, OrderSide.BUY, 100.0, 0.0, 0.0)
        )
        p.apply_fill(
            FillEvent(pd.Timestamp("2024-01-03"), "MSFT", 50, OrderSide.BUY, 200.0, 0.0, 0.0)
        )
        weights = p.current_weights({"AAPL": 100.0, "MSFT": 200.0})
        # NAV = 980k cash + 10k + 10k = 1_000_000; weights = 1% each
        assert weights["AAPL"] == pytest.approx(0.01)
        assert weights["MSFT"] == pytest.approx(0.01)

    def test_nav_series_indexed_by_timestamp(self):
        p = Portfolio(1_000_000)
        p.mark_to_market(pd.Timestamp("2024-01-03"), {})
        p.mark_to_market(pd.Timestamp("2024-01-04"), {})
        s = p.nav_series()
        assert isinstance(s.index, pd.DatetimeIndex)
        assert list(s.values) == [1_000_000, 1_000_000]


# ── End-to-end: order → fill → portfolio ──────────────────────────────


class TestEndToEnd:
    def test_round_trip_with_costs_loses_money_on_flat_market(self):
        """Flat market + nonzero costs must produce a NAV loss. If a
        backtest reports breakeven on a flat market with costs, costs
        are not actually being charged."""
        p = Portfolio(1_000_000)
        eh = ExecutionHandler(FlatSlippageModel(slippage_bps=10.0, commission_bps=1.0))

        decision = pd.Timestamp("2024-01-02")
        next_bar = pd.Timestamp("2024-01-03")

        buy_order = OrderEvent(decision, "AAPL", 100, OrderSide.BUY)
        buy_fill = eh.execute(buy_order, next_bar, next_bar_open=100.0)
        p.apply_fill(buy_fill)

        sell_decision = pd.Timestamp("2024-01-04")
        sell_next = pd.Timestamp("2024-01-05")
        sell_order = OrderEvent(sell_decision, "AAPL", 100, OrderSide.SELL)
        sell_fill = eh.execute(sell_order, sell_next, next_bar_open=100.0)
        p.apply_fill(sell_fill)

        final_mark = p.mark_to_market(sell_next, {})
        assert final_mark.nav < 1_000_000, (
            "Flat market with costs must lose money. "
            f"NAV={final_mark.nav}, expected < 1_000_000"
        )
        # Loss should be ~ 2 × slippage + 2 × commission
        # = 2 × (100 × 100 × 10bps) + 2 × (100 × 100 × 1bps) ≈ 22
        loss = 1_000_000 - final_mark.nav
        assert 15 < loss < 30, f"Expected loss in [15, 30], got {loss}"
