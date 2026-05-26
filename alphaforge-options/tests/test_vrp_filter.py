"""Tests for alphaforge-options/signals/vrp_filter.py.

Uses real on-disk data from alphaforge-vix/data/ where accessible,
but falls back to synthetic DataFrames for CI portability.
Network-touching tests are marked skip.
"""
import numpy as np
import pandas as pd
import pytest

from signals.vrp_filter import (
    VIX_DATA_ROOT,
    build_vrp_panel,
    compute_log_returns,
    compute_realized_vol,
    compute_vrp,
    entry_signal,
    load_spy,
    load_vix,
    monthly_cycle_dates,
)

DATA_AVAILABLE = (VIX_DATA_ROOT / "vix_indices" / "VIX.csv").exists()


# ---------------------------------------------------------------------------
# Helpers — synthetic data
# ---------------------------------------------------------------------------

def _make_synthetic_price_series(n: int = 300, seed: int = 42) -> pd.Series:
    rng = np.random.default_rng(seed)
    log_ret = rng.normal(0.0005, 0.01, size=n)
    prices = 400.0 * np.exp(np.cumsum(log_ret))
    dates = pd.date_range("2010-01-04", periods=n, freq="B")
    return pd.Series(prices, index=dates, name="close")


def _make_synthetic_panel(n: int = 300) -> pd.DataFrame:
    prices = _make_synthetic_price_series(n)
    log_ret = compute_log_returns(prices)
    rv = compute_realized_vol(log_ret)
    rng = np.random.default_rng(0)
    vix = pd.Series(15.0 + rng.normal(0, 3, size=n), index=prices.index, name="vix").clip(lower=5)
    vrp = compute_vrp(vix, rv)
    panel = pd.concat([vix, rv, vrp, prices.rename("spy_close")], axis=1).dropna()
    return panel


# ---------------------------------------------------------------------------
# compute_log_returns
# ---------------------------------------------------------------------------

class TestComputeLogReturns:
    def test_first_value_is_nan(self):
        prices = _make_synthetic_price_series(50)
        lr = compute_log_returns(prices)
        assert pd.isna(lr.iloc[0])

    def test_length_matches_input(self):
        prices = _make_synthetic_price_series(50)
        lr = compute_log_returns(prices)
        assert len(lr) == len(prices)

    def test_approximate_values(self):
        prices = pd.Series([100.0, 110.0, 105.0])
        lr = compute_log_returns(prices)
        assert abs(lr.iloc[1] - np.log(110 / 100)) < 1e-12
        assert abs(lr.iloc[2] - np.log(105 / 110)) < 1e-12


# ---------------------------------------------------------------------------
# compute_realized_vol
# ---------------------------------------------------------------------------

class TestComputeRealizedVol:
    def test_units_in_percent_vix_range(self):
        prices = _make_synthetic_price_series(100)
        lr = compute_log_returns(prices)
        rv = compute_realized_vol(lr, window=21)
        valid = rv.dropna()
        # SPY vol typically 10-40%; our synthetic returns are 1%/day → ~16% annualized
        assert (valid > 5).all() and (valid < 60).all()

    def test_nan_before_window_fills(self):
        prices = _make_synthetic_price_series(100)
        lr = compute_log_returns(prices)
        rv = compute_realized_vol(lr, window=21)
        # First 21 rows (+ 1 for log-return NaN) should be NaN
        assert rv.iloc[:21].isna().all()

    def test_window_respected(self):
        prices = _make_synthetic_price_series(100)
        lr = compute_log_returns(prices)
        rv21 = compute_realized_vol(lr, window=21)
        rv63 = compute_realized_vol(lr, window=63)
        # rv63 has more NaNs at the start
        assert rv21.notna().sum() > rv63.notna().sum()


# ---------------------------------------------------------------------------
# compute_vrp
# ---------------------------------------------------------------------------

class TestComputeVrp:
    def test_vrp_name(self):
        vix = pd.Series([20.0] * 100, name="vix")
        rv = pd.Series([15.0] * 100, name="realized_vol")
        vrp = compute_vrp(vix, rv)
        assert vrp.name == "vrp"

    def test_vrp_formula(self):
        vix = pd.Series([20.0, 18.0, 22.0], name="vix")
        rv = pd.Series([15.0, 16.0, 19.0], name="realized_vol")
        vrp = compute_vrp(vix, rv)
        expected = vix.values - rv.values
        np.testing.assert_allclose(vrp.values, expected)

    def test_positive_when_vix_above_rv(self):
        vix = pd.Series([20.0], name="vix")
        rv = pd.Series([15.0], name="realized_vol")
        assert compute_vrp(vix, rv).iloc[0] > 0

    def test_negative_when_rv_above_vix(self):
        vix = pd.Series([15.0], name="vix")
        rv = pd.Series([20.0], name="realized_vol")
        assert compute_vrp(vix, rv).iloc[0] < 0


