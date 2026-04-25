"""Tests for DataHandler PIT enforcement and end-to-end engine semantics.

These tests pin down behavior that distinguishes the event-driven engine
from a vectorized one:
  - BarHistory raises if asked to hold data past its as_of timestamp.
  - DataHandler.next_bar returns the strictly-next bar, never the same.
  - Engine fills use next-bar opens; same-bar fills are impossible.
  - Synthetic flat-market end-to-end loses ~costs and nothing more.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.event_driven import (
    BarHistory,
    DataHandler,
    EngineConfig,
    EventDrivenEngine,
    ExecutionHandler,
    FlatSlippageModel,
    MomentumLongShort,
    Portfolio,
    SignalEvent,
    Strategy,
)


def _make_frame(prices, volume=1_000_000, start="2020-01-02"):
    idx = pd.bdate_range(start=start, periods=len(prices))
    return pd.DataFrame(
        {
            "Open": prices,
            "High": [p * 1.005 for p in prices],
            "Low": [p * 0.995 for p in prices],
            "Close": prices,
            "Volume": [volume] * len(prices),
        },
        index=idx,
    )


# ── BarHistory PIT enforcement ────────────────────────────────────────


class TestBarHistory:
    def test_construction_rejects_data_past_as_of(self):
        idx = pd.bdate_range("2024-01-02", periods=5)
        df = pd.DataFrame({"Close": [1, 2, 3, 4, 5]}, index=idx)
        with pytest.raises(ValueError, match="PIT violation"):
            BarHistory(as_of=idx[2], frames={"AAPL": df})

    def test_construction_accepts_data_at_or_before_as_of(self):
        idx = pd.bdate_range("2024-01-02", periods=5)
        df = pd.DataFrame(
            {
                "Open": [1, 2, 3, 4, 5],
                "High": [1, 2, 3, 4, 5],
                "Low": [1, 2, 3, 4, 5],
                "Close": [1, 2, 3, 4, 5],
                "Volume": [1, 2, 3, 4, 5],
            },
            index=idx,
        )
        h = BarHistory(as_of=idx[4], frames={"AAPL": df.loc[: idx[4]]})
        assert h.latest_close("AAPL") == 5

    def test_unknown_ticker_raises(self):
        h = BarHistory(as_of=pd.Timestamp("2024-01-02"), frames={})
        with pytest.raises(KeyError, match="unknown ticker"):
            h.history("AAPL")


# ── DataHandler ───────────────────────────────────────────────────────


class TestDataHandler:
    def test_next_bar_is_strictly_after(self):
        df = _make_frame([100, 101, 102, 103, 104])
        dh = DataHandler({"AAPL": df})
        result = dh.next_bar("AAPL", df.index[2])
        assert result is not None
        ts, bar = result
        assert ts == df.index[3]
        assert bar["Open"] == 103

    def test_next_bar_returns_none_at_end_of_data(self):
        df = _make_frame([100, 101])
        dh = DataHandler({"AAPL": df})
        assert dh.next_bar("AAPL", df.index[-1]) is None

    def test_view_as_of_slices_strictly(self):
        df = _make_frame(list(range(100, 110)))
        dh = DataHandler({"AAPL": df})
        view = dh.view_as_of(df.index[4])
        # latest_close at index 4 is value 104 in the prices [100..109]
        assert view.latest_close("AAPL") == 104
        assert len(view.history("AAPL")) == 5

    def test_unsorted_index_rejected(self):
        idx = pd.DatetimeIndex(["2024-01-04", "2024-01-02", "2024-01-03"])
        df = pd.DataFrame(
            {c: [1.0, 2.0, 3.0] for c in ("Open", "High", "Low", "Close", "Volume")},
            index=idx,
        )
        with pytest.raises(ValueError, match="sorted"):
            DataHandler({"AAPL": df})

    def test_missing_required_columns_rejected(self):
        idx = pd.bdate_range("2024-01-02", periods=3)
        df = pd.DataFrame({"Close": [1.0, 2.0, 3.0]}, index=idx)
        with pytest.raises(ValueError, match="missing required columns"):
            DataHandler({"AAPL": df})


# ── End-to-end: synthetic flat market loses only costs ────────────────


class _AlwaysLongAAPL(Strategy):
    """Trivial strategy: keep AAPL at 50% NAV, MSFT flat."""

    def on_bar(self, history):
        return [
            SignalEvent(history.as_of, "AAPL", target_weight=0.5, strategy_id="t"),
            SignalEvent(history.as_of, "MSFT", target_weight=0.0, strategy_id="t"),
        ]


class TestEngineEndToEnd:
    def test_flat_market_only_loses_costs(self):
        """If prices never move, NAV decay must equal exactly the realized
        slippage + commission paid on the initial allocation. No other
        cost path should silently appear."""
        n = 60
        flat = _make_frame([100.0] * n)
        flat_msft = _make_frame([200.0] * n)
        dh = DataHandler({"AAPL": flat, "MSFT": flat_msft})

        slippage_bps = 5.0
        commission_bps = 1.0
        eh = ExecutionHandler(
            FlatSlippageModel(slippage_bps=slippage_bps, commission_bps=commission_bps)
        )
        p = Portfolio(initial_cash=1_000_000)

        engine = EventDrivenEngine(
            data_handler=dh,
            strategy=_AlwaysLongAAPL(),
            execution_handler=eh,
            portfolio=p,
            config=EngineConfig(rebalance_freq=10_000, initial_cash=1_000_000),
        )
        result = engine.run()

        assert result.skipped_orders == 0
        assert "AAPL" in p.positions
        # Expected cost: one buy of ~50% NAV at 100 = ~5,000 shares
        # Cost ≈ notional × (slippage_bps + commission_bps) / 1e4
        # = 500_000 × 6e-4 = 300
        final_nav = p.nav_history[-1].nav
        loss = 1_000_000 - final_nav
        assert 250 < loss < 350, f"Expected loss in [250, 350], got {loss}"

    def test_no_lookahead_in_strategy_data(self):
        """The strategy must never see its own future. We probe by
        asserting that, at every rebalance, the BarHistory's latest
        timestamp equals as_of and not anything beyond."""
        captured = []

        class ProbeStrategy(Strategy):
            def on_bar(inner_self, history):
                for tk in history.tickers():
                    df = history.history(tk)
                    if not df.empty:
                        captured.append((history.as_of, df.index.max()))
                return []

        df = _make_frame(list(range(100, 130)))
        dh = DataHandler({"AAPL": df})
        engine = EventDrivenEngine(
            data_handler=dh,
            strategy=ProbeStrategy(),
            execution_handler=ExecutionHandler(),
            config=EngineConfig(rebalance_freq=1, initial_cash=1_000_000),
        )
        engine.run()
        assert captured, "strategy was never invoked"
        for as_of, last_seen in captured:
            assert last_seen <= as_of, (
                f"PIT leak: strategy at as_of={as_of} saw row at {last_seen}"
            )

    def test_momentum_strategy_runs_on_synthetic_trends(self):
        """Smoke test the reference momentum strategy on a small synthetic
        universe with deliberate trends. Requirement: it runs without
        errors and produces a NAV series of the expected length."""
        n = 400
        rng = np.random.default_rng(42)
        tickers = [f"TKR{i:02d}" for i in range(10)]
        frames = {}
        for k, tk in enumerate(tickers):
            drift = 0.0005 * (k - 4.5)  # spread of trends across tickers
            shocks = rng.normal(loc=drift, scale=0.012, size=n)
            prices = 100.0 * np.exp(np.cumsum(shocks))
            frames[tk] = _make_frame(prices.tolist())

        dh = DataHandler(frames)
        strat = MomentumLongShort(lookback_days=252, skip_days=21,
                                   long_pct=0.2, short_pct=0.2)
        engine = EventDrivenEngine(
            data_handler=dh,
            strategy=strat,
            execution_handler=ExecutionHandler(),
            config=EngineConfig(rebalance_freq=21, initial_cash=1_000_000,
                                warmup_bars=253),
        )
        result = engine.run()
        assert len(result.rebalance_dates) > 0
        nav = result.portfolio.nav_series()
        assert len(nav) > 0
        assert nav.iloc[0] > 0
        # Sanity: NAV stays positive (no crashes through zero)
        assert (nav > 0).all()
