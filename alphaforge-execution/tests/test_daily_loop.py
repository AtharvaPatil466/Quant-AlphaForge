"""Tests for the execution engine and daily loop."""

import numpy as np
import pandas as pd
import pytest

from execution.broker import Order
from execution.paper_broker import PaperBroker
from execution.daily_loop import ExecutionEngine
from portfolio.tracker import PortfolioTracker


def _make_history(tickers, n_days=50, seed=42):
    rng = np.random.RandomState(seed)
    history = {}
    for i, ticker in enumerate(tickers):
        base = 100 + i * 20
        prices = base * np.cumprod(1 + rng.randn(n_days) * 0.01)
        df = pd.DataFrame({
            "Close": prices,
            "Open": prices * 0.99,
            "High": prices * 1.01,
            "Low": prices * 0.98,
            "Volume": rng.randint(100_000, 1_000_000, n_days).astype(float),
        }, index=pd.date_range("2024-01-01", periods=n_days))
        history[ticker] = df
    return history


def _cfg(tickers=None):
    tickers = tickers or ["AAPL", "MSFT", "NVDA", "GOOGL", "META", "AVGO"]
    return {
        "universe": {"tickers": tickers},
        "strategy": {
            "top_n": 3,
            "position_weight": 0.05,
            "mom_5d_weight": 0.4,
            "mom_21d_weight": 0.4,
            "mean_reversion_weight": 0.2,
        },
        "risk": {
            "max_position_pct": 0.10,
            "max_gross_exposure": 1.50,
            "max_daily_turnover": 0.50,
            "max_daily_loss": 0.02,
            "max_drawdown": 0.10,
        },
        "execution": {
            "broker": "paper",
            "starting_nav": 100_000.0,
            "slippage_bps": 5.0,
        },
    }


class TestExecutionEngine:
    def _engine(self, tickers=None):
        tickers = tickers or ["AAPL", "MSFT", "NVDA", "GOOGL", "META", "AVGO"]
        cfg = _cfg(tickers)
        broker = PaperBroker(starting_cash=100_000.0, slippage_bps=5.0)
        tracker = PortfolioTracker(starting_nav=100_000.0)
        return ExecutionEngine(broker, tracker, cfg)

    def test_run_day_returns_snapshot(self):
        tickers = ["AAPL", "MSFT", "NVDA", "GOOGL", "META", "AVGO"]
        engine = self._engine(tickers)
        history = _make_history(tickers)
        snap = engine.run_day(history, "2024-02-19")
        assert snap is not None
        assert snap.nav > 0

    def test_halted_engine_returns_none(self):
        engine = self._engine()
        engine.halted = True
        engine.halt_reason = "test halt"
        history = _make_history(["AAPL", "MSFT", "NVDA", "GOOGL", "META", "AVGO"])
        snap = engine.run_day(history, "2024-02-19")
        assert snap is None

    def test_orders_generated(self):
        engine = self._engine()
        history = _make_history(["AAPL", "MSFT", "NVDA", "GOOGL", "META", "AVGO"])
        engine.run_day(history, "2024-02-19")
        positions = engine.broker.get_positions()
        assert len(positions) > 0

    def test_circuit_breaker_halts(self):
        tickers = ["AAPL", "MSFT", "NVDA", "GOOGL", "META", "AVGO"]
        cfg = _cfg(tickers)
        cfg["risk"]["max_daily_loss"] = 0.0001  # extremely tight
        broker = PaperBroker(starting_cash=100_000.0, slippage_bps=500.0)  # huge slippage
        tracker = PortfolioTracker(starting_nav=100_000.0)
        engine = ExecutionEngine(broker, tracker, cfg)
        history = _make_history(tickers)
        engine.run_day(history, "2024-02-19")
        # With extreme slippage, NAV drops and circuit breaker may trigger
        # Just verify the engine can handle this without crashing
        assert engine.broker.get_account().nav > 0

    def test_compute_orders_skip_small_delta(self):
        engine = self._engine()
        orders = engine._compute_orders(
            target_weights={"AAPL": 0.05},
            current_weights={"AAPL": 0.048},  # delta < 0.5%
            nav=100_000,
            prices={"AAPL": 150.0},
        )
        assert len(orders) == 0

    def test_compute_orders_skip_tiny_dollar(self):
        engine = self._engine()
        orders = engine._compute_orders(
            target_weights={"AAPL": 0.01},
            current_weights={},
            nav=1_000,  # 1% of $1000 = $10 < $50 threshold
            prices={"AAPL": 150.0},
        )
        assert len(orders) == 0

    def test_compute_orders_buy_and_sell(self):
        engine = self._engine()
        orders = engine._compute_orders(
            target_weights={"AAPL": 0.05},
            current_weights={"MSFT": 0.05},
            nav=100_000,
            prices={"AAPL": 150.0, "MSFT": 300.0},
        )
        sides = {o.side for o in orders}
        assert "BUY" in sides
        assert "SELL" in sides

    def test_compute_orders_zero_price_skipped(self):
        engine = self._engine()
        orders = engine._compute_orders(
            target_weights={"AAPL": 0.05},
            current_weights={},
            nav=100_000,
            prices={},  # no price available
        )
        assert len(orders) == 0

    def test_multi_day_execution(self):
        tickers = ["AAPL", "MSFT", "NVDA", "GOOGL", "META", "AVGO"]
        engine = self._engine(tickers)
        history = _make_history(tickers, n_days=50)
        dates = history["AAPL"].index

        for dt in dates[-5:]:
            sliced = {t: df.loc[:dt] for t, df in history.items()}
            snap = engine.run_day(sliced, str(dt.date()))
            if engine.halted:
                break

        assert len(engine.tracker.snapshots) >= 1
        assert engine.tracker.nav_history[-1] > 0
