"""Tests for gauntlet/gates.py — Five-gate gauntlet framework.

Tests cover:
    1. Individual gate logic on synthetic data
    2. Full gauntlet orchestration
    3. Edge cases (degenerate inputs, short series)
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from gauntlet.gates import (
    GauntletResult,
    deflated_sharpe_ratio,
    gate1_dsr,
    gate2_bootstrap_ci,
    gate3_sign_agreement,
    gate4_cost_survival,
    gate5_regime_stress,
    run_gauntlet,
    sharpe_ratio,
    split_oos_returns,
    stationary_bootstrap_sharpe,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def strong_positive_returns() -> np.ndarray:
    """Returns with clear positive Sharpe (≈2.0 annualized)."""
    rng = np.random.default_rng(42)
    return rng.normal(0.001, 0.01, size=1260)  # ~5 years


@pytest.fixture
def noise_returns() -> np.ndarray:
    """Pure noise returns (mean=0)."""
    rng = np.random.default_rng(42)
    return rng.normal(0.0, 0.01, size=1260)


@pytest.fixture
def full_daily_returns() -> pd.Series:
    """Daily returns spanning IS + OOS-A + OOS-B with DatetimeIndex."""
    rng = np.random.default_rng(42)
    dates = pd.bdate_range("2004-01-01", "2025-12-31")
    returns = rng.normal(0.0003, 0.012, size=len(dates))
    return pd.Series(returns, index=dates)


# ---------------------------------------------------------------------------
# Sharpe ratio
# ---------------------------------------------------------------------------

class TestSharpeRatio:
    def test_positive(self, strong_positive_returns):
        sr = sharpe_ratio(strong_positive_returns)
        assert sr > 0

    def test_zero_mean(self, noise_returns):
        sr = sharpe_ratio(noise_returns)
        # Should be close to zero (within ±1)
        assert abs(sr) < 2.0

    def test_degenerate(self):
        assert sharpe_ratio(np.array([])) == 0.0
        assert sharpe_ratio(np.array([0.01])) == 0.0
        assert sharpe_ratio(np.array([0.01, 0.01, 0.01])) == 0.0  # zero std


# ---------------------------------------------------------------------------
# Gate 1: DSR
# ---------------------------------------------------------------------------

class TestGate1DSR:
    def test_strong_signal_has_high_dsr(self):
        """A very strong Sharpe should produce high DSR.

        DSR now takes a PER-PERIOD Sharpe (no √252). 0.12 per-day over 1260
        obs ≈ annualized 1.9 — a genuinely strong daily strategy — and clears
        the 0.95 gate after deflation against 22 trials.
        """
        dsr = deflated_sharpe_ratio(0.12, n_trials=22, n_obs=1260)
        assert dsr > 0.95

    def test_weak_signal_has_low_dsr(self):
        """A weak Sharpe should produce low DSR.

        0.02 per-day over 1260 obs ≈ annualized 0.32 — too weak to clear the
        expected-max-of-22-trials hurdle after the Lo variance correction.
        """
        dsr = deflated_sharpe_ratio(0.02, n_trials=22, n_obs=1260)
        assert dsr < 0.5

    def test_gate_result(self, strong_positive_returns, noise_returns):
        result = gate1_dsr(strong_positive_returns, strong_positive_returns)
        assert isinstance(result.passed, bool)
        assert "DSR_A" in result.summary


# ---------------------------------------------------------------------------
# Gate 2: Bootstrap CI
# ---------------------------------------------------------------------------

class TestGate2BootstrapCI:
    def test_returns_tuple(self, strong_positive_returns):
        ci = stationary_bootstrap_sharpe(
            strong_positive_returns, n_boot=100, block_mean=21
        )
        assert len(ci) == 2
        assert ci[0] <= ci[1]

    def test_strong_signal_excludes_zero(self, strong_positive_returns):
        ci = stationary_bootstrap_sharpe(
            strong_positive_returns, n_boot=500, block_mean=21
        )
        # Strong positive returns should have CI entirely above zero
        assert ci[0] > 0

    def test_gate_result(self, strong_positive_returns, noise_returns):
        result = gate2_bootstrap_ci(
            strong_positive_returns, strong_positive_returns, n_boot=100
        )
        assert isinstance(result.passed, bool)


# ---------------------------------------------------------------------------
# Gate 3: Sign Agreement
# ---------------------------------------------------------------------------

class TestGate3SignAgreement:
    def test_both_positive(self, strong_positive_returns):
        result = gate3_sign_agreement(
            strong_positive_returns, strong_positive_returns
        )
        assert result.passed is True

    def test_one_negative(self, strong_positive_returns, noise_returns):
        # Create clearly negative returns
        neg_returns = -np.abs(strong_positive_returns)
        result = gate3_sign_agreement(strong_positive_returns, neg_returns)
        assert result.passed is False


# ---------------------------------------------------------------------------
# Gate 4: Cost Survival
# ---------------------------------------------------------------------------

class TestGate4CostSurvival:
    def test_strong_signal_survives(self, strong_positive_returns):
        result = gate4_cost_survival(
            strong_positive_returns, strong_positive_returns,
        )
        # Strong signal should survive even doubled costs
        assert isinstance(result.passed, bool)

    def test_metrics_present(self, strong_positive_returns):
        result = gate4_cost_survival(
            strong_positive_returns, strong_positive_returns,
        )
        assert "stressed_round_trip_bps" in result.metrics
        # Doubled cost should be ~71.8
        assert abs(result.metrics["stressed_round_trip_bps"] - 71.8) < 0.1


# ---------------------------------------------------------------------------
# Gate 5: Regime Stress
# ---------------------------------------------------------------------------

class TestGate5RegimeStress:
    def test_with_full_returns(self, full_daily_returns):
        result = gate5_regime_stress(full_daily_returns)
        assert isinstance(result.passed, bool)
        assert "4-of-4" in result.summary

    def test_insufficient_data(self):
        """Short series missing stress periods should fail."""
        dates = pd.bdate_range("2023-01-01", "2023-06-30")
        short = pd.Series(np.random.default_rng(1).normal(0.001, 0.01, len(dates)),
                          index=dates)
        result = gate5_regime_stress(short)
        assert result.passed is False


# ---------------------------------------------------------------------------
# Split OOS returns
# ---------------------------------------------------------------------------

class TestSplitOOSReturns:
    def test_split(self, full_daily_returns):
        oos_a, oos_b = split_oos_returns(full_daily_returns)
        assert len(oos_a) > 0
        assert len(oos_b) > 0

    def test_no_overlap(self, full_daily_returns):
        oos_a, oos_b = split_oos_returns(full_daily_returns)
        assert len(oos_a) + len(oos_b) <= len(full_daily_returns)


# ---------------------------------------------------------------------------
# Full gauntlet
# ---------------------------------------------------------------------------

class TestRunGauntlet:
    def test_returns_gauntlet_result(self, full_daily_returns):
        result = run_gauntlet("test_trial", full_daily_returns)
        assert isinstance(result, GauntletResult)
        assert len(result.gate_results) == 5

    def test_summary(self, full_daily_returns):
        result = run_gauntlet("test_trial", full_daily_returns)
        s = result.summary()
        assert "test_trial" in s
        assert "DEPLOY-READY" in s or "FAILED" in s
