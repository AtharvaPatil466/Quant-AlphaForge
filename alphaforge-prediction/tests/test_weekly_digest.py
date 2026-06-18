"""Tests for the weekly forward-digest summariser (pure logic, synthetic data)."""
from __future__ import annotations

from research.weekly_digest import compute_digest

_NOW = "2026-06-22T09:00:00Z"


def _card(*, n_resolved=6, target=200, success=False, generated_at=_NOW):
    return {
        "generated_at": generated_at,
        "target_resolved": target,
        "rule": {"name": "provisional-FLB-forward-v1-nonMVE",
                 "provisional": True, "max_days_to_close": 45.0},
        "counts": {"n_placed": 686, "n_resolved": n_resolved,
                   "n_open": 686 - n_resolved,
                   "fraction_of_target": n_resolved / target},
        "pnl": {"net_pnl": 0.83, "net_pnl_2x_fee": 0.77},
        "calibration": {"brier_market_implied": 0.0004,
                        "log_loss_market_implied": 0.0157, "base_rate_brier": 0.25},
        "edge": {"longshot": {"edge": -0.008, "lo": -0.02, "hi": -0.001,
                              "n": 3, "excludes_zero": True},
                 "favorite": {"edge": 0.023, "lo": 0.01, "hi": 0.04,
                              "n": 3, "excludes_zero": True}},
        "success_check": {"PHASE2_SUCCESS": success,
                          "edge_ci_excludes_zero": True,
                          "calibration_beats_market": True},
    }


def test_accumulating_is_not_a_decision_point():
    text, state, decision = compute_digest(_card(n_resolved=6), None, _NOW)
    assert decision is False
    assert "ACCUMULATING" in text
    assert "READ NOW" not in text
    assert state["n_resolved"] == 6


def test_week_over_week_delta():
    prev = {"n_resolved": 4, "timestamp": "2026-06-15T09:00:00Z"}
    text, state, _ = compute_digest(_card(n_resolved=10), prev, _NOW)
    assert "+6 this week" in text
    assert state["n_resolved"] == 10


def test_phase2_success_is_a_decision_point():
    text, _, decision = compute_digest(_card(success=True), None, _NOW)
    assert decision is True
    assert "READ NOW" in text and "PHASE2_SUCCESS=True" in text


def test_hitting_target_is_a_decision_point_even_without_success():
    text, _, decision = compute_digest(_card(n_resolved=200, success=False), None, _NOW)
    assert decision is True
    assert "READ NOW" in text


def test_stale_scorecard_is_flagged():
    # scorecard generated 5 days before "now" -> stale warning.
    text, _, _ = compute_digest(_card(generated_at="2026-06-17T09:00:00Z"),
                                None, "2026-06-22T09:00:00Z")
    assert "WARN" in text and "stalled" in text


def test_first_run_delta_is_full_count():
    text, _, _ = compute_digest(_card(n_resolved=6), None, _NOW)
    assert "+6 this week" in text
