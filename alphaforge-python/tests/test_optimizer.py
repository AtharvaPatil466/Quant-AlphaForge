"""Tests for the mean-variance portfolio optimizer."""

import math

import numpy as np
import pytest

from optimizer.mean_variance import (
    OptimizeConfig,
    OptimizeResult,
    _estimate_covariance,
    _estimate_expected_returns,
    _optimize_weights,
    optimize_portfolio,
)
from data.synthetic import generate_dataset
from backtest.engine import _compute_factor_scores_js


@pytest.fixture
def dataset():
    return generate_dataset("Technology", 252, 42)


@pytest.fixture
def tickers(dataset):
    return list(dataset.keys())


@pytest.fixture
def scores(dataset):
    return _compute_factor_scores_js(dataset, 252)


# ── Expected Returns ────────────────────────────────────────────────────────

class TestExpectedReturns:
    def test_shape(self, dataset, scores, tickers):
        mu = _estimate_expected_returns(dataset, scores, tickers)
        assert mu.shape == (len(tickers),)

    def test_finite(self, dataset, scores, tickers):
        mu = _estimate_expected_returns(dataset, scores, tickers)
        assert np.all(np.isfinite(mu))

    def test_shrinkage_zero_is_historical(self, dataset, scores, tickers):
        mu = _estimate_expected_returns(dataset, scores, tickers, shrinkage=0.0)
        # With shrinkage=0, result should be pure historical mean return
        for i, ticker in enumerate(tickers):
            rets = dataset[ticker].returns[1:]
            expected = float(np.mean(rets)) * 252
            assert abs(mu[i] - expected) < 1e-6

    def test_shrinkage_one_is_factor(self, dataset, scores, tickers):
        mu = _estimate_expected_returns(dataset, scores, tickers, shrinkage=1.0)
        # With shrinkage=1, result should be pure factor signal
        for i, ticker in enumerate(tickers):
            composite = scores.get(ticker, {}).get("_composite", 0.0)
            expected = composite / 100.0 * 0.30
            assert abs(mu[i] - expected) < 1e-6


# ── Covariance Matrix ──────────────────────────────────────────────────────

class TestCovariance:
    def test_shape(self, dataset, tickers):
        cov = _estimate_covariance(dataset, tickers)
        n = len(tickers)
        assert cov.shape == (n, n)

    def test_symmetric(self, dataset, tickers):
        cov = _estimate_covariance(dataset, tickers)
        assert np.allclose(cov, cov.T)

    def test_positive_semi_definite(self, dataset, tickers):
        cov = _estimate_covariance(dataset, tickers)
        eigenvalues = np.linalg.eigvalsh(cov)
        assert np.all(eigenvalues >= -1e-10)

    def test_diagonal_positive(self, dataset, tickers):
        cov = _estimate_covariance(dataset, tickers)
        assert np.all(np.diag(cov) > 0)

    def test_high_shrinkage_near_diagonal(self, dataset, tickers):
        cov = _estimate_covariance(dataset, tickers, shrinkage=0.99)
        # Off-diagonal elements should be near zero
        n = len(tickers)
        for i in range(n):
            for j in range(n):
                if i != j:
                    assert abs(cov[i, j]) < abs(cov[i, i])


# ── Weight Optimization ────────────────────────────────────────────────────

