"""Tests for signals.delivery_pct — INDIA_DESIGN.md §4.1 trial grid.

Covers:
- enumerate_trials: exactly 18 trials, unique names, correct params.
- compute_signal: z-scored, mean ≈ 0 cross-sectionally, NaN handling.
- compute_forward_returns: correct math, trailing NaNs.
- compute_ic_series: values in [-1, 1], correct length.
- assign_buckets: long/short/neutral assignment, correct counts.
- Edge cases: single stock, all-NaN, zero close.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from signals.delivery_pct import (
    DeliveryPctSignal,
    compute_forward_returns,
    enumerate_trials,
    LOOKBACKS,
    BUCKETS,
    HOLDING_PERIODS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def synthetic_panel() -> tuple[pd.DataFrame, pd.DataFrame]:
    """A reproducible 60-day × 20-stock panel for signal + return testing.

    Returns (close_df, deliv_pct_df).
    """
    rng = np.random.default_rng(42)
    n_days, n_stocks = 60, 20
    dates = pd.bdate_range("2023-01-02", periods=n_days, freq="B")
    symbols = [f"STOCK_{i:02d}" for i in range(n_stocks)]

    # Synthetic close prices: geometric random walk
    log_returns = rng.normal(0.0003, 0.02, (n_days, n_stocks))
    close = 100.0 * np.exp(np.cumsum(log_returns, axis=0))
    close_df = pd.DataFrame(close, index=dates, columns=symbols)

    # Synthetic delivery pct: 40-80 range with stock-level persistence
    base_deliv = rng.uniform(40.0, 80.0, (1, n_stocks))
    noise = rng.normal(0.0, 5.0, (n_days, n_stocks))
    deliv_pct = np.clip(base_deliv + noise, 0.0, 100.0)
    deliv_pct_df = pd.DataFrame(deliv_pct, index=dates, columns=symbols)

    return close_df, deliv_pct_df


@pytest.fixture
def small_panel() -> tuple[pd.DataFrame, pd.DataFrame]:
    """5-day × 5-stock micro panel for exact math verification."""
    dates = pd.bdate_range("2024-01-01", periods=10, freq="B")
    symbols = ["A", "B", "C", "D", "E"]

    close_data = np.array([
        [100, 200, 300, 400, 500],
        [101, 199, 301, 399, 501],
        [102, 198, 302, 398, 502],
        [103, 197, 303, 397, 503],
        [104, 196, 304, 396, 504],
        [105, 195, 305, 395, 505],
        [106, 194, 306, 394, 506],
        [107, 193, 307, 393, 507],
        [108, 192, 308, 392, 508],
        [109, 191, 309, 391, 509],
    ], dtype=float)
    close_df = pd.DataFrame(close_data, index=dates, columns=symbols)

    deliv_data = np.array([
        [70, 30, 50, 60, 40],
        [72, 28, 52, 58, 42],
        [68, 32, 48, 62, 38],
        [75, 25, 55, 55, 45],
        [71, 31, 49, 61, 39],
        [73, 29, 51, 59, 41],
        [69, 33, 47, 63, 37],
        [74, 26, 54, 56, 44],
        [70, 30, 50, 60, 40],
        [72, 28, 52, 58, 42],
    ], dtype=float)
    deliv_pct_df = pd.DataFrame(deliv_data, index=dates, columns=symbols)

    return close_df, deliv_pct_df


# ---------------------------------------------------------------------------
# enumerate_trials
# ---------------------------------------------------------------------------

class TestEnumerateTrials:
    def test_count(self) -> None:
        trials = enumerate_trials()
        assert len(trials) == 18, f"Expected 18 trials, got {len(trials)}"

    def test_unique_names(self) -> None:
        trials = enumerate_trials()
        names = [t.trial_name for t in trials]
        assert len(set(names)) == 18, "Trial names must be unique"

    def test_all_lookbacks_present(self) -> None:
        trials = enumerate_trials()
        lbs = {t.lookback for t in trials}
        assert lbs == set(LOOKBACKS)

    def test_all_buckets_present(self) -> None:
        trials = enumerate_trials()
        bks = {t.bucket for t in trials}
        assert bks == set(BUCKETS)

    def test_all_holding_periods_present(self) -> None:
        trials = enumerate_trials()
        hps = {t.holding_period for t in trials}
        assert hps == set(HOLDING_PERIODS)

    def test_trial_grid_complete(self) -> None:
        """Every (lookback, bucket, hp) combination appears exactly once."""
        trials = enumerate_trials()
        combos = {(t.lookback, t.bucket, t.holding_period) for t in trials}
        expected = {
            (lb, bk, hp)
            for lb in LOOKBACKS
            for bk in BUCKETS
            for hp in HOLDING_PERIODS
        }
        assert combos == expected

    def test_trial_name_format(self) -> None:
        sig = DeliveryPctSignal(10, "quintile", 5)
        assert sig.trial_name == "deliv_pct_L10_Q5_H5"

        sig2 = DeliveryPctSignal(60, "decile", 21)
        assert sig2.trial_name == "deliv_pct_L60_Q10_H21"


# ---------------------------------------------------------------------------
# compute_forward_returns
# ---------------------------------------------------------------------------

class TestComputeForwardReturns:
    def test_shape_preserved(self, synthetic_panel: tuple) -> None:
        close_df, _ = synthetic_panel
        fwd = compute_forward_returns(close_df, 5)
        assert fwd.shape == close_df.shape

    def test_trailing_nans(self, small_panel: tuple) -> None:
        close_df, _ = small_panel
        fwd = compute_forward_returns(close_df, 3)
        # Last 3 rows should be all NaN
        assert fwd.iloc[-3:].isna().all().all()
        # First rows should NOT be NaN (all close > 0)
        assert fwd.iloc[0].notna().all()

    def test_correct_values(self, small_panel: tuple) -> None:
        close_df, _ = small_panel
        fwd = compute_forward_returns(close_df, 1)
        # For stock A: row 0 → (101/100 - 1) = 0.01
        expected_a_0 = (close_df.iloc[1]["A"] / close_df.iloc[0]["A"]) - 1.0
        actual = fwd.iloc[0]["A"]
        assert abs(actual - expected_a_0) < 1e-12

    def test_multi_day_return(self, small_panel: tuple) -> None:
        close_df, _ = small_panel
        fwd = compute_forward_returns(close_df, 5)
        # For stock A: row 0 → (105/100 - 1) = 0.05
        expected = (close_df.iloc[5]["A"] / close_df.iloc[0]["A"]) - 1.0
        actual = fwd.iloc[0]["A"]
        assert abs(actual - expected) < 1e-12

    def test_zero_close_produces_nan(self) -> None:
        """A stock with close=0 should produce NaN, not inf."""
        dates = pd.bdate_range("2024-01-01", periods=5, freq="B")
        close_df = pd.DataFrame(
            {"X": [100, 0, 102, 103, 104]},
            index=dates,
        )
        fwd = compute_forward_returns(close_df, 1)
        assert np.isnan(fwd.loc[dates[1], "X"])

    def test_invalid_holding_period(self) -> None:
        dates = pd.bdate_range("2024-01-01", periods=5, freq="B")
        close_df = pd.DataFrame({"X": [100, 101, 102, 103, 104]}, index=dates)
        with pytest.raises(ValueError, match="holding_period must be ≥ 1"):
            compute_forward_returns(close_df, 0)


# ---------------------------------------------------------------------------
# compute_signal
# ---------------------------------------------------------------------------

class TestComputeSignal:
    def test_output_shape(self, synthetic_panel: tuple) -> None:
        close_df, deliv_pct_df = synthetic_panel
        sig = DeliveryPctSignal(10, "quintile", 5)
        signal_df = sig.compute_signal(close_df, deliv_pct_df)
        assert signal_df.shape == close_df.shape

    def test_cross_sectional_mean_near_zero(self, synthetic_panel: tuple) -> None:
        """Z-scored signal should have cross-sectional mean ≈ 0."""
        close_df, deliv_pct_df = synthetic_panel
        sig = DeliveryPctSignal(10, "quintile", 5)
        signal_df = sig.compute_signal(close_df, deliv_pct_df)
        # Check rows after the lookback warm-up where z-score is defined
        valid_rows = signal_df.dropna(how="all")
        cs_means = valid_rows.mean(axis=1).dropna()
        assert (cs_means.abs() < 1e-10).all(), (
            f"Cross-sectional means should be ≈ 0, got max abs "
            f"{cs_means.abs().max():.2e}"
        )

    def test_cross_sectional_std_near_one(self, synthetic_panel: tuple) -> None:
        """Z-scored signal should have cross-sectional std ≈ 1."""
        close_df, deliv_pct_df = synthetic_panel
        sig = DeliveryPctSignal(10, "quintile", 5)
        signal_df = sig.compute_signal(close_df, deliv_pct_df)
        valid_rows = signal_df.dropna(how="all")
        cs_stds = valid_rows.std(axis=1).dropna()
        # Allow small floating-point tolerance
        assert ((cs_stds - 1.0).abs() < 0.05).all(), (
            f"Cross-sectional stds should be ≈ 1, got range "
            f"[{cs_stds.min():.4f}, {cs_stds.max():.4f}]"
        )

    def test_early_rows_nan_for_long_lookback(
        self, synthetic_panel: tuple
    ) -> None:
        """With lookback=60, no valid signal until day 30 (min_periods)."""
        close_df, deliv_pct_df = synthetic_panel
        sig = DeliveryPctSignal(60, "quintile", 5)
        signal_df = sig.compute_signal(close_df, deliv_pct_df)
        # First 29 rows should be mostly NaN (min_periods = 30)
        assert signal_df.iloc[:29].isna().all().all()

    def test_nan_close_masks_signal(self, small_panel: tuple) -> None:
        """If a stock has NaN close on a day, signal should be NaN."""
        close_df, deliv_pct_df = small_panel
        close_df = close_df.copy()
        close_df.iloc[5, 0] = np.nan  # STOCK_A day 5
        sig = DeliveryPctSignal(3, "quintile", 5)
        signal_df = sig.compute_signal(close_df, deliv_pct_df)
        assert np.isnan(signal_df.iloc[5, 0])


# ---------------------------------------------------------------------------
# compute_ic_series
# ---------------------------------------------------------------------------

class TestComputeICSeries:
    def test_values_in_range(self, synthetic_panel: tuple) -> None:
        close_df, deliv_pct_df = synthetic_panel
        sig = DeliveryPctSignal(10, "quintile", 5)
        signal_df = sig.compute_signal(close_df, deliv_pct_df)
        fwd_ret = compute_forward_returns(close_df, 5)
        ic = sig.compute_ic_series(signal_df, fwd_ret)
        assert (ic >= -1.0).all() and (ic <= 1.0).all(), (
            f"IC values out of [-1, 1]: min={ic.min()}, max={ic.max()}"
        )

    def test_ic_series_not_empty(self, synthetic_panel: tuple) -> None:
        close_df, deliv_pct_df = synthetic_panel
        sig = DeliveryPctSignal(10, "quintile", 5)
        signal_df = sig.compute_signal(close_df, deliv_pct_df)
        fwd_ret = compute_forward_returns(close_df, 5)
        ic = sig.compute_ic_series(signal_df, fwd_ret)
        assert len(ic) > 0, "IC series should have at least one observation"

    def test_ic_name_matches_trial(self, synthetic_panel: tuple) -> None:
        close_df, deliv_pct_df = synthetic_panel
        sig = DeliveryPctSignal(20, "decile", 10)
        signal_df = sig.compute_signal(close_df, deliv_pct_df)
        fwd_ret = compute_forward_returns(close_df, 10)
        ic = sig.compute_ic_series(signal_df, fwd_ret)
        assert ic.name == "deliv_pct_L20_Q10_H10"

    def test_rebalance_step(self, synthetic_panel: tuple) -> None:
        """IC series dates should step by holding_period rows."""
        close_df, deliv_pct_df = synthetic_panel
        hp = 5
        sig = DeliveryPctSignal(10, "quintile", hp)
        signal_df = sig.compute_signal(close_df, deliv_pct_df)
        fwd_ret = compute_forward_returns(close_df, hp)
        ic = sig.compute_ic_series(signal_df, fwd_ret)
        if len(ic) >= 2:
            # Check that IC dates are every hp-th date from signal
            common = signal_df.index.intersection(fwd_ret.index)
            expected_dates = common[::hp]
            # All IC dates should be in expected rebalance dates
            for dt in ic.index:
                assert dt in expected_dates

    def test_perfect_positive_correlation(self) -> None:
        """If signal == forward return (rank-wise), IC should be 1.0."""
        dates = pd.bdate_range("2024-01-01", periods=10, freq="B")
        symbols = [f"S{i}" for i in range(10)]
        # Signal: linear spread across stocks
        signal_vals = np.tile(np.arange(10, dtype=float), (10, 1))
        signal_df = pd.DataFrame(signal_vals, index=dates, columns=symbols)
        # Forward returns: same rank order (perfectly correlated)
        returns_df = signal_df * 0.01 + 0.001  # monotone transform preserves rank
        sig = DeliveryPctSignal(5, "quintile", 1)
        ic = sig.compute_ic_series(signal_df, returns_df)
        assert len(ic) > 0
        assert all(abs(v - 1.0) < 1e-10 for v in ic.values)


# ---------------------------------------------------------------------------
# assign_buckets
# ---------------------------------------------------------------------------

class TestAssignBuckets:
    def test_quintile_counts(self, synthetic_panel: tuple) -> None:
        """Quintile bucket: top 20% long, bottom 20% short."""
        close_df, deliv_pct_df = synthetic_panel
        sig = DeliveryPctSignal(10, "quintile", 5)
        signal_df = sig.compute_signal(close_df, deliv_pct_df)
        buckets = sig.assign_buckets(signal_df)
        # Check a valid row (after lookback warm-up)
        valid_row = buckets.iloc[15]
        n_stocks = valid_row.notna().sum()
        if n_stocks > 0:
            n_long = (valid_row == 1.0).sum()
            n_short = (valid_row == -1.0).sum()
            expected_per_bucket = max(1, int(np.floor(n_stocks * 0.20)))
            assert n_long == expected_per_bucket
            assert n_short == expected_per_bucket

    def test_decile_counts(self, synthetic_panel: tuple) -> None:
        """Decile bucket: top 10% long, bottom 10% short."""
        close_df, deliv_pct_df = synthetic_panel
        sig = DeliveryPctSignal(10, "decile", 5)
        signal_df = sig.compute_signal(close_df, deliv_pct_df)
        buckets = sig.assign_buckets(signal_df)
        valid_row = buckets.iloc[15]
        n_stocks = valid_row.notna().sum()
        if n_stocks > 0:
            n_long = (valid_row == 1.0).sum()
            n_short = (valid_row == -1.0).sum()
            expected_per_bucket = max(1, int(np.floor(n_stocks * 0.10)))
            assert n_long == expected_per_bucket
            assert n_short == expected_per_bucket

    def test_bucket_values(self, synthetic_panel: tuple) -> None:
        """All bucket values should be in {-1, 0, 1, NaN}."""
        close_df, deliv_pct_df = synthetic_panel
        sig = DeliveryPctSignal(10, "quintile", 5)
        signal_df = sig.compute_signal(close_df, deliv_pct_df)
        buckets = sig.assign_buckets(signal_df)
        valid = buckets.values[~np.isnan(buckets.values)]
        unique_vals = set(valid)
        assert unique_vals <= {-1.0, 0.0, 1.0}, f"Unexpected values: {unique_vals}"


# ---------------------------------------------------------------------------
# Edge cases & validation
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_invalid_lookback(self) -> None:
        with pytest.raises(ValueError, match="lookback must be ≥ 1"):
            DeliveryPctSignal(0, "quintile", 5)

    def test_invalid_bucket(self) -> None:
        with pytest.raises(ValueError, match="bucket must be one of"):
            DeliveryPctSignal(10, "tertile", 5)

    def test_invalid_holding_period(self) -> None:
        with pytest.raises(ValueError, match="holding_period must be ≥ 1"):
            DeliveryPctSignal(10, "quintile", 0)

    def test_single_stock_signal(self) -> None:
        """Signal on a single stock should be all NaN (no cross-section)."""
        dates = pd.bdate_range("2024-01-01", periods=15, freq="B")
        close_df = pd.DataFrame({"X": np.arange(100, 115, dtype=float)}, index=dates)
        deliv_df = pd.DataFrame({"X": np.full(15, 60.0)}, index=dates)
        sig = DeliveryPctSignal(5, "quintile", 5)
        signal_df = sig.compute_signal(close_df, deliv_df)
        # With one stock, std = NaN → z-score = NaN
        assert signal_df.isna().all().all()

    def test_all_nan_delivery(self) -> None:
        """If delivery pct is all NaN, signal should be all NaN."""
        dates = pd.bdate_range("2024-01-01", periods=15, freq="B")
        symbols = ["A", "B", "C"]
        close_df = pd.DataFrame(
            np.full((15, 3), 100.0), index=dates, columns=symbols,
        )
        deliv_df = pd.DataFrame(
            np.full((15, 3), np.nan), index=dates, columns=symbols,
        )
        sig = DeliveryPctSignal(5, "quintile", 5)
        signal_df = sig.compute_signal(close_df, deliv_df)
        assert signal_df.isna().all().all()