# ---------------------------------------------------------------------------
# entry_signal
# ---------------------------------------------------------------------------

class TestEntrySignal:
    def test_true_when_above_threshold(self):
        vrp = pd.Series([0.5, 2.0, 3.0])
        sig = entry_signal(vrp, threshold=0.0)
        assert sig.tolist() == [True, True, True]

    def test_false_when_below_threshold(self):
        vrp = pd.Series([-1.0, -0.5])
        sig = entry_signal(vrp, threshold=0.0)
        assert sig.tolist() == [False, False]

    def test_at_threshold_is_false(self):
        vrp = pd.Series([0.0])
        sig = entry_signal(vrp, threshold=0.0)
        assert not sig.iloc[0]


# ---------------------------------------------------------------------------
# monthly_cycle_dates (synthetic panel)
# ---------------------------------------------------------------------------

class TestMonthlyCycleDates:
    def setup_method(self):
        self.panel = _make_synthetic_panel(300)

    def test_returns_list_of_dicts(self):
        cycles = monthly_cycle_dates(self.panel, "2010-01-04", "2010-12-31")
        assert isinstance(cycles, list)
        if cycles:
            assert isinstance(cycles[0], dict)

    def test_required_keys(self):
        cycles = monthly_cycle_dates(self.panel, "2010-01-04", "2010-12-31")
        for cyc in cycles:
            for k in ("entry_date", "expiry_date", "roll_date", "T_entry", "T_roll"):
                assert k in cyc, f"Missing key: {k}"

    def test_one_cycle_per_month_approximately(self):
        cycles = monthly_cycle_dates(self.panel, "2010-01-04", "2010-12-31")
        # 12 months; some may be excluded if roll falls outside panel
        assert 8 <= len(cycles) <= 12

    def test_roll_date_before_expiry(self):
        cycles = monthly_cycle_dates(self.panel, "2010-01-04", "2010-12-31")
        for cyc in cycles:
            assert cyc["roll_date"] <= cyc["expiry_date"]

    def test_roll_date_after_or_equal_entry(self):
        cycles = monthly_cycle_dates(self.panel, "2010-01-04", "2010-12-31")
        for cyc in cycles:
            assert cyc["roll_date"] >= cyc["entry_date"]

    def test_T_entry_approx_30_over_365(self):
        cycles = monthly_cycle_dates(self.panel, "2010-01-04", "2010-12-31")
        for cyc in cycles:
            assert abs(cyc["T_entry"] - 30 / 365.0) < 1e-12

    def test_T_roll_positive(self):
        cycles = monthly_cycle_dates(self.panel, "2010-01-04", "2010-12-31")
        for cyc in cycles:
            assert cyc["T_roll"] > 0

    def test_both_dates_in_panel(self):
        cycles = monthly_cycle_dates(self.panel, "2010-01-04", "2010-12-31")
        for cyc in cycles:
            assert cyc["entry_date"] in self.panel.index
            assert cyc["roll_date"] in self.panel.index

    def test_empty_range_returns_empty_list(self):
        # start after end
        cycles = monthly_cycle_dates(self.panel, "2020-01-01", "2019-01-01")
        assert cycles == []


# ---------------------------------------------------------------------------
# build_vrp_panel and load_* (real-data tests, skipped if data absent)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not DATA_AVAILABLE, reason="alphaforge-vix data not on disk")
class TestRealData:
    def test_load_vix_returns_series(self):
        vix = load_vix()
        assert isinstance(vix, pd.Series)
        assert len(vix) > 1000

    def test_load_spy_returns_df(self):
        spy = load_spy()
        assert "close" in spy.columns and "adj_close" in spy.columns
        assert len(spy) > 1000

    def test_build_vrp_panel_columns(self):
        panel = build_vrp_panel()
        for col in ("vix", "realized_vol", "vrp", "spy_close"):
            assert col in panel.columns, f"Missing column: {col}"

    def test_build_vrp_panel_no_nans(self):
        panel = build_vrp_panel()
        assert not panel.isnull().any().any()

    def test_panel_covers_is_window(self):
        panel = build_vrp_panel()
        assert panel.index[0] <= pd.Timestamp("2004-06-01")
        assert panel.index[-1] >= pd.Timestamp("2014-12-31")

    def test_vrp_predominantly_positive(self):
        # Historical stylized fact: VRP > 0 roughly 70-75% of trading days
        panel = build_vrp_panel()
        frac_positive = (panel["vrp"] > 0).mean()
        assert frac_positive > 0.55
