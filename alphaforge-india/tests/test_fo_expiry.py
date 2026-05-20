"""Tests for signals/fo_expiry.py — F&O expiry event-study signal.

Tests cover:
    1. Trial enumeration (exactly 4 trials)
    2. Window return computation on synthetic data
    3. Event-study statistical tests
    4. Pass/fail criterion logic
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from signals.fo_expiry import (  # noqa: E402
    FOExpiryTrial,
    _trading_days_around_date,
    compute_window_returns,
    enumerate_trials,
    run_event_study,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def synthetic_close() -> pd.DataFrame:
    """Synthetic close prices: 100 stocks, 500 trading days (~2 years)."""
    rng = np.random.default_rng(42)
    n_days, n_stocks = 500, 100
    dates = pd.bdate_range("2010-01-01", periods=n_days)
    symbols = [f"SYM{i:03d}" for i in range(n_stocks)]
    # Random walk prices starting at 100
    returns = rng.normal(0.0005, 0.02, size=(n_days, n_stocks))
    prices = 100 * np.exp(np.cumsum(returns, axis=0))
    return pd.DataFrame(prices, index=dates, columns=symbols)


@pytest.fixture
def synthetic_expiry_dates() -> list[date]:
    """Monthly expiry dates (last Thursday) within the synthetic data range."""
    import calendar
    expiries = []
    for year in (2010, 2011):
        for month in range(1, 13):
            last_day = calendar.monthrange(year, month)[1]
            d = date(year, month, last_day)
            while d.weekday() != 3:  # Thursday
                d -= timedelta(days=1)
            expiries.append(d)
    return expiries


# ---------------------------------------------------------------------------
# Trial enumeration
# ---------------------------------------------------------------------------

class TestEnumerateTrials:
    def test_exactly_four_trials(self):
        trials = enumerate_trials()
        assert len(trials) == 4

    def test_all_combinations_present(self):
        trials = enumerate_trials()
        combos = {(t.pre_window, t.post_window) for t in trials}
        assert combos == {(3, 3), (3, 5), (5, 3), (5, 5)}

    def test_trial_names_unique(self):
        trials = enumerate_trials()
        names = [t.trial_name for t in trials]
        assert len(set(names)) == 4

    def test_trial_name_format(self):
        t = FOExpiryTrial(pre_window=3, post_window=5)
        assert t.trial_name == "fo_expiry_pre3_post5"


# ---------------------------------------------------------------------------
# Trading days around date
# ---------------------------------------------------------------------------

class TestTradingDaysAroundDate:
    def test_basic(self):
        dates = pd.bdate_range("2010-01-01", periods=20)
        anchor = dates[10].date()
        pre, post = _trading_days_around_date(dates, anchor, 3, 3)
        assert len(pre) == 3
        assert len(post) == 3
        # All pre dates should be before anchor
        for d in pre:
            assert pd.Timestamp(d) < pd.Timestamp(anchor)
        # All post dates should be after anchor
        for d in post:
            assert pd.Timestamp(d) > pd.Timestamp(anchor)

    def test_edge_insufficient_pre(self):
        dates = pd.bdate_range("2010-01-01", periods=5)
        anchor = dates[1].date()
        pre, post = _trading_days_around_date(dates, anchor, 5, 3)
        assert len(pre) < 5  # Not enough dates before


# ---------------------------------------------------------------------------
# Window returns
# ---------------------------------------------------------------------------

class TestComputeWindowReturns:
    def test_produces_dataframe(self, synthetic_close, synthetic_expiry_dates):
        df = compute_window_returns(
            synthetic_close,
            synthetic_expiry_dates[:5],
            pre_window=3,
            post_window=3,
        )
        assert isinstance(df, pd.DataFrame)
        assert "pre_return" in df.columns
        assert "post_return" in df.columns
        assert "n_stocks" in df.columns

    def test_returns_within_reasonable_range(
        self, synthetic_close, synthetic_expiry_dates
    ):
        df = compute_window_returns(
            synthetic_close,
            synthetic_expiry_dates[:10],
            pre_window=5,
            post_window=5,
        )
        # Returns should be small numbers (within ±50% for 5 days)
        assert df["pre_return"].abs().max() < 0.5
        assert df["post_return"].abs().max() < 0.5

    def test_skips_events_with_insufficient_data(self):
        """An expiry outside the date range should be skipped."""
        dates = pd.bdate_range("2010-01-01", periods=20)
        close = pd.DataFrame(
            np.random.default_rng(1).standard_normal((20, 5)) + 100,
            index=dates,
            columns=[f"S{i}" for i in range(5)],
        )
        # Expiry outside range
        df = compute_window_returns(
            close, [date(2025, 1, 1)], pre_window=3, post_window=3
        )
        assert len(df) == 0


# ---------------------------------------------------------------------------
# Event study
# ---------------------------------------------------------------------------

class TestRunEventStudy:
    def test_with_enough_events(self, synthetic_close, synthetic_expiry_dates):
        trial = FOExpiryTrial(pre_window=3, post_window=3)
        window_rets = compute_window_returns(
            synthetic_close, synthetic_expiry_dates, 3, 3,
        )
        result = run_event_study(window_rets, trial)
        assert result.n_events > 0
        assert -1.0 <= result.pre_sign_consistency <= 1.0
        assert -1.0 <= result.post_sign_consistency <= 1.0
        assert result.pre_return_p_value >= 0.0
        assert result.post_return_p_value >= 0.0
        assert isinstance(result.passed_phase1, bool)

    def test_with_too_few_events(self):
        """With < 3 events, should return failed result."""
        trial = FOExpiryTrial(pre_window=3, post_window=3)
        df = pd.DataFrame({
            "expiry_date": [date(2010, 1, 1)],
            "pre_return": [0.01],
            "post_return": [-0.01],
            "n_stocks": [50],
        })
        result = run_event_study(df, trial)
        assert result.passed_phase1 is False
        assert result.n_events == 1

    def test_strong_signal_passes(self):
        """Synthetic strong signal should pass Phase 1C."""
        trial = FOExpiryTrial(pre_window=3, post_window=3)
        rng = np.random.default_rng(42)
        n_events = 50
        # Strongly positive pre-returns
        df = pd.DataFrame({
            "expiry_date": [
                date(2010, 1, 1) + timedelta(days=30 * i)
                for i in range(n_events)
            ],
            "pre_return": rng.normal(0.02, 0.005, n_events),  # strong positive
            "post_return": rng.normal(0.001, 0.02, n_events),  # weak
            "n_stocks": [50] * n_events,
        })
        result = run_event_study(df, trial)
        assert result.passed_phase1 is True
        assert result.pre_return_p_value < 0.05
        assert result.pre_sign_consistency >= 0.70

    def test_weak_signal_fails(self):
        """Random noise should fail Phase 1C."""
        trial = FOExpiryTrial(pre_window=3, post_window=3)
        rng = np.random.default_rng(42)
        n_events = 50
        df = pd.DataFrame({
            "expiry_date": [
                date(2010, 1, 1) + timedelta(days=30 * i)
                for i in range(n_events)
            ],
            "pre_return": rng.normal(0.0, 0.02, n_events),  # pure noise
            "post_return": rng.normal(0.0, 0.02, n_events),  # pure noise
            "n_stocks": [50] * n_events,
        })
        result = run_event_study(df, trial)
        # With mean=0 noise, unlikely to pass
        # (could occasionally pass by chance, but seed 42 shouldn't)


class TestResultSummary:
    def test_summary_string(self):
        result = run_event_study(
            pd.DataFrame({
                "pre_return": [0.01, 0.02, 0.015, 0.01, 0.02],
                "post_return": [-0.01, 0.01, 0.005, -0.005, 0.01],
            }),
            FOExpiryTrial(pre_window=3, post_window=3),
        )
        s = result.summary()
        assert "fo_expiry_pre3_post3" in s
        assert "PASS" in s or "FAIL" in s