class TestOptimizeWeights:
    def _simple_inputs(self):
        mu = np.array([0.10, 0.05, -0.02]) / 252  # daily
        cov = np.array([
            [0.04, 0.01, 0.005],
            [0.01, 0.03, 0.008],
            [0.005, 0.008, 0.05],
        ]) / 252
        return mu, cov

    def test_long_only_no_negative(self):
        mu, cov = self._simple_inputs()
        config = OptimizeConfig(mode="long_only", max_weight=0.50)
        w = _optimize_weights(mu, cov, config)
        assert np.all(w >= -1e-6)

    def test_market_neutral_sums_to_zero(self):
        mu, cov = self._simple_inputs()
        config = OptimizeConfig(mode="market_neutral", max_weight=0.50, min_weight=-0.50)
        w = _optimize_weights(mu, cov, config)
        assert abs(np.sum(w)) < 1e-4

    def test_leverage_constraint(self):
        mu, cov = self._simple_inputs()
        config = OptimizeConfig(max_gross_leverage=1.0, max_weight=0.50, min_weight=-0.50)
        w = _optimize_weights(mu, cov, config)
        assert np.sum(np.abs(w)) <= 1.0 + 1e-4

    def test_weight_bounds_respected(self):
        mu, cov = self._simple_inputs()
        config = OptimizeConfig(max_weight=0.30, min_weight=-0.30)
        w = _optimize_weights(mu, cov, config)
        assert np.all(w <= 0.30 + 1e-6)
        assert np.all(w >= -0.30 - 1e-6)

    def test_high_risk_aversion_smaller_positions(self):
        mu, cov = self._simple_inputs()
        w_low = _optimize_weights(mu, cov, OptimizeConfig(risk_aversion=0.5))
        w_high = _optimize_weights(mu, cov, OptimizeConfig(risk_aversion=10.0))
        assert np.sum(np.abs(w_high)) <= np.sum(np.abs(w_low)) + 1e-4

    def test_max_positions_enforced(self):
        mu, cov = self._simple_inputs()
        config = OptimizeConfig(max_positions=2, max_weight=0.50, min_weight=-0.50)
        w = _optimize_weights(mu, cov, config)
        assert np.sum(np.abs(w) > 1e-6) <= 2


# ── Full Pipeline ──────────────────────────────────────────────────────────

class TestOptimizePortfolio:
    def test_returns_result(self):
        config = OptimizeConfig(sector="Technology", lookback=252)
        result = optimize_portfolio(config)
        assert isinstance(result, OptimizeResult)
        assert result.error is None

    def test_weights_sum_reasonable(self):
        config = OptimizeConfig(sector="Technology", lookback=252)
        result = optimize_portfolio(config)
        assert result.gross_leverage <= config.max_gross_leverage + 0.01

    def test_long_only_no_shorts(self):
        config = OptimizeConfig(sector="Technology", lookback=252, mode="long_only")
        result = optimize_portfolio(config)
        assert result.n_short == 0
        assert all(w >= 0 for w in result.weights.values())

    def test_market_neutral(self):
        config = OptimizeConfig(
            sector="Technology", lookback=252, mode="market_neutral",
            max_weight=0.30, min_weight=-0.30, risk_aversion=0.5,
        )
        result = optimize_portfolio(config)
        assert abs(result.net_exposure) < 0.01

    def test_expected_metrics_finite(self):
        config = OptimizeConfig(sector="Technology", lookback=252)
        result = optimize_portfolio(config)
        assert math.isfinite(result.expected_return)
        assert math.isfinite(result.expected_vol)
        assert math.isfinite(result.expected_sharpe)

    def test_factor_exposures_present(self):
        config = OptimizeConfig(sector="Technology", lookback=252)
        result = optimize_portfolio(config)
        assert len(result.factor_exposures) == 5  # 5 JS factors

    def test_covariance_matrix_shape(self):
        config = OptimizeConfig(sector="Technology", lookback=252)
        result = optimize_portfolio(config)
        n = len(result.tickers)
        assert len(result.covariance_matrix) == n
        assert len(result.covariance_matrix[0]) == n

    def test_all_sectors(self):
        for sector in ["Technology", "Finance", "Healthcare", "Energy", "Consumer"]:
            config = OptimizeConfig(sector=sector, lookback=252)
            result = optimize_portfolio(config)
            assert result.error is None
            assert len(result.weights) > 0

    def test_empty_universe(self):
        config = OptimizeConfig(sector="NonexistentSector", lookback=252)
        result = optimize_portfolio(config)
        assert result.error is not None

    def test_short_lookback(self):
        config = OptimizeConfig(sector="Technology", lookback=63)
        result = optimize_portfolio(config)
        assert result.error is None

    def test_high_risk_aversion(self):
        low = optimize_portfolio(OptimizeConfig(risk_aversion=0.1))
        high = optimize_portfolio(OptimizeConfig(risk_aversion=50.0))
        assert high.gross_leverage <= low.gross_leverage + 0.01
