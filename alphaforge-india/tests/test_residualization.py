"""Tests for gauntlet/residualization.py — Four-factor model."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from gauntlet.residualization import (
    ResidualizeResult,
    build_factor_matrix,
    compute_amihud_illiquidity,
    compute_liquidity_factor,
    compute_market_factor,
    compute_smb_factor,
    residualize,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def synthetic_data():
    """100 stocks, 500 days of synthetic OHLCV data."""
    rng = np.random.default_rng(42)
    n_days, n_stocks = 500, 100
    dates = pd.bdate_range("2010-01-01", periods=n_days)
    symbols = [f"SYM{i:03d}" for i in range(n_stocks)]

    rets = rng.normal(0.0005, 0.02, size=(n_days, n_stocks))
    close = pd.DataFrame(
        100 * np.exp(np.cumsum(rets, axis=0)),
        index=dates, columns=symbols,
    )
    volume = pd.DataFrame(
        rng.integers(10000, 1000000, size=(n_days, n_stocks)),
        index=dates, columns=symbols, dtype=float,
    )
    market_cap = close * volume * 0.01  # proxy
    return close, volume, market_cap


# ---------------------------------------------------------------------------
# Amihud illiquidity
# ---------------------------------------------------------------------------

class TestAmihudIlliquidity:
    def test_shape(self, synthetic_data):
        close, volume, _ = synthetic_data
        amihud = compute_amihud_illiquidity(close, volume, window=21)
        assert amihud.shape == close.shape

    def test_non_negative(self, synthetic_data):
        close, volume, _ = synthetic_data
        amihud = compute_amihud_illiquidity(close, volume)
        valid = amihud.dropna(how="all").iloc[25:]
        assert (valid.fillna(0) >= 0).all().all()

    def test_zero_volume_produces_nan(self):
        dates = pd.bdate_range("2010-01-01", periods=30)
        close = pd.DataFrame({"A": np.ones(30) * 100}, index=dates)
        volume = pd.DataFrame({"A": np.zeros(30)}, index=dates)
        amihud = compute_amihud_illiquidity(close, volume, window=5)
        assert amihud["A"].isna().all()


# ---------------------------------------------------------------------------
# Factor construction
# ---------------------------------------------------------------------------

class TestMarketFactor:
    def test_shape(self, synthetic_data):
        close, _, _ = synthetic_data
        mkt = compute_market_factor(close)
        assert len(mkt) == len(close)

    def test_with_risk_free(self, synthetic_data):
        close, _, _ = synthetic_data
        rf = pd.Series(0.0001, index=close.index)
        mkt = compute_market_factor(close, rf)
        mkt_no_rf = compute_market_factor(close)
        # Should be lower by ~rf
        diff = (mkt_no_rf - mkt).dropna()
        assert abs(diff.mean() - 0.0001) < 0.001


class TestSMBFactor:
    def test_shape(self, synthetic_data):
        close, _, market_cap = synthetic_data
        smb = compute_smb_factor(close, market_cap)
        assert len(smb) == len(close)

    def test_near_zero_mean(self, synthetic_data):
        """SMB should have mean close to zero for random data."""
        close, _, market_cap = synthetic_data
        smb = compute_smb_factor(close, market_cap)
        assert abs(smb.mean()) < 0.01


class TestLiquidityFactor:
    def test_shape(self, synthetic_data):
        close, volume, _ = synthetic_data
        liq = compute_liquidity_factor(close, volume)
        assert len(liq) == len(close)


class TestBuildFactorMatrix:
    def test_columns(self, synthetic_data):
        close, volume, market_cap = synthetic_data
        fm = build_factor_matrix(close, volume, market_cap)
        assert set(fm.columns) == {"MKT", "SMB", "LIQ", "const"}
        assert (fm["const"] == 1.0).all()

    def test_without_market_cap(self, synthetic_data):
        close, volume, _ = synthetic_data
        fm = build_factor_matrix(close, volume)  # no market_cap
        assert "SMB" in fm.columns


# ---------------------------------------------------------------------------
# Residualization
# ---------------------------------------------------------------------------

class TestResidualize:
    def test_pure_alpha(self, synthetic_data):
        """Strategy with pure alpha (uncorrelated to factors) should pass."""
        close, volume, market_cap = synthetic_data
        fm = build_factor_matrix(close, volume, market_cap)

        # Generate strategy returns uncorrelated to factors
        rng = np.random.default_rng(99)
        strat = pd.Series(
            rng.normal(0.002, 0.01, len(close)),
            index=close.index,
        )
        result = residualize(strat, fm)
        assert isinstance(result, ResidualizeResult)
        assert result.n_obs > 100
        # With mean=0.002 and std=0.01 over 500 days, alpha should be significant
        assert result.alpha > 0
        assert result.passed is True

    def test_factor_exposure_only(self, synthetic_data):
        """Strategy that is pure market beta should fail alpha test."""
        close, volume, market_cap = synthetic_data
        fm = build_factor_matrix(close, volume, market_cap)

        # Strategy = market factor + noise
        strat = fm["MKT"] * 1.5 + pd.Series(
            np.random.default_rng(1).normal(0, 0.001, len(close)),
            index=close.index,
        )
        result = residualize(strat, fm)
        # Alpha should be near zero and not significant
        assert abs(result.alpha) < 0.005

    def test_insufficient_data(self):
        """Should handle very short series gracefully."""
        fm = pd.DataFrame({
            "MKT": [0.01, -0.01],
            "SMB": [0.005, -0.005],
            "LIQ": [0.003, -0.003],
            "const": [1.0, 1.0],
        })
        strat = pd.Series([0.02, -0.02])
        result = residualize(strat, fm)
        assert result.passed is False
        assert result.n_obs <= 2

    def test_summary_string(self, synthetic_data):
        close, volume, market_cap = synthetic_data
        fm = build_factor_matrix(close, volume, market_cap)
        strat = pd.Series(
            np.random.default_rng(99).normal(0.002, 0.01, len(close)),
            index=close.index,
        )
        result = residualize(strat, fm)
        s = result.summary()
        assert "α=" in s
        assert "PASS" in s or "FAIL" in s
        assert "R²=" in s

    def test_betas_present(self, synthetic_data):
        close, volume, market_cap = synthetic_data
        fm = build_factor_matrix(close, volume, market_cap)
        strat = pd.Series(
            np.random.default_rng(99).normal(0.002, 0.01, len(close)),
            index=close.index,
        )
        result = residualize(strat, fm)
        assert "MKT" in result.betas
        assert "SMB" in result.betas
        assert "LIQ" in result.betas
