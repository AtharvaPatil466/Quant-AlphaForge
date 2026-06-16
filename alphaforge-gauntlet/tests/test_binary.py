"""Tests for the binary-outcome calibration gauntlet (``afgauntlet.binary``).

Covers the load-bearing claims of the FLB stack:

  (a) golden scoring values (Brier / log-loss on hand-computed arrays);
  (b) a perfectly-calibrated synthetic set → reliability edges ≈ 0, slope ≈ 1;
  (c) injected-FLB recovery — longshots that under-resolve and favorites that
      over-resolve are detected with CIs that exclude zero, in the right signs;
  (d) ``binary_mde`` monotonicity (smaller |edge| → more events; higher power →
      more events) plus a sanity magnitude check;
  (e) the calibration gates fire on injected FLB and pass-through on a
      calibrated null.

All stochastic tests are seeded; bootstrap / sample counts are kept small so the
module runs in a couple of seconds.
"""
import math

import numpy as np
import pytest

import afgauntlet as afg
from afgauntlet.binary import (binary_mde, brier_score, bucket_edge_ci,
                               calibration_slope_intercept,
                               gate_calibration_gap, gate_edge_ci_excludes_zero,
                               gate_net_of_fee_edge, log_loss,
                               reliability_curve)

# The FLB study's cent buckets.
CENT_BINS = [0.0, 0.05, 0.15, 0.35, 0.65, 0.85, 0.95, 1.0]


def _calibrated_dataset(n=20000, seed=0):
    """A perfectly-calibrated set: outcome ~ Bernoulli(predicted)."""
    rng = np.random.default_rng(seed)
    p = rng.uniform(0.0, 1.0, size=n)
    y = (rng.uniform(0.0, 1.0, size=n) < p).astype(float)
    return p, y


def _flb_dataset(n_per=8000, seed=1):
    """Injected FLB: two point masses.

    Longshots quoted p=0.10 actually resolve YES only 5% (over-priced → negative
    edge); favorites quoted p=0.90 actually resolve YES 95% (under-priced →
    positive edge). Plus a calibrated middle bucket at p=0.50 / 50%.
    """
    rng = np.random.default_rng(seed)
    p = np.concatenate([
        np.full(n_per, 0.10),
        np.full(n_per, 0.50),
        np.full(n_per, 0.90),
    ])
    y = np.concatenate([
        (rng.uniform(size=n_per) < 0.05).astype(float),
        (rng.uniform(size=n_per) < 0.50).astype(float),
        (rng.uniform(size=n_per) < 0.95).astype(float),
    ])
    return p, y


# ─── (a) golden scoring values ────────────────────────────────────────────────

def test_brier_golden():
    p = [0.8, 0.3, 0.6, 0.1]
    y = [1, 0, 1, 0]
    # (0.04 + 0.09 + 0.16 + 0.01) / 4 = 0.075
    assert brier_score(p, y) == pytest.approx(0.075)


def test_log_loss_golden():
    p = [0.8, 0.3, 0.6, 0.1]
    y = [1, 0, 1, 0]
    expected = -np.mean([math.log(0.8), math.log(0.7),
                         math.log(0.6), math.log(0.9)])
    assert log_loss(p, y) == pytest.approx(expected)
    assert log_loss(p, y) == pytest.approx(0.2990011586691898)


def test_log_loss_clips_confident_miss():
    # p=0 with y=1 would be -inf without clipping; clip bounds it.
    val = log_loss([0.0, 1.0], [1, 0], eps=1e-12)
    assert math.isfinite(val)
    assert val == pytest.approx(-math.log(1e-12))


def test_brier_perfect_and_empty():
    assert brier_score([1.0, 0.0], [1, 0]) == pytest.approx(0.0)
    assert math.isnan(brier_score([], []))
    assert math.isnan(log_loss([], []))


def test_align_rejects_shape_mismatch():
    with pytest.raises(ValueError):
        brier_score([0.5, 0.5], [1])


# ─── (b) perfectly-calibrated set → edges ≈ 0, slope ≈ 1 ───────────────────────

