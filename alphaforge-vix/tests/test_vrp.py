"""Unit tests for signals/vrp.py."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from signals import vrp


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def synthetic_vix_spy():
    """Deterministic synthetic VIX + SPY series with known structure.

    VIX is a slow mean-reverting series around 20 with one big spike.
    SPY is a GBM. We don't expect IC to be huge — these tests check
    plumbing, not signal quality.
    """
    rng = np.random.default_rng(42)
    n = 800
    idx = pd.date_range("2010-01-04", periods=n, freq="B")
    # VIX: AR(1) around 20, with a spike at index ~400.
    vix = np.zeros(n)
    vix[0] = 20.0
    for i in range(1, n):
        vix[i] = 0.95 * vix[i - 1] + 0.05 * 20.0 + rng.normal(0, 1.0)
    vix[400:410] += 25.0  # spike
    vix = np.clip(vix, 9.0, 80.0)
    vix_s = pd.Series(vix, index=idx, name="VIX")

    # SPY: GBM with vol roughly tracking VIX.
    daily_vol = vix / np.sqrt(252) / 100.0
    log_ret = rng.normal(0.0003, 1.0, n) * daily_vol
    spy_close = 100.0 * np.exp(np.cumsum(log_ret))
    spy_s = pd.Series(spy_close, index=idx, name="close")
    return vix_s, spy_s


# ---------------------------------------------------------------------------
# Trial enumeration
# ---------------------------------------------------------------------------

def test_all_trials_has_18_entries():
    trials = vrp.all_trials()
    assert len(trials) == 18
    assert len(set(t.name for t in trials)) == 18


def test_trial_parameters_cover_pre_committed_grid():
    trials = vrp.all_trials()
    lookbacks = sorted({t.lookback for t in trials})
    thresholds = sorted({t.vrp_threshold for t in trials})
    holds = sorted({t.holding_period for t in trials})
    assert lookbacks == [10, 21, 63]
    assert thresholds == [0.0, 2.0, 4.0]
    assert holds == [5, 21]


def test_trial_name_round_trip():
    t = vrp.VrpTrial(lookback=21, vrp_threshold=2.0, holding_period=5)
    assert t.name == "vrp_L21_thr2_hold5"


# ---------------------------------------------------------------------------
# Compute functions
# ---------------------------------------------------------------------------

def test_compute_vrp_basic():
    vix = pd.Series([20.0, 22.0, 25.0], index=pd.date_range("2010-01-04", periods=3, freq="B"))
    rv = pd.Series([15.0, 18.0, 30.0], index=vix.index)
    vrp_s = vrp.compute_vrp(vix, rv)
    assert vrp_s.iloc[0] == 5.0
    assert vrp_s.iloc[1] == 4.0
    assert vrp_s.iloc[2] == -5.0


def test_compute_forward_return_negates_log_change():
    # VIX doubles → log change is +log(2); forward return should be -log(2).
    idx = pd.date_range("2010-01-04", periods=10, freq="B")
    vix = pd.Series([20.0] * 5 + [40.0] * 5, index=idx)
    fr = vrp.compute_forward_return(vix, horizon=5)
    # At t=0, VIX_5 / VIX_0 = 40/20 = 2; fwd_ret = -log(2)
    assert math.isclose(fr.iloc[0], -math.log(2.0), rel_tol=1e-9)
    # Last 5 values must be NaN (no t+h data).
    assert fr.iloc[-5:].isna().all()


def test_compute_forward_return_rejects_zero_horizon():
    vix = pd.Series([20.0, 22.0], index=pd.date_range("2010-01-04", periods=2, freq="B"))
    with pytest.raises(ValueError):
        vrp.compute_forward_return(vix, horizon=0)


def test_ic_pearson_returns_nan_for_short_series():
    s = pd.Series([1.0, 2.0, 3.0])
    r = pd.Series([1.0, 2.0, 3.0])
    assert np.isnan(vrp.ic_pearson(s, r))


def test_ic_pearson_perfect_correlation():
    idx = pd.date_range("2010-01-04", periods=100, freq="B")
    s = pd.Series(np.arange(100, dtype=float), index=idx)
    r = pd.Series(np.arange(100, dtype=float) * 2.0 + 5.0, index=idx)
    assert math.isclose(vrp.ic_pearson(s, r), 1.0, abs_tol=1e-9)


def test_ic_pearson_drops_misaligned_nans():
    idx = pd.date_range("2010-01-04", periods=50, freq="B")
    s = pd.Series(np.arange(50, dtype=float), index=idx)
    r = s.copy()
    r.iloc[:5] = np.nan
    s.iloc[-5:] = np.nan
    # 40 paired non-NaN observations remain. Should give corr=1.0.
    assert math.isclose(vrp.ic_pearson(s, r), 1.0, abs_tol=1e-9)


def test_yearly_ic_buckets_by_year():
    idx = pd.date_range("2010-01-04", "2012-12-30", freq="B")
    s = pd.Series(np.arange(len(idx), dtype=float), index=idx)
    # r = s within each year, but with year-specific offset.
    r = s.copy()
    y_ic = vrp.yearly_ic(s, r)
    # Three years.
    assert sorted(y_ic.index) == [2010, 2011, 2012]
    # Within a year both arrays are strictly increasing → corr = 1.
    for v in y_ic.values:
        assert math.isclose(v, 1.0, abs_tol=1e-9)


# ---------------------------------------------------------------------------
# Signal mapping
# ---------------------------------------------------------------------------

def test_signed_signal_threshold_logic():
    idx = pd.date_range("2010-01-04", periods=7, freq="B")
    vrp_s = pd.Series([5.0, 1.0, 0.0, -1.0, -5.0, 3.0, -3.0], index=idx)
    sig = vrp._signed_signal(vrp_s, threshold=2.0)
    assert sig.tolist() == [1.0, 0.0, 0.0, 0.0, -1.0, 1.0, -1.0]


def test_signed_signal_zero_threshold():
    idx = pd.date_range("2010-01-04", periods=5, freq="B")
    vrp_s = pd.Series([0.5, -0.5, 0.0, 1.0, -1.0], index=idx)
    sig = vrp._signed_signal(vrp_s, threshold=0.0)
    assert sig.tolist() == [1.0, -1.0, 0.0, 1.0, -1.0]


# ---------------------------------------------------------------------------
# evaluate_trial / evaluate_all
# ---------------------------------------------------------------------------

def test_evaluate_trial_plumbing(synthetic_vix_spy):
    from ingest.realized_vol import build_spy_panel
    vix, spy_close = synthetic_vix_spy
    spy_panel = build_spy_panel(spy_close)
    trial = vrp.VrpTrial(lookback=21, vrp_threshold=0.0, holding_period=21)
    result = vrp.evaluate_trial(
        trial, vix, spy_panel,
        is_start=vix.index.min(),
        is_end=vix.index.max(),
    )
    # All horizons reported.
    assert set(result.ic_by_horizon.keys()) == set(vrp.IC_HORIZONS)
    # Peak horizon must be one of the configured horizons.
    assert result.peak_horizon in vrp.IC_HORIZONS
    # Yearly IC keys are years inside the index range.
    years = set(result.yearly_ic_at_peak.keys())
    assert years.issubset({2010, 2011, 2012, 2013})


def test_evaluate_all_returns_18_results(synthetic_vix_spy):
    from ingest.realized_vol import build_spy_panel
    vix, spy_close = synthetic_vix_spy
    spy_panel = build_spy_panel(spy_close)
    results = vrp.evaluate_all(
        vix, spy_panel,
        is_start=vix.index.min(),
        is_end=vix.index.max(),
    )
    assert len(results) == 18
    names = [r.trial.name for r in results]
    assert len(set(names)) == 18


def test_evaluate_trial_raises_on_missing_rv_column():
    idx = pd.date_range("2010-01-04", periods=100, freq="B")
    vix = pd.Series(np.ones(100) * 20.0, index=idx)
    bad_panel = pd.DataFrame({"realized_vol_99": np.ones(100)}, index=idx)
    trial = vrp.VrpTrial(lookback=21, vrp_threshold=0.0, holding_period=21)
    with pytest.raises(KeyError):
        vrp.evaluate_trial(trial, vix, bad_panel,
                           is_start=idx[0], is_end=idx[-1])


def test_evaluate_trial_pass_flag_is_conjunction_of_subflags():
    """The `passed` flag must be the AND of the three sub-criteria.
    Built with a noise-VRP setup so signal varies enough to give real IC."""
    n_years = 11
    days_per_year = 252
    n = n_years * days_per_year
    start = pd.Timestamp("2004-01-02")
    idx = pd.date_range(start, periods=n, freq="B")

    rng = np.random.default_rng(0)
    # VIX bouncing between calm and elevated regimes.
    base = 18.0 + 5.0 * np.sin(np.linspace(0, 30, n))
    noise = rng.normal(0, 2.0, n)
    vix_vals = np.clip(base + noise, 10.0, 60.0)
    vix = pd.Series(vix_vals, index=idx, name="VIX")
    # Realized vol jittered around VIX so VRP straddles zero.
    rv = pd.Series(vix_vals + rng.normal(0, 4.0, n), index=idx)
    spy_panel = pd.DataFrame({"realized_vol_21": rv})

    trial = vrp.VrpTrial(lookback=21, vrp_threshold=0.0, holding_period=21)
    result = vrp.evaluate_trial(
        trial, vix, spy_panel, is_start=start, is_end=idx[-1],
    )
    assert result.n_obs > 100
    # Pass-flag must be the AND of its three sub-criteria.
    assert result.passed == (result.pass_ic_threshold
                              and result.pass_yearly_all
                              and result.pass_yearly_ex_2008_09)


def test_to_dict_round_trip(synthetic_vix_spy):
    from ingest.realized_vol import build_spy_panel
    vix, spy_close = synthetic_vix_spy
    spy_panel = build_spy_panel(spy_close)
    trial = vrp.VrpTrial(lookback=10, vrp_threshold=2.0, holding_period=5)
    r = vrp.evaluate_trial(trial, vix, spy_panel,
                           is_start=vix.index.min(),
                           is_end=vix.index.max())
    d = r.to_dict()
    # All required keys present.
    for k in ("trial_name", "ic_by_horizon", "passed",
              "years_positive_all", "peak_horizon"):
        assert k in d
    # IC keys are strings (JSON-friendly).
    assert all(isinstance(k, str) for k in d["ic_by_horizon"])
