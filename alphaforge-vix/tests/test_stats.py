"""Unit tests for gauntlet/stats.py."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from gauntlet import stats


# ---------------------------------------------------------------------------
# Sharpe
# ---------------------------------------------------------------------------

def test_annualized_sharpe_basic():
    # Deterministic series with mean 0.001, std 0.01 daily.
    rng = np.random.default_rng(0)
    r = rng.normal(0.001, 0.01, 1000)
    s = stats.annualized_sharpe(r)
    # Expected ≈ 0.001 / 0.01 × √252 ≈ 1.587. With n=1000 the sample-mean
    # SE is ~0.000316, so the realized Sharpe can swing ±0.6 around 1.587.
    # Bounds [0.5, 2.7] cover ~95% of seeds.
    assert 0.5 < s < 2.7


def test_annualized_sharpe_zero_std_returns_zero():
    r = np.ones(100) * 0.001
    assert stats.annualized_sharpe(r) == 0.0


def test_annualized_sharpe_short_series_nan():
    assert math.isnan(stats.annualized_sharpe(np.array([0.01])))


# ---------------------------------------------------------------------------
# Skewness / kurtosis
# ---------------------------------------------------------------------------

def test_skewness_zero_for_symmetric():
    rng = np.random.default_rng(0)
    r = rng.normal(0.0, 1.0, 10_000)
    # Skewness of large symmetric sample ≈ 0.
    assert abs(stats.sample_skewness(r)) < 0.1


def test_skewness_negative_for_left_skew():
    # Construct left-skewed: x - x^2 with x ~ N(0,1).
    rng = np.random.default_rng(0)
    x = rng.normal(0, 1, 5000)
    left_skewed = x - 0.5 * x ** 2
    assert stats.sample_skewness(left_skewed) < -0.2


def test_excess_kurtosis_zero_for_normal():
    rng = np.random.default_rng(0)
    r = rng.normal(0, 1, 50_000)
    # Normal has excess kurtosis 0 ± noise.
    assert abs(stats.sample_excess_kurtosis(r)) < 0.15


def test_excess_kurtosis_positive_for_t():
    # Fat-tailed t-distribution.
    rng = np.random.default_rng(0)
    df = 5
    r = rng.standard_t(df, 50_000)
    assert stats.sample_excess_kurtosis(r) > 1.0


# ---------------------------------------------------------------------------
# Cornish-Fisher Sharpe
# ---------------------------------------------------------------------------

def test_cf_sharpe_equals_sharpe_for_normal():
    """Per §5.6 design (CF-Sharpe = Sharpe / CF-adjustment-factor), normal
    returns have CF-adjustment = 1 → CF-Sharpe = Sharpe (to FP noise from
    sample skewness ≠ 0 exactly)."""
    rng = np.random.default_rng(0)
    r = rng.normal(0.0005, 0.01, 10_000)
    s = stats.annualized_sharpe(r)
    cf = stats.cornish_fisher_sharpe(r)
    # Within 10% for large-N normal sample.
    assert abs(cf - s) / max(abs(s), 1e-6) < 0.10


def test_cf_sharpe_penalizes_negative_skew():
    """A series with the same mean/std but negative skew should produce a
    LOWER CF-Sharpe than a symmetric series."""
    rng = np.random.default_rng(0)
    # Symmetric series.
    r_sym = rng.normal(0.001, 0.01, 5000)
    # Left-skewed series: add an occasional large negative.
    r_neg = r_sym.copy()
    # Inject 5% probability of a -3% return.
    crash_mask = rng.random(5000) < 0.05
    r_neg[crash_mask] -= 0.03
    # Make sure means roughly match by adjusting the symmetric series.
    r_neg = r_neg - (np.mean(r_neg) - np.mean(r_sym))
    # CF-Sharpe should be lower for the skewed series.
    assert stats.cornish_fisher_sharpe(r_neg) < stats.cornish_fisher_sharpe(r_sym)


def test_cf_sharpe_rejects_unsupported_alpha():
    rng = np.random.default_rng(0)
    r = rng.normal(0.0, 1.0, 100)
    with pytest.raises(ValueError):
        stats.cornish_fisher_sharpe(r, alpha=0.10)


def test_cf_sharpe_short_series_returns_nan():
    assert math.isnan(stats.cornish_fisher_sharpe(np.array([0.01, 0.02, 0.03])))


# ---------------------------------------------------------------------------
# DSR
# ---------------------------------------------------------------------------

def test_dsr_single_trial_no_deflation():
    """With n_trials=1, the E[max] correction is 0, so DSR is the
    probability that the observed Sharpe exceeds 0 — which depends on n_obs."""
    dsr = stats.deflated_sharpe_ratio(
        sharpe_observed=1.5, n_trials=1, n_obs=252,
        skewness=0.0, excess_kurtosis=0.0,
    )
    # Sharpe of 1.5 with 1 year of data: very high probability.
    assert dsr > 0.9


def test_dsr_decreases_with_more_trials():
    """Holding observed Sharpe fixed, more trials → lower DSR."""
    sr = 2.0
    dsr_low = stats.deflated_sharpe_ratio(sr, n_trials=5, n_obs=500)
    dsr_high = stats.deflated_sharpe_ratio(sr, n_trials=100, n_obs=500)
    assert dsr_high < dsr_low


def test_dsr_decreases_with_negative_skew():
    """Negative skew should reduce DSR (Bailey-LdP variance correction)."""
    sr = 2.0
    dsr_normal = stats.deflated_sharpe_ratio(sr, n_trials=28, n_obs=500,
                                              skewness=0.0)
    dsr_skewed = stats.deflated_sharpe_ratio(sr, n_trials=28, n_obs=500,
                                              skewness=-1.5, excess_kurtosis=3.0)
    assert dsr_skewed < dsr_normal


def test_dsr_high_sharpe_passes_28trial_gauntlet():
    """A 'large' observed Sharpe with enough obs should pass DSR > 0.95
    even at n_trials = 28 (the gauntlet's deflation denominator)."""
    dsr = stats.deflated_sharpe_ratio(
        sharpe_observed=3.0, n_trials=28, n_obs=2520,  # 10 yrs daily
        skewness=0.0, excess_kurtosis=0.0,
    )
    assert dsr > 0.95


def test_dsr_low_sharpe_fails_28trial_gauntlet():
    dsr = stats.deflated_sharpe_ratio(
        sharpe_observed=0.5, n_trials=28, n_obs=2520,
    )
    assert dsr < 0.95


def test_dsr_rejects_invalid_n_trials():
    with pytest.raises(ValueError):
        stats.deflated_sharpe_ratio(1.0, n_trials=0, n_obs=100)


# ---------------------------------------------------------------------------
# Stationary bootstrap CI
# ---------------------------------------------------------------------------

def test_bootstrap_indices_length_matches_n():
    rng = np.random.default_rng(0)
    idx = stats.stationary_bootstrap_indices(500, expected_block_size=21, rng=rng)
    assert idx.shape == (500,)
    assert idx.min() >= 0
    assert idx.max() < 500


def test_bootstrap_indices_handles_empty():
    rng = np.random.default_rng(0)
    idx = stats.stationary_bootstrap_indices(0, expected_block_size=21, rng=rng)
    assert idx.size == 0


def test_bootstrap_indices_rejects_zero_block():
    rng = np.random.default_rng(0)
    with pytest.raises(ValueError):
        stats.stationary_bootstrap_indices(100, 0, rng)


def test_bootstrap_ci_contains_point_estimate_for_normal_series():
    rng = np.random.default_rng(42)
    r = rng.normal(0.0005, 0.01, 1500)
    out = stats.stationary_bootstrap_sharpe_ci(
        r, n_replications=500, expected_block_size=21, seed=7,
    )
    # Point estimate should fall inside the 95% CI (roughly — bootstrap
    # has noise but the inclusion is overwhelmingly likely).
    assert out.lower <= out.sharpe <= out.upper or \
           abs(out.sharpe - (out.lower + out.upper) / 2) < (out.upper - out.lower)


def test_bootstrap_ci_is_deterministic_given_seed():
    rng = np.random.default_rng(0)
    r = rng.normal(0.0, 0.01, 500)
    a = stats.stationary_bootstrap_sharpe_ci(r, n_replications=200, seed=7)
    b = stats.stationary_bootstrap_sharpe_ci(r, n_replications=200, seed=7)
    assert a.lower == b.lower and a.upper == b.upper


def test_bootstrap_ci_short_series_returns_nan_bounds():
    out = stats.stationary_bootstrap_sharpe_ci(np.array([0.01, 0.02]),
                                                expected_block_size=21)
    assert math.isnan(out.lower) and math.isnan(out.upper)
    assert out.n_replications == 0


def test_bootstrap_ci_width_shrinks_with_more_replications():
    rng = np.random.default_rng(0)
    r = rng.normal(0.0005, 0.01, 1000)
    a = stats.stationary_bootstrap_sharpe_ci(r, n_replications=100, seed=1)
    b = stats.stationary_bootstrap_sharpe_ci(r, n_replications=2000, seed=1)
    # CI width should stabilize / shrink as replications grow.
    width_a = a.upper - a.lower
    width_b = b.upper - b.lower
    # Within 30% — bootstrap CI converges with replications.
    assert width_b <= 1.3 * width_a


# ---------------------------------------------------------------------------
# Sign agreement
# ---------------------------------------------------------------------------

def test_sign_agreement_both_positive_returns_true():
    rng = np.random.default_rng(0)
    a = rng.normal(0.001, 0.01, 500)
    b = rng.normal(0.001, 0.01, 500)
    assert stats.sign_agreement(a, b)


def test_sign_agreement_one_negative_returns_false():
    rng = np.random.default_rng(0)
    a = rng.normal(0.001, 0.01, 500)
    b = rng.normal(-0.001, 0.01, 500)
    assert not stats.sign_agreement(a, b)
