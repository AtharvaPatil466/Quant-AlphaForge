"""Reconciliation tests: the canonical gauntlet must reproduce the upstream
substrate implementations to float equality.

This is the load-bearing evidence that consolidating the four per-substrate
copies into one package did not silently change any number — i.e. that no
historical verdict was an implementation artifact. Each upstream module is
loaded standalone (by file path) so we compare against the *exact* code that
produced the published verdicts.

If an upstream file moves or a signature diverges, the relevant test is skipped
with a recorded reason rather than failing spuriously; a genuine numerical
divergence in a matching function FAILS loudly — that is the finding.
"""
import importlib.util
import os
import sys

import numpy as np
import pytest

import afgauntlet as g

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load(path: str, name: str):
    full = os.path.join(_REPO_ROOT, path)
    if not os.path.exists(full):
        pytest.skip(f"upstream not found: {path}")
    spec = importlib.util.spec_from_file_location(name, full)
    mod = importlib.util.module_from_spec(spec)
    # Register before exec so @dataclass can resolve sys.modules[__module__].
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def vix():
    return _load("alphaforge-vix/gauntlet/stats.py", "vix_stats_upstream")


@pytest.fixture(scope="module")
def hygiene():
    return _load("alphaforge-python/research/stats_hygiene.py", "stats_hygiene_upstream")


# ─── VIX gauntlet/stats.py ───────────────────────────────────────────────────

def test_reconcile_annualized_sharpe(vix):
    rng = np.random.default_rng(2)
    for _ in range(5):
        r = rng.normal(0.001, 0.012, 800)
        assert g.annualized_sharpe(r) == vix.annualized_sharpe(r)


def test_reconcile_skew_kurtosis(vix):
    rng = np.random.default_rng(4)
    r = rng.normal(0, 0.01, 1000)
    assert g.sample_skewness(r) == vix.sample_skewness(r)
    assert g.sample_excess_kurtosis(r) == vix.sample_excess_kurtosis(r)


def test_reconcile_cornish_fisher(vix):
    rng = np.random.default_rng(6)
    for _ in range(5):
        r = rng.normal(0.0008, 0.01, 1000)
        assert g.cornish_fisher_sharpe(r) == vix.cornish_fisher_sharpe(r)


def test_reconcile_deflated_sharpe(vix):
    cases = [(0.5, 28, 1260), (1.0, 10, 2520), (2.5, 1, 504),
             (0.3, 56, 1000), (-0.4, 28, 1260)]
    for sr, n, nobs in cases:
        a = g.deflated_sharpe_ratio(sr, n, nobs, skewness=-0.3, excess_kurtosis=2.0)
        b = vix.deflated_sharpe_ratio(sr, n, nobs, skewness=-0.3, excess_kurtosis=2.0)
        assert a == b, f"DSR mismatch at {(sr, n, nobs)}: {a} != {b}"


def test_reconcile_bootstrap_ci(vix):
    rng = np.random.default_rng(8)
    r = rng.normal(0.0009, 0.011, 1500)
    a = g.stationary_bootstrap_sharpe_ci(r, n_replications=600, expected_block_size=21, seed=3)
    b = vix.stationary_bootstrap_sharpe_ci(r, n_replications=600, expected_block_size=21, seed=3)
    assert (a.sharpe, a.lower, a.upper) == (b.sharpe, b.lower, b.upper)


def test_reconcile_bootstrap_indices(vix):
    rng_a = np.random.default_rng(0)
    rng_b = np.random.default_rng(0)
    ia = g.stationary_bootstrap_indices(500, 21, rng_a)
    ib = vix.stationary_bootstrap_indices(500, 21, rng_b)
    assert np.array_equal(ia, ib)


# ─── equity stack research/stats_hygiene.py ──────────────────────────────────

def test_reconcile_hansen_spa(hygiene):
    rng = np.random.default_rng(10)
    M = rng.normal(0.0, 0.01, (400, 6))
    M[:, 2] += 0.002
    a = g.hansen_spa_test(M, reps=400, mean_block=21, seed=1)
    b = hygiene.hansen_spa_test(M, reps=400, mean_block=21, seed=1)
    assert a["T_spa"] == b["T_spa"]
    assert a["p_value"] == b["p_value"]
    assert a["argmax"] == b["argmax"]


def test_reconcile_white_reality_check(hygiene):
    rng = np.random.default_rng(12)
    M = rng.normal(0.0, 0.01, (350, 5))
    M[:, 0] += 0.0015
    a = g.white_reality_check(M, reps=400, mean_block=21, seed=2)
    b = hygiene.white_reality_check(M, reps=400, mean_block=21, seed=2)
    assert a["T_rc"] == b["T_rc"]
    assert a["p_value"] == b["p_value"]


def test_reconcile_purged_embargo_splits(hygiene):
    a_cv = g.PurgedEmbargoedKFold(n_splits=5, label_horizon=21, embargo_pct=0.01)
    b_cv = hygiene.PurgedEmbargoedKFold(n_splits=5, label_horizon=21, embargo_pct=0.01)
    for (atr, ate), (btr, bte) in zip(a_cv.split(1000), b_cv.split(1000)):
        assert np.array_equal(atr, btr)
        assert np.array_equal(ate, bte)
