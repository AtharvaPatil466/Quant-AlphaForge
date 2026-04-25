"""Tests for data validator."""

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from data.validator import DataValidationError, validate_history


def _make_df(n_days=60, start="2024-01-01", nan_close=False, zero_vol_pct=0.0):
    """Create a valid DataFrame for testing."""
    dates = pd.date_range(start, periods=n_days)
    closes = 100 + np.random.randn(n_days).cumsum()
    volumes = np.random.randint(100_000, 1_000_000, n_days).astype(float)
    if nan_close:
        closes[5] = np.nan
    if zero_vol_pct > 0:
        n_zero = int(n_days * zero_vol_pct)
        volumes[:n_zero] = 0
    return pd.DataFrame({"Close": closes, "Volume": volumes}, index=dates)


class TestValidateHistory:
    def test_valid_data_passes(self):
        history = {"AAPL": _make_df(), "MSFT": _make_df()}
        validate_history(history, ["AAPL", "MSFT"], min_days=30, check_staleness=False)

    def test_missing_ticker(self):
        history = {"AAPL": _make_df()}
        with pytest.raises(DataValidationError, match="Missing tickers"):
            validate_history(history, ["AAPL", "MSFT"], check_staleness=False)

    def test_insufficient_history(self):
        history = {"AAPL": _make_df(n_days=10)}
        with pytest.raises(DataValidationError, match="only 10 days"):
            validate_history(history, ["AAPL"], min_days=30, check_staleness=False)

    def test_nan_in_close(self):
        history = {"AAPL": _make_df(nan_close=True)}
        with pytest.raises(DataValidationError, match="NaN"):
            validate_history(history, ["AAPL"], check_staleness=False)

    def test_excessive_zero_volume(self):
        history = {"AAPL": _make_df(zero_vol_pct=0.20)}
        with pytest.raises(DataValidationError, match="zero-volume"):
            validate_history(history, ["AAPL"], check_staleness=False)

    def test_acceptable_zero_volume(self):
        history = {"AAPL": _make_df(zero_vol_pct=0.05)}
        validate_history(history, ["AAPL"], min_days=30, check_staleness=False)

    def test_staleness_check(self):
        old_start = (date.today() - timedelta(days=100)).isoformat()
        history = {"AAPL": _make_df(n_days=30, start=old_start)}
        with pytest.raises(DataValidationError, match="stale"):
            validate_history(history, ["AAPL"], min_days=10, check_staleness=True)

    def test_staleness_disabled(self):
        old_start = (date.today() - timedelta(days=100)).isoformat()
        history = {"AAPL": _make_df(n_days=30, start=old_start)}
        validate_history(history, ["AAPL"], min_days=10, check_staleness=False)

    def test_extra_tickers_ignored(self):
        history = {"AAPL": _make_df(), "MSFT": _make_df(), "EXTRA": _make_df(n_days=5)}
        validate_history(history, ["AAPL", "MSFT"], min_days=30, check_staleness=False)
