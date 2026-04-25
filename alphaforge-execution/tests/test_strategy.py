"""Tests for momentum ranking strategy."""

import numpy as np
import pandas as pd
import pytest

from strategy.momentum import Signal, TargetPortfolio, compute_signals, generate_target_weights


def _make_history(tickers, n_days=50, seed=42):
    """Create synthetic price history for testing."""
    rng = np.random.RandomState(seed)
    history = {}
    for i, ticker in enumerate(tickers):
        base = 100 + i * 20
        prices = base * np.cumprod(1 + rng.randn(n_days) * 0.02)
        df = pd.DataFrame({
            "Close": prices,
            "Volume": rng.randint(100_000, 1_000_000, n_days),
        }, index=pd.date_range("2024-01-01", periods=n_days))
        history[ticker] = df
    return history


class TestComputeSignals:
    def test_returns_signals_for_all_tickers(self):
        history = _make_history(["AAPL", "MSFT", "NVDA"])
        signals = compute_signals(history)
        assert len(signals) == 3

    def test_signals_sorted_by_composite(self):
        history = _make_history(["AAPL", "MSFT", "NVDA", "GOOGL"])
        signals = compute_signals(history)
        composites = [s.composite for s in signals]
        assert composites == sorted(composites, reverse=True)

    def test_ranks_assigned(self):
        history = _make_history(["AAPL", "MSFT", "NVDA"])
        signals = compute_signals(history)
        ranks = [s.rank for s in signals]
        assert ranks == [1, 2, 3]

    def test_insufficient_history_skipped(self):
        """Tickers with only 1 day of data should be skipped."""
        history = {
            "AAPL": pd.DataFrame({"Close": [100.0]}, index=[pd.Timestamp("2024-01-01")]),
        }
        signals = compute_signals(history)
        assert len(signals) == 0

    def test_short_history_no_mean_reversion(self):
        """< 21 days means mean reversion = 0."""
        history = _make_history(["AAPL"], n_days=10)
        signals = compute_signals(history)
        assert len(signals) == 1
        assert signals[0].mean_reversion == 0.0

    def test_custom_weights(self):
        history = _make_history(["AAPL", "MSFT"])
        s1 = compute_signals(history, mom_5d_weight=1.0, mom_21d_weight=0.0, mr_weight=0.0)
        s2 = compute_signals(history, mom_5d_weight=0.0, mom_21d_weight=1.0, mr_weight=0.0)
        # Different weights should generally produce different composites
        assert s1[0].composite != s2[0].composite

    def test_day_index_parameter(self):
        history = _make_history(["AAPL"], n_days=50)
        s_latest = compute_signals(history, day_index=-1)
        s_mid = compute_signals(history, day_index=25)
        # Different day_index should give different signals
        assert s_latest[0].mom_5d != s_mid[0].mom_5d

    def test_division_by_zero_safety(self):
        """Near-zero prices should not crash."""
        df = pd.DataFrame({
            "Close": [1e-12] * 30,
            "Volume": [100_000] * 30,
        }, index=pd.date_range("2024-01-01", periods=30))
        signals = compute_signals({"AAPL": df})
        assert len(signals) == 1
        assert np.isfinite(signals[0].composite)


class TestGenerateTargetWeights:
    def test_top_n_selection(self):
        history = _make_history(["AAPL", "MSFT", "NVDA", "GOOGL", "META", "AVGO"])
        target = generate_target_weights(history, top_n=3, position_weight=0.05)
        assert len(target.weights) == 3
        assert all(w == 0.05 for w in target.weights.values())

    def test_all_signals_included(self):
        history = _make_history(["AAPL", "MSFT", "NVDA"])
        target = generate_target_weights(history, top_n=2)
        assert len(target.signals) == 3  # all tickers ranked

    def test_date_extracted(self):
        history = _make_history(["AAPL"], n_days=30)
        target = generate_target_weights(history)
        assert target.date != ""

    def test_top_n_exceeds_universe(self):
        """top_n > number of tickers should still work."""
        history = _make_history(["AAPL", "MSFT"])
        target = generate_target_weights(history, top_n=10, position_weight=0.05)
        assert len(target.weights) == 2

    def test_empty_history(self):
        target = generate_target_weights({}, top_n=5)
        assert len(target.weights) == 0
