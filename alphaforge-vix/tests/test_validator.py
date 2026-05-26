"""Tests for ingest.validator."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from ingest import validator as V


# ---------------------------------------------------------------------------
# check_term_structure
# ---------------------------------------------------------------------------

def _make_cboe_panel(years=20):
    """Synthetic CBOE-shape panel with all 5 columns."""
    dates = pd.date_range("2006-01-02", periods=252 * years, freq="B")
    rng = np.random.default_rng(7)
    base = 15 + 5 * np.sin(np.linspace(0, years * 6, len(dates))) \
           + rng.normal(0, 2, len(dates))
    panel = pd.DataFrame({
        "VIX": np.clip(base, 9, 80),
        "VIX1D": np.clip(base - 2, 6, 80),
        "VIX9D": np.clip(base - 1, 7, 80),
        "VIX3M": np.clip(base + 3, 12, 80),
        "VIX6M": np.clip(base + 4, 13, 80),
    }, index=dates)
    panel.index.name = "date"
    return panel


def test_check_term_structure_passes_on_full_panel():
    panel = _make_cboe_panel()
    # Override the first dates so they're inside the slack window.
    r = V.check_term_structure(panel)
    # 2006 start is too early for VIX3M/VIX9D/VIX1D so we expect WARN.
    assert r.status in {V.Status.PASS.value, V.Status.WARN.value}


def test_check_term_structure_fails_on_missing_column():
    panel = _make_cboe_panel().drop(columns=["VIX3M"])
    r = V.check_term_structure(panel)
    assert r.status == V.Status.FAIL.value
    assert "VIX3M" in r.metrics["missing_columns"]


def test_check_term_structure_fails_on_empty():
    r = V.check_term_structure(None)
    assert r.status == V.Status.FAIL.value


# ---------------------------------------------------------------------------
# check_spy_spikes
# ---------------------------------------------------------------------------

def test_check_spy_spikes_fails_on_empty():
    r = V.check_spy_spikes(None)
    assert r.status == V.Status.FAIL.value


def test_check_spy_spikes_delegates_to_realized_vol_module():
    """We don't re-validate the spike logic here (tested in test_realized_vol).
    We just verify the delegation + status mapping works."""
    from ingest import realized_vol as RV
    # Synthesize a panel that contains all 5 spikes.
    full_idx = pd.date_range("2008-01-01", "2024-12-31", freq="B")
    panel = pd.DataFrame({
        "log_return": pd.Series(0.0, index=full_idx),
        "realized_vol_10": pd.Series(10.0, index=full_idx),
        "realized_vol_21": pd.Series(10.0, index=full_idx),
        "realized_vol_63": pd.Series(10.0, index=full_idx),
    })
    panel.loc[pd.Timestamp("2008-10-15"), "realized_vol_21"] = 80.0
    panel.loc[pd.Timestamp("2010-05-06"), "log_return"] = -0.04
    panel.loc[pd.Timestamp("2015-08-26"), "realized_vol_21"] = 25.0
    panel.loc[pd.Timestamp("2018-02-08"), "realized_vol_21"] = 35.0
    panel.loc[pd.Timestamp("2020-03-16"), "log_return"] = -0.12

    r = V.check_spy_spikes(panel)
    assert r.status == V.Status.PASS.value
    assert r.metrics["n_passed"] == 5


# ---------------------------------------------------------------------------
# check_etp_availability
# ---------------------------------------------------------------------------

def _make_svxy(start="2011-10-04", with_regime=True):
    idx = pd.date_range(start, "2025-12-31", freq="B")
    df = pd.DataFrame({
        "close": np.linspace(100, 50, len(idx)),
        "volume": 1_000_000,
    }, index=idx)
    df.index.name = "date"
    if with_regime:
        boundary = pd.Timestamp("2018-02-27")
        df["regime"] = "pre_restructuring"
        df.loc[df.index >= boundary, "regime"] = "post_restructuring"
    return df


def _make_vxx(start="2018-01-25"):
    idx = pd.date_range(start, "2025-12-31", freq="B")
    return pd.DataFrame({
        "close": np.linspace(40, 60, len(idx)), "volume": 1_000_000,
    }, index=idx)


def test_check_etp_passes_on_complete_inputs():
    r = V.check_etp_availability(_make_svxy(), _make_vxx())
    assert r.status == V.Status.PASS.value
    assert r.metrics["svxy_pre_restructuring_rows"] > 0
    assert r.metrics["svxy_post_restructuring_rows"] > 0


def test_check_etp_fails_when_svxy_missing_regime():
    svxy = _make_svxy(with_regime=False)
    r = V.check_etp_availability(svxy, _make_vxx())
    assert r.status == V.Status.FAIL.value
    assert any("regime" in e for e in r.errors)


def test_check_etp_fails_when_svxy_starts_late():
    svxy_late = _make_svxy(start="2015-01-02")
    r = V.check_etp_availability(svxy_late, _make_vxx())
    assert r.status == V.Status.FAIL.value


def test_check_etp_fails_when_vxx_missing():
    r = V.check_etp_availability(_make_svxy(), None)
    assert r.status == V.Status.FAIL.value
    assert any("vxx" in e.lower() for e in r.errors)


# ---------------------------------------------------------------------------
# check_vix_cross_consistency
# ---------------------------------------------------------------------------

def test_check_vix_cross_passes_when_series_identical():
    idx = pd.date_range("2010-01-04", periods=2000, freq="B")
    s = pd.Series(15 + np.random.default_rng(1).normal(0, 2, len(idx)), index=idx)
    r = V.check_vix_cross_consistency(s, s.copy())
    assert r.status == V.Status.PASS.value
    assert r.metrics["correlation"] == pytest.approx(1.0)


def test_check_vix_cross_warns_when_correlation_low():
    idx = pd.date_range("2010-01-04", periods=2000, freq="B")
    rng = np.random.default_rng(1)
    cboe = pd.Series(rng.normal(0, 1, len(idx)), index=idx)
    yf = pd.Series(rng.normal(0, 1, len(idx)), index=idx)  # different draws
    r = V.check_vix_cross_consistency(cboe, yf)
    # Two independent random series correlate near 0 → WARN.
    assert r.status == V.Status.WARN.value


def test_check_vix_cross_skips_when_no_overlap():
    s1 = pd.Series([15.0], index=[pd.Timestamp("2010-01-04")])
    s2 = pd.Series([15.0], index=[pd.Timestamp("2020-01-04")])
    r = V.check_vix_cross_consistency(s1, s2)
    assert r.status == V.Status.WARN.value


# ---------------------------------------------------------------------------
# check_contango_bias
# ---------------------------------------------------------------------------

def test_check_contango_passes_when_vix3m_typically_above_vix():
    panel = _make_cboe_panel()
    r = V.check_contango_bias(panel)
    # Synthetic panel sets VIX3M = base + 3 vs VIX = base, so VIX3M > VIX 100%.
    assert r.status == V.Status.PASS.value
    assert r.metrics["contango_fraction"] == pytest.approx(1.0)


def test_check_contango_warns_when_backwardation_dominant():
    idx = pd.date_range("2010-01-04", periods=500, freq="B")
    panel = pd.DataFrame({
        "VIX": np.full(len(idx), 30.0),    # high vol
        "VIX3M": np.full(len(idx), 20.0),  # below VIX → backwardation
    }, index=idx)
    r = V.check_contango_bias(panel)
    assert r.status == V.Status.WARN.value


def test_check_contango_skips_when_columns_missing():
    panel = pd.DataFrame({"VIX": [15.0, 16.0]},
                          index=pd.date_range("2024-01-01", periods=2))
    r = V.check_contango_bias(panel)
    assert r.status == V.Status.SKIP.value


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def test_run_phase0_validators_returns_all_checks():
    inputs = V.ValidatorInputs()
    results = V.run_phase0_validators(inputs)
    expected = {
        "term_structure", "spy_spike_events", "etp_availability",
        "vix_cross_consistency", "contango_bias",
        "vix_futures_settlements", "fred_dgs3mo",
    }
    assert set(results.keys()) == expected


def test_run_phase0_validators_marks_addendum_skips():
    results = V.run_phase0_validators(V.ValidatorInputs())
    assert results["vix_futures_settlements"].status == V.Status.SKIP.value
    assert "ADDENDUM" in results["vix_futures_settlements"].summary
    assert results["fred_dgs3mo"].status == V.Status.SKIP.value


# ---------------------------------------------------------------------------
# render_markdown_report
# ---------------------------------------------------------------------------

def test_render_markdown_includes_pass_summary():
    results = {
        "a": V.CheckResult("a", V.Status.PASS.value, "great"),
        "b": V.CheckResult("b", V.Status.FAIL.value, "broken",
                            errors=["err1"]),
    }
    md = V.render_markdown_report(results, design_doc_sha="56d745e7")
    assert "PASS" in md
    assert "FAIL" in md
    assert "broken" in md
    assert "56d745e7" in md
    assert "NOT CERTIFIED" in md


def test_render_markdown_certified_when_no_fail():
    results = {
        "a": V.CheckResult("a", V.Status.PASS.value, "ok"),
        "b": V.CheckResult("b", V.Status.WARN.value, "minor"),
        "c": V.CheckResult("c", V.Status.SKIP.value, "blocked upstream"),
    }
    md = V.render_markdown_report(results)
    assert "# Phase 0 Validation — CERTIFIED" in md
