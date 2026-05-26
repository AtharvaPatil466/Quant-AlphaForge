"""Unit tests for gauntlet/residualization.py."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from gauntlet import residualization as resid


def test_alpha_t_stat_threshold_is_design_value():
    assert resid.ALPHA_T_STAT_THRESHOLD == 1.96


def test_build_factor_panel_drops_none_columns():
    idx = pd.date_range("2020-01-01", periods=10, freq="B")
    spy = pd.Series(np.zeros(10), index=idx)
    panel = resid.build_factor_panel(spy_returns=spy)
    assert list(panel.columns) == ["SPY"]


def test_build_factor_panel_with_all_four():
    idx = pd.date_range("2020-01-01", periods=10, freq="B")
    z = pd.Series(np.zeros(10), index=idx)
    panel = resid.build_factor_panel(spy_returns=z, delta_vix=z,
                                      st_reversal=z, carry_change=z)
    assert set(panel.columns) == {"SPY", "DeltaVIX", "ST_Reversal", "Carry"}


def test_residualize_zero_alpha_when_strategy_equals_factor():
    """If strategy = SPY × 0.5, the regression recovers alpha ≈ 0, β_SPY ≈ 0.5."""
    rng = np.random.default_rng(0)
    n = 500
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    spy = pd.Series(rng.normal(0.0005, 0.012, n), index=idx)
    strategy = 0.5 * spy
    panel = resid.build_factor_panel(spy_returns=spy)
    r = resid.residualize(strategy, panel)
    assert abs(r.alpha) < 0.0001  # ≈ zero
    assert abs(r.coefficients["SPY"] - 0.5) < 0.01
    # Alpha t-stat should be tiny — no alpha → no pass.
    assert not r.alpha_passes_gate


def test_residualize_passes_when_alpha_significant():
    """Strategy = 0.001 + 0.5 · SPY + ε with small ε → significant alpha."""
    rng = np.random.default_rng(0)
    n = 2000
    idx = pd.date_range("2010-01-01", periods=n, freq="B")
    spy = pd.Series(rng.normal(0.0, 0.012, n), index=idx)
    epsilon = pd.Series(rng.normal(0.0, 0.002, n), index=idx)
    strategy = 0.0008 + 0.5 * spy + epsilon   # ~20% annual alpha
    panel = resid.build_factor_panel(spy_returns=spy)
    r = resid.residualize(strategy, panel)
    assert r.alpha > 0.0
    assert abs(r.alpha_t_stat) > 1.96
    assert r.alpha_passes_gate


def test_residualize_negative_alpha_fails_gate_even_if_significant():
    rng = np.random.default_rng(0)
    n = 2000
    idx = pd.date_range("2010-01-01", periods=n, freq="B")
    spy = pd.Series(rng.normal(0.0, 0.012, n), index=idx)
    strategy = -0.0008 + 0.5 * spy + 0.002 * rng.normal(0, 1, n)
    strategy = pd.Series(strategy.to_numpy(), index=idx)
    panel = resid.build_factor_panel(spy_returns=spy)
    r = resid.residualize(strategy, panel)
    # alpha is significantly negative — gate requires alpha > 0 AND |t| > 1.96.
    assert r.alpha < 0
    assert not r.alpha_passes_gate


def test_residualize_provisional_when_factor_missing():
    """If only SPY is provided, result is provisional with 1/4 factors."""
    rng = np.random.default_rng(0)
    n = 500
    idx = pd.date_range("2010-01-01", periods=n, freq="B")
    spy = pd.Series(rng.normal(0.0, 0.012, n), index=idx)
    panel = resid.build_factor_panel(spy_returns=spy)
    r = resid.residualize(spy, panel)
    assert r.provisional
    assert r.factor_availability.n_factors == 1
    assert "DeltaVIX" in r.factor_availability.missing


def test_residualize_insufficient_observations_returns_safe_default():
    idx = pd.date_range("2020-01-01", periods=10, freq="B")
    r_strat = pd.Series(np.zeros(10), index=idx)
    panel = resid.build_factor_panel(spy_returns=pd.Series(np.zeros(10), index=idx))
    r = resid.residualize(r_strat, panel)
    assert not r.alpha_passes_gate
    assert r.note == "insufficient overlapping observations (<30)"


def test_residualize_with_all_four_factors():
    rng = np.random.default_rng(0)
    n = 500
    idx = pd.date_range("2018-01-02", periods=n, freq="B")
    spy = pd.Series(rng.normal(0.0005, 0.012, n), index=idx)
    dvix = pd.Series(rng.normal(0.0, 0.02, n), index=idx)
    streversal = pd.Series(rng.normal(0.0, 0.005, n), index=idx)
    carry = pd.Series(rng.normal(0.0, 0.001, n), index=idx)
    # Strategy with 4-factor structure + 0.0005 alpha + noise.
    strat_ret = (0.0005 + 0.3 * spy - 0.2 * dvix + 0.1 * streversal
                 + 0.05 * carry + rng.normal(0, 0.002, n))
    strategy = pd.Series(strat_ret, index=idx)
    panel = resid.build_factor_panel(spy_returns=spy, delta_vix=dvix,
                                      st_reversal=streversal, carry_change=carry)
    r = resid.residualize(strategy, panel)
    assert not r.provisional
    assert r.factor_availability.n_factors == 4
    assert "SPY" in r.coefficients
    # alpha should be around 0.0005 — t-stat should clear.
    assert r.alpha > 0
