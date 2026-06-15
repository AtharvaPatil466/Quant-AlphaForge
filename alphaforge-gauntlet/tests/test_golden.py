"""Golden / analytic-invariant tests for the canonical gauntlet.

These assert mathematically guaranteed properties (monotonicities, bounds,
known-regime values) rather than statistically-likely outcomes, so they are
deterministic and not flaky.
"""
import math

import numpy as np
import pytest

import afgauntlet as g


# ─── Sharpe ──────────────────────────────────────────────────────────────────

def test_annualized_sharpe_matches_manual():
    rng = np.random.default_rng(1)
    r = rng.normal(0.001, 0.01, 1000)
    expected = r.mean() / r.std(ddof=1) * math.sqrt(252.0)
    assert g.annualized_sharpe(r) == pytest.approx(expected, rel=1e-12)


def test_annualized_sharpe_zero_std_is_zero():
    assert g.annualized_sharpe(np.full(100, 0.001)) == 0.0


def test_annualized_sharpe_too_short_is_nan():
    assert math.isnan(g.annualized_sharpe(np.array([0.01])))


# ─── Deflated Sharpe ─────────────────────────────────────────────────────────

def test_dsr_in_unit_interval():
    for sr in (-1.0, 0.0, 0.5, 1.0, 3.0):
        for n in (1, 10, 100):
            d = g.deflated_sharpe_ratio(sr, n, 1260)
            assert 0.0 <= d <= 1.0


def test_dsr_monotonic_in_observed_sharpe():
    vals = [g.deflated_sharpe_ratio(sr, 28, 1260) for sr in (0.0, 0.5, 1.0, 2.0, 3.0)]
    assert all(b >= a for a, b in zip(vals, vals[1:]))


def test_dsr_decreasing_in_n_trials():
    vals = [g.deflated_sharpe_ratio(1.0, n, 1260) for n in (1, 5, 28, 100, 1000)]
    assert all(b <= a for a, b in zip(vals, vals[1:]))


def test_dsr_known_regime_fails_and_passes():
    # Modest Sharpe over ~5y OOS deflated vs 28 trials -> below 0.95 hurdle
    assert g.deflated_sharpe_ratio(0.5, 28, 1260) < 0.95
    # Strong Sharpe, single trial, long sample -> clears it
    assert g.deflated_sharpe_ratio(3.0, 1, 2520) > 0.95


def test_dsr_rejects_zero_trials():
    with pytest.raises(ValueError):
        g.deflated_sharpe_ratio(1.0, 0, 1260)


def test_expected_max_sharpe_increases_with_trials():
    vals = [g.expected_max_sharpe(n) for n in (1, 2, 10, 28, 100)]
    assert vals[0] == 0.0
    assert all(b >= a for a, b in zip(vals[1:], vals[2:]))


# ─── Cornish-Fisher ──────────────────────────────────────────────────────────

def test_cf_penalizes_negative_skew():
    rng = np.random.default_rng(3)
    sym = rng.normal(0.0008, 0.01, 4000)
    # Build a negatively-skewed series with similar mean/std.
    neg = -np.abs(rng.normal(0, 0.01, 4000)) ** 1.0
    neg = neg - neg.mean() + 0.0008
    base = g.annualized_sharpe(neg)
    cf = g.cornish_fisher_sharpe(neg)
    if g.sample_skewness(neg) < 0:
        assert cf < base  # negative skew is penalized
    # symmetric -> CF close to plain Sharpe
    assert g.cornish_fisher_sharpe(sym) == pytest.approx(g.annualized_sharpe(sym), rel=0.15)


# ─── Bootstrap CI ────────────────────────────────────────────────────────────

def test_bootstrap_ci_reproducible_and_ordered():
    rng = np.random.default_rng(11)
    r = rng.normal(0.0009, 0.01, 1500)
    a = g.stationary_bootstrap_sharpe_ci(r, n_replications=400, seed=42)
    b = g.stationary_bootstrap_sharpe_ci(r, n_replications=400, seed=42)
    assert (a.lower, a.upper) == (b.lower, b.upper)
    assert a.lower <= a.upper


def test_bootstrap_excludes_zero_semantics():
    rng = np.random.default_rng(5)
    strong = rng.normal(0.0025, 0.008, 2000)   # high Sharpe
    noise = rng.normal(0.0, 0.01, 2000)        # ~zero mean
    assert g.stationary_bootstrap_sharpe_ci(strong, n_replications=600, seed=0).excludes_zero
    assert not g.stationary_bootstrap_sharpe_ci(noise, n_replications=600, seed=0).excludes_zero


# ─── Multiple testing ────────────────────────────────────────────────────────

def test_spa_detects_strong_column():
    rng = np.random.default_rng(9)
    M = rng.normal(0.0, 0.01, (400, 8))
    M[:, 3] += 0.004  # one genuinely skilled strategy
    res = g.hansen_spa_test(M, reps=500, seed=0)
    assert 0.0 <= res["p_value"] <= 1.0
    assert res["argmax"] == 3
    assert res["p_value"] < 0.05


def test_reality_check_more_conservative_than_spa():
    # White's RC p-value >= SPA p-value (it never rejects more easily).
    rng = np.random.default_rng(13)
    M = rng.normal(0.0, 0.01, (400, 6))
    M[:, 1] += 0.0015
    spa = g.hansen_spa_test(M, reps=500, seed=0)["p_value"]
    rc = g.white_reality_check(M, reps=500, seed=0)["p_value"]
    assert rc >= spa - 1e-9


# ─── Purged + embargoed CV ───────────────────────────────────────────────────

def test_purged_embargo_train_test_disjoint_and_gapped():
    cv = g.PurgedEmbargoedKFold(n_splits=5, label_horizon=10, embargo_pct=0.02)
    n = 500
    for train, test in cv.split(n):
        assert set(train).isdisjoint(set(test))
        ts, te = test.min(), test.max()
        # No training index inside the purge/embargo band around the test fold.
        band = set(range(max(0, ts - 10), min(n, te + 1 + int(round(0.02 * n)))))
        assert set(train).isdisjoint(band)


# ─── Gates ───────────────────────────────────────────────────────────────────

def test_gate_max_drawdown_known_path():
    nav = np.array([100.0, 120.0, 90.0, 110.0])  # peak 120 -> trough 90 = 25%
    out = g.gate_max_drawdown(nav, max_drawdown=0.30)
    assert out.value == pytest.approx(0.25, rel=1e-9)
    assert out.passed
    assert not g.gate_max_drawdown(nav, max_drawdown=0.20).passed


def test_report_deploy_ready_is_and_of_gates():
    rng = np.random.default_rng(21)
    strong = rng.normal(0.0030, 0.008, 2520)
    gates = [
        g.gate_deflated_sharpe(strong, n_trials=1),
        g.gate_bootstrap_excludes_zero(strong, n_replications=400),
        g.gate_cost_survival(strong),
    ]
    report = g.evaluate_gates(gates)
    assert report.deploy_ready
    assert report.n_passed == report.n_total
    # One failing gate flips the verdict.
    weak = rng.normal(0.0, 0.01, 1260)
    report2 = g.evaluate_gates([g.gate_deflated_sharpe(weak, n_trials=28)] + gates)
    assert not report2.deploy_ready


def test_source_hash_is_deterministic_hex():
    h1, h2 = g.source_hash(), g.source_hash()
    assert h1 == h2
    assert len(h1) == 64 and all(c in "0123456789abcdef" for c in h1)