def test_reliability_edges_near_zero_when_calibrated():
    p, y = _calibrated_dataset(n=40000, seed=0)
    rows = reliability_curve(p, y, CENT_BINS)
    assert len(rows) == len(CENT_BINS) - 1  # all buckets populated on uniform p
    for r in rows:
        assert abs(r["edge"]) < 0.03, r
        assert r["realized_freq"] == pytest.approx(r["p_mean"], abs=0.03)
    # Counts reconstitute the full sample.
    assert sum(r["count"] for r in rows) == p.size


def test_calibration_slope_intercept_near_identity():
    p, y = _calibrated_dataset(n=40000, seed=2)
    slope, intercept = calibration_slope_intercept(p, y)
    assert slope == pytest.approx(1.0, abs=0.1)
    assert intercept == pytest.approx(0.0, abs=0.1)


def test_calibration_slope_degenerate():
    # All-YES outcomes → no variation → undefined fit.
    s, i = calibration_slope_intercept([0.3, 0.6, 0.9], [1, 1, 1])
    assert math.isnan(s) and math.isnan(i)
    # Too few events.
    s, i = calibration_slope_intercept([0.5, 0.5], [1, 0])
    assert math.isnan(s) and math.isnan(i)


# ─── (c) injected-FLB recovery ────────────────────────────────────────────────

def test_flb_low_bucket_negative_edge_excludes_zero():
    p, y = _flb_dataset(seed=1)
    res = bucket_edge_ci(p, y, lo=0.0, hi=0.15, seed=0)
    # Quoted ~0.10, realized ~0.05 → edge ~ -0.05.
    assert res["edge"] < 0
    assert res["edge"] == pytest.approx(-0.05, abs=0.02)
    assert res["excludes_zero"] is True
    assert res["hi"] < 0  # whole CI below zero
    assert res["n"] == 8000


def test_flb_high_bucket_positive_edge_excludes_zero():
    p, y = _flb_dataset(seed=1)
    res = bucket_edge_ci(p, y, lo=0.85, hi=1.0, seed=0)
    # Quoted ~0.90, realized ~0.95 → edge ~ +0.05.
    assert res["edge"] > 0
    assert res["edge"] == pytest.approx(0.05, abs=0.02)
    assert res["excludes_zero"] is True
    assert res["lo"] > 0  # whole CI above zero


def test_calibrated_middle_bucket_does_not_exclude_zero():
    p, y = _flb_dataset(seed=1)
    res = bucket_edge_ci(p, y, lo=0.35, hi=0.65, seed=0)
    assert abs(res["edge"]) < 0.03
    assert res["excludes_zero"] is False


def test_flb_slope_departs_from_identity():
    # FLB miscalibration → recalibration slope != 1. (In this dataset the
    # realized tails are *more* extreme than implied — 0.10→0.05, 0.90→0.95 —
    # so the slope sits above 1; a calibrated set sits at 1.)
    p, y = _flb_dataset(seed=1)
    slope, _ = calibration_slope_intercept(p, y)
    assert abs(slope - 1.0) > 0.1
    # And the calibrated control stays at identity.
    pc, yc = _calibrated_dataset(n=40000, seed=2)
    s_cal, _ = calibration_slope_intercept(pc, yc)
    assert abs(s_cal - 1.0) < 0.1


def test_bucket_edge_ci_empty_region():
    res = bucket_edge_ci([0.5, 0.5], [1, 0], lo=0.9, hi=1.0)
    assert res["n"] == 0
    assert res["excludes_zero"] is False
    assert math.isnan(res["edge"])


# ─── (d) binary_mde power analysis ────────────────────────────────────────────

def test_binary_mde_smaller_edge_more_events():
    n_big = binary_mde(0.10, base_rate=0.10)
    n_small = binary_mde(0.02, base_rate=0.10)
    assert n_small > n_big


def test_binary_mde_higher_power_more_events():
    n_lo = binary_mde(0.05, base_rate=0.10, power=0.8)
    n_hi = binary_mde(0.05, base_rate=0.10, power=0.95)
    assert n_hi > n_lo


