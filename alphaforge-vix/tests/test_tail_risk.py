"""Unit tests for gauntlet/tail_risk.py."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from gauntlet import tail_risk as tr


# ---------------------------------------------------------------------------
# Frozen constants
# ---------------------------------------------------------------------------

def test_frozen_constants_match_design():
    assert tr.MAX_DRAWDOWN_THRESHOLD == 0.30
    assert tr.CF_SHARPE_THRESHOLD == 0.50


# ---------------------------------------------------------------------------
# evaluate_stress_period
# ---------------------------------------------------------------------------

def test_stress_period_no_data_returns_no_data():
    nav = pd.Series([1_000_000.0] * 5,
                    index=pd.date_range("2030-01-02", periods=5, freq="B"))
    r = tr.evaluate_stress_period(
        nav, "2008_financial_crisis",
        pd.Timestamp("2008-09-01"), pd.Timestamp("2009-03-31"),
    )
    assert r.coverage == tr.CoverageStatus.NO_DATA
    assert r.drawdown_passes_gate is None
    assert r.max_drawdown is None


def test_stress_period_covered_when_data_present():
    idx = pd.date_range("2020-02-03", periods=60, freq="B")
    # NAV drops 20% then recovers — max DD from entry is 20%.
    n = len(idx)
    nav_vals = np.concatenate([
        np.linspace(1.0, 0.80, n // 2),
        np.linspace(0.80, 0.95, n - n // 2),
    ])
    nav = pd.Series(nav_vals * 1_000_000.0, index=idx)
    r = tr.evaluate_stress_period(
        nav, "2020_covid_crash",
        pd.Timestamp("2020-02-01"), pd.Timestamp("2020-04-30"),
    )
    assert r.coverage == tr.CoverageStatus.COVERED
    assert math.isclose(r.max_drawdown, 0.20, abs_tol=0.001)
    assert r.drawdown_passes_gate  # 20% <= 30%


def test_stress_period_30pct_dd_fails_gate():
    idx = pd.date_range("2020-02-03", periods=10, freq="B")
    nav = pd.Series(np.linspace(1.0, 0.60, 10) * 1_000_000.0, index=idx)
    r = tr.evaluate_stress_period(
        nav, "2020_covid_crash",
        pd.Timestamp("2020-02-01"), pd.Timestamp("2020-04-30"),
    )
    assert math.isclose(r.max_drawdown, 0.40, abs_tol=0.001)
    assert not r.drawdown_passes_gate


# ---------------------------------------------------------------------------
# evaluate_gate5
# ---------------------------------------------------------------------------

def test_gate5_no_data_anywhere_fails():
    nav = pd.Series([1_000_000.0] * 5,
                    index=pd.date_range("2030-01-02", periods=5, freq="B"))
    r = tr.evaluate_gate5(nav)
    assert not r.passes
    assert r.n_covered == 0


def test_gate5_passes_when_all_covered_periods_under_threshold():
    # Build a NAV that touches all 4 stress periods, each with <30% DD.
    idx = pd.date_range("2008-08-01", "2020-12-31", freq="B")
    nav = pd.Series(np.ones(len(idx)) * 1_000_000.0, index=idx)
    # 10% drawdowns in each stress window.
    for _, start, end in tr.STRESS_PERIODS:
        mask = (nav.index >= start) & (nav.index <= end)
        nav.loc[mask] = nav.loc[mask] * 0.92  # 8% drawdown
    r = tr.evaluate_gate5(nav)
    assert r.passes
    assert r.n_covered == 4


def test_gate5_fails_if_one_covered_period_breaches():
    idx = pd.date_range("2008-08-01", "2020-12-31", freq="B")
    nav = pd.Series(np.ones(len(idx)) * 1_000_000.0, index=idx)
    # 2018 Volmageddon: trend from 1.0 → 0.40 within the window → 60% DD.
    _, vm_start, vm_end = tr.STRESS_PERIODS[2]
    mask = (nav.index >= vm_start) & (nav.index <= vm_end)
    n_in_window = int(mask.sum())
    nav.loc[mask] = np.linspace(1.0, 0.40, n_in_window) * 1_000_000.0
    r = tr.evaluate_gate5(nav)
    assert not r.passes


# ---------------------------------------------------------------------------
# evaluate_gate6
# ---------------------------------------------------------------------------

def test_gate6_passes_when_cf_sharpe_above_threshold_both_oos():
    rng = np.random.default_rng(0)
    r_a = pd.Series(rng.normal(0.001, 0.005, 500))
    r_b = pd.Series(rng.normal(0.001, 0.005, 500))
    res = tr.evaluate_gate6(r_a, r_b)
    # mean 0.001, std 0.005, daily Sharpe = 0.2, annualized ≈ 3.17
    # CF-Sharpe close to that for ~normal → way above 0.5
    assert res.passes


def test_gate6_fails_when_cf_sharpe_below_threshold_in_either():
    rng = np.random.default_rng(0)
    r_good = pd.Series(rng.normal(0.001, 0.005, 500))
    r_bad = pd.Series(rng.normal(-0.001, 0.005, 500))
    res = tr.evaluate_gate6(r_good, r_bad)
    assert not res.passes
    assert res.passes_oos_a
    assert not res.passes_oos_b
