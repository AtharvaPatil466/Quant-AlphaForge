"""DSR variant reconciliation + divergence bounds.

The project shipped four DSR implementations. These tests:
  1. prove the canonical `from_trials` (empirical-σ̂) form reproduces PEAD;
  2. bound how far the historical analytic variants (crypto, India) drift from
     the canonical exact form, in the regime the substrates operated in;
  3. assert the divergence never flips a verdict across the 0.95 hurdle.

Bounds are the empirically-observed maxima (see reports/dsr_variant_divergence.py)
with headroom, so a future change that widens the disagreement fails loudly.
"""
import math
import os
import sys

import pytest

import afgauntlet as g

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from reports import _upstreams as up  # noqa: E402

ANN = 252.0
_SR_GRID = [0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0]
_N_GRID = [10, 28, 56]
_OBS_GRID = [252, 504, 1260, 2520]


@pytest.fixture(scope="module")
def pead():
    return up.pead_dsr()


@pytest.fixture(scope="module")
def crypto():
    return up.crypto_dsr()


@pytest.fixture(scope="module")
def india():
    return up.india_dsr()


def test_canonical_from_trials_reconciles_pead(pead):
    cands = [0.2, 0.4, 0.55, 0.7, 0.9, 1.1, 1.4, 0.3, 0.6, 0.85]
    for sr in (0.5, 1.0, 2.0, 2.5):
        for nobs in (252, 1260):
            a = g.deflated_sharpe_ratio_from_trials(sr, nobs, cands)
            b = pead(sr, nobs, cands)
            assert a == pytest.approx(b, abs=1e-7), f"sr={sr}, nobs={nobs}"


def test_crypto_divergence_bounded(crypto):
    worst = 0.0
    for sr in _SR_GRID:
        sr_pp = sr / math.sqrt(ANN)
        for N in _N_GRID:
            for nobs in _OBS_GRID:
                canon = g.deflated_sharpe_ratio(sr, N, nobs)
                d = crypto(sr_pp, n_trials=N, skewness=0.0, kurtosis=3.0,
                           n_observations=nobs)
                worst = max(worst, abs(d - canon))
    assert worst < 0.01, f"crypto DSR divergence grew to {worst:.4f}"


def test_india_divergence_bounded_and_nonzero(india):
    worst = 0.0
    for sr in _SR_GRID:
        sr_pp = sr / math.sqrt(ANN)
        for N in _N_GRID:
            for nobs in _OBS_GRID:
                canon = g.deflated_sharpe_ratio(sr, N, nobs)
                d = india(sr_pp, n_trials=N, n_obs=nobs, skew=0.0, kurt_excess=0.0)
                worst = max(worst, abs(d - canon))
    # India's asymptotic E[max] is a genuine (small) divergence, not noise.
    assert 0.0 < worst < 0.05, f"India DSR divergence = {worst:.4f}"


def test_no_verdict_flips_across_variants(crypto, india):
    """No (sr, N, n_obs) point where one variant clears 0.95 and another does
    not — i.e. the estimator inconsistency never changed a pass/fail decision."""
    flips = 0
    for sr in _SR_GRID:
        sr_pp = sr / math.sqrt(ANN)
        for N in _N_GRID:
            for nobs in _OBS_GRID:
                vals = [
                    g.deflated_sharpe_ratio(sr, N, nobs),
                    crypto(sr_pp, n_trials=N, skewness=0.0, kurtosis=3.0, n_observations=nobs),
                    india(sr_pp, n_trials=N, n_obs=nobs, skew=0.0, kurt_excess=0.0),
                ]
                if max(vals) > 0.95 and min(vals) <= 0.95:
                    flips += 1
    assert flips == 0, f"{flips} verdict flips across DSR variants"
