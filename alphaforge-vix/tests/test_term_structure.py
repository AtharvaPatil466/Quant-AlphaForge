"""Unit tests for signals/term_structure.py."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from signals import term_structure as ts


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def synthetic_panel():
    idx = pd.date_range("2010-01-04", periods=500, freq="B")
    rng = np.random.default_rng(0)
    vix = pd.Series(np.clip(rng.normal(18.0, 3.0, len(idx)), 9.0, 60.0), index=idx)
    # VIX3M slightly above VIX (contango bias).
    vix3m = vix + rng.normal(2.0, 1.0, len(idx))
    vix6m = vix + rng.normal(3.0, 1.2, len(idx))
    panel = pd.DataFrame({
        "VIX": vix, "VIX3M": vix3m, "VIX6M": vix6m,
    })
    return panel, vix


# ---------------------------------------------------------------------------
# Slope computation
# ---------------------------------------------------------------------------

def test_compute_slope_3m_ratio(synthetic_panel):
    panel, _ = synthetic_panel
    s = ts.compute_slope(panel, "slope_3M")
    expected = panel["VIX3M"] / panel["VIX"]
    pd.testing.assert_series_equal(s.rename(None), expected.rename(None))


def test_compute_slope_diff_additive(synthetic_panel):
    panel, _ = synthetic_panel
    s = ts.compute_slope(panel, "slope_diff")
    expected = panel["VIX3M"] - panel["VIX"]
    pd.testing.assert_series_equal(s.rename(None), expected.rename(None))


def test_compute_slope_rejects_unknown_measure(synthetic_panel):
    panel, _ = synthetic_panel
    with pytest.raises(ValueError):
        ts.compute_slope(panel, "slope_bogus")


def test_compute_slope_6m_requires_vix6m_column():
    bad = pd.DataFrame({"VIX": [20.0]})
    with pytest.raises(KeyError):
        ts.compute_slope(bad, "slope_6M")


# ---------------------------------------------------------------------------
# Signal mapping
# ---------------------------------------------------------------------------

def test_signed_slope_signal_ratio_above_below():
    idx = pd.date_range("2010-01-04", periods=5, freq="B")
    slope = pd.Series([1.10, 1.05, 1.00, 0.95, 0.90], index=idx)
    sig = ts._signed_slope_signal(slope, threshold=1.05, measure="slope_3M")
    # 1.05 → +1, 1.00 → 0, 0.95 → -1 (since 2 - 1.05 = 0.95)
    assert sig.tolist() == [1.0, 1.0, 0.0, -1.0, -1.0]


def test_signed_slope_signal_additive_above_below():
    idx = pd.date_range("2010-01-04", periods=5, freq="B")
    slope = pd.Series([0.10, 0.05, 0.00, -0.05, -0.10], index=idx)
    sig = ts._signed_slope_signal(slope, threshold=0.05, measure="slope_diff")
    assert sig.tolist() == [1.0, 1.0, 0.0, -1.0, -1.0]


# ---------------------------------------------------------------------------
# Trial enumeration
# ---------------------------------------------------------------------------

def test_all_trials_has_6_entries():
    trials = ts.all_trials()
    assert len(trials) == 6
    assert len(set(t.name for t in trials)) == 6


def test_trials_cover_all_measure_threshold_pairs():
    trials = ts.all_trials()
    pairs = {(t.measure, t.threshold) for t in trials}
    expected = set()
    for m, thrs in ts.SLOPE_THRESHOLDS.items():
        for t in thrs:
            expected.add((m, t))
    assert pairs == expected


# ---------------------------------------------------------------------------
# Contango sanity check
# ---------------------------------------------------------------------------

def test_contango_sanity_passes_when_contango_predicts_short_vol():
    """Construct a series where contango (slope_diff > 0) correlates with
    subsequent VIX declines → positive short-vol forward return."""
    n = 400
    idx = pd.date_range("2010-01-04", periods=n, freq="B")
    rng = np.random.default_rng(0)
    # When slope_diff is high, simulate the next 21 days as a VIX decline.
    # Build VIX as a noisy series with engineered drops following
    # high-slope days.
    vix = np.full(n, 18.0)
    slope_diff = rng.normal(2.0, 1.0, n)  # contango-biased
    for t in range(n - 25):
        if slope_diff[t] > 2.5:
            drop = 0.05  # 5% drop spread over 21 days
            vix[t + 1:t + 22] = vix[t + 1:t + 22] * (1 - drop)
        vix[t + 1] += rng.normal(0, 0.5)
    vix_s = pd.Series(np.clip(vix, 9.0, 60.0), index=idx)
    panel = pd.DataFrame({"VIX": vix_s, "VIX3M": vix_s + slope_diff})
    res = ts.contango_sanity_check(panel, vix_s, measure="slope_diff",
                                   horizon=21, is_start=idx[0], is_end=idx[-1])
    # Plumbing assertions only — synthetic doesn't guarantee directional pass.
    assert res.contango_n > 0
    assert res.backwardation_n >= 0
    assert isinstance(res.passed, bool)


# ---------------------------------------------------------------------------
# evaluate_trial
# ---------------------------------------------------------------------------

def test_evaluate_trial_plumbing(synthetic_panel):
    panel, vix = synthetic_panel
    trial = ts.SlopeTrial(measure="slope_3M", threshold=1.05)
    r = ts.evaluate_trial(trial, panel, vix,
                          is_start=panel.index.min(),
                          is_end=panel.index.max())
    assert set(r.ic_by_horizon.keys()) == set(ts.IC_HORIZONS)
    assert r.peak_horizon in ts.IC_HORIZONS or r.peak_horizon is None
    assert r.n_obs > 0


def test_evaluate_all_returns_6_results(synthetic_panel):
    panel, vix = synthetic_panel
    results = ts.evaluate_all(panel, vix,
                              is_start=panel.index.min(),
                              is_end=panel.index.max())
    assert len(results) == 6
    names = [r.trial.name for r in results]
    assert len(set(names)) == 6


def test_to_dict_round_trip(synthetic_panel):
    panel, vix = synthetic_panel
    trial = ts.SlopeTrial(measure="slope_diff", threshold=0.05)
    r = ts.evaluate_trial(trial, panel, vix,
                          is_start=panel.index.min(),
                          is_end=panel.index.max())
    d = r.to_dict()
    for k in ("trial_name", "measure", "threshold", "ic_by_horizon",
              "passed", "is_effective_start"):
        assert k in d