def test_binary_mde_monotone_grid():
    edges = [0.20, 0.10, 0.05, 0.02, 0.01]
    ns = [binary_mde(e, base_rate=0.10) for e in edges]
    assert ns == sorted(ns)  # increasing as edge shrinks
    for a, b in zip(ns, ns[1:]):
        assert b > a         # strictly increasing


def test_binary_mde_magnitude_sanity():
    # Detecting a 5pp move off a 10% base at 80%/0.05 is in the low hundreds,
    # not single digits and not millions — the small-N wall in concrete terms.
    n = binary_mde(0.05, base_rate=0.10)
    assert 100 < n < 1000
    # The count depends on the alternative's variance, so an upward 5pp move
    # (p1=0.15) and a downward one (p1=0.05) are each monotone in |edge| but not
    # identical — both are positive, finite, and modest.
    assert binary_mde(0.05, 0.10) > 0
    assert binary_mde(-0.05, 0.10) > 0


def test_binary_mde_rejects_zero_edge():
    with pytest.raises(ValueError):
        binary_mde(0.0, base_rate=0.10)
    with pytest.raises(ValueError):
        binary_mde(0.05, base_rate=0.0)


# ─── (e) gates ────────────────────────────────────────────────────────────────

def test_gate_calibration_gap_fires_on_flb():
    p, y = _flb_dataset(seed=1)
    g_low = gate_calibration_gap(p, y, 0.0, 0.15, "negative", min_gap=0.02)
    g_high = gate_calibration_gap(p, y, 0.85, 1.0, "positive", min_gap=0.02)
    assert g_low.passed and g_high.passed
    assert g_low.value < 0 and g_high.value > 0
    assert isinstance(g_low, afg.GateOutcome)


def test_gate_calibration_gap_passes_through_on_null():
    p, y = _calibrated_dataset(n=40000, seed=5)
    g = gate_calibration_gap(p, y, 0.0, 0.15, "negative", min_gap=0.02)
    assert g.passed is False  # no real gap on a calibrated set


def test_gate_edge_ci_excludes_zero_composes():
    p, y = _flb_dataset(seed=1)
    g_flb = gate_edge_ci_excludes_zero(p, y, 0.0, 0.15, seed=0)
    assert g_flb.passed is True

    pc, yc = _calibrated_dataset(n=40000, seed=6)
    g_null = gate_edge_ci_excludes_zero(pc, yc, 0.0, 0.05, seed=0)
    assert g_null.passed is False


def test_gate_net_of_fee_edge():
    # Gross 0.05 edge survives a 0.02 fee.
    g_ok = gate_net_of_fee_edge(0.05, fee_per_unit=0.02)
    assert g_ok.passed and g_ok.value == pytest.approx(0.03)
    # Gross 0.03 edge does not survive a 0.04 fee.
    g_bad = gate_net_of_fee_edge(0.03, fee_per_unit=0.04)
    assert g_bad.passed is False
    # Sign-agnostic on the gross edge magnitude.
    assert gate_net_of_fee_edge(-0.05, 0.02).passed is True


def test_gates_compose_into_report():
    p, y = _flb_dataset(seed=1)
    gates = [
        gate_calibration_gap(p, y, 0.85, 1.0, "positive", min_gap=0.02),
        gate_edge_ci_excludes_zero(p, y, 0.85, 1.0, seed=0),
        gate_net_of_fee_edge(0.05, fee_per_unit=0.02),
    ]
    report = afg.evaluate_gates(gates)
    assert report.deploy_ready is True
    assert report.n_total == 3
    assert "DEPLOY-READY" in report.summary()


def test_public_exports_present():
    for name in ("brier_score", "log_loss", "reliability_curve",
                 "calibration_slope_intercept", "bucket_edge_ci", "binary_mde",
                 "gate_calibration_gap", "gate_edge_ci_excludes_zero",
                 "gate_net_of_fee_edge"):
        assert hasattr(afg, name)
        assert name in afg.__all__
