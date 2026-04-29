"""Tests for Phase 3 risk-model helpers."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.risk_model import (
    factor_replication_correlation,
    fit_factor_model,
    rolling_factor_residuals,
    rolling_factor_residuals_panel,
)


@pytest.fixture
def factor_fixture():
    rng = np.random.default_rng(42)
    idx = pd.bdate_range("2020-01-01", periods=400)
    factors = pd.DataFrame(
        {
            "SMB": rng.normal(0.0, 0.01, len(idx)),
            "HML": rng.normal(0.0, 0.012, len(idx)),
            "UMD": rng.normal(0.0, 0.011, len(idx)),
        },
        index=idx,
    )
    return idx, factors


class TestFitFactorModel:
    def test_recovers_known_betas(self, factor_fixture):
        idx, factors = factor_fixture
        rng = np.random.default_rng(7)
        y = 0.001 + 0.6 * factors["SMB"] - 0.4 * factors["HML"] + rng.normal(0.0, 0.002, len(idx))
        result = fit_factor_model(y.rename("asset"), factors[["SMB", "HML"]])
        assert result.alpha == pytest.approx(0.001, abs=5e-4)
        assert result.betas["SMB"] == pytest.approx(0.6, abs=0.05)
        assert result.betas["HML"] == pytest.approx(-0.4, abs=0.05)
        assert result.r_squared > 0.9


class TestRollingResiduals:
    def test_self_residualization_drives_loading_near_zero(self, factor_fixture):
        idx, factors = factor_fixture
        rng = np.random.default_rng(11)
        asset = 0.8 * factors["SMB"] + rng.normal(0.0, 0.003, len(idx))
        resid = rolling_factor_residuals(asset.rename("asset"), factors[["SMB"]], window=126, min_obs=100)
        post_warmup = resid.dropna()
        fit = fit_factor_model(post_warmup, factors.loc[post_warmup.index, ["SMB"]])
        assert abs(fit.betas["SMB"]) < 0.1

    def test_panel_wrapper_preserves_shape_and_warmup(self, factor_fixture):
        idx, factors = factor_fixture
        rng = np.random.default_rng(13)
        panel = pd.DataFrame(
            {
                "A": 0.5 * factors["SMB"] + rng.normal(0.0, 0.005, len(idx)),
                "B": -0.3 * factors["HML"] + rng.normal(0.0, 0.005, len(idx)),
            },
            index=idx,
        )
        resid = rolling_factor_residuals_panel(panel, factors[["SMB", "HML"]], window=63, min_obs=50)
        assert resid.shape == panel.shape
        assert resid.iloc[:50].isna().all().all()
        assert resid.iloc[-50:].notna().all().all()


class TestFactorReplicationCorrelation:
    def test_overlap_correlation_is_reported(self, factor_fixture):
        idx, factors = factor_fixture
        replica = pd.DataFrame(
            {
                "SMB": factors["SMB"] * 1.05,
                "HML": factors["HML"] * -1.0,
            },
            index=idx,
        )
        reference = pd.DataFrame(
            {
                "SMB": factors["SMB"],
                "HML": -factors["HML"],
                "UMD": factors["UMD"],
            },
            index=idx,
        )
        corr = factor_replication_correlation(replica, reference)
        assert corr.loc["SMB", "correlation"] > 0.99
        assert corr.loc["HML", "correlation"] > 0.99
