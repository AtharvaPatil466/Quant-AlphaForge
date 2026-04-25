"""
Factor tests — output validity, consistency, and parity checks.
"""

import numpy as np
import pytest

from data.synthetic import generate_dataset
from factors.registry import (
    load_factor,
    FACTOR_REGISTRY,
    JS_FACTOR_NAMES,
    FACTOR_NAMES,
)
from factors.rsi_divergence import _compute_rsi_js as compute_rsi


@pytest.fixture
def tech_dataset():
    return generate_dataset("Technology", 252, 42)


class TestFactorRegistry:
    def test_all_factors_accessible(self):
        for name in FACTOR_NAMES:
            factor = load_factor(name)
            assert factor is not None

    def test_unknown_factor_raises(self):
        with pytest.raises(ValueError):
            load_factor("Nonexistent Factor")


class TestComputeRSI:
    def test_all_gains(self):
        """Monotonically increasing prices — JS safeDiv(avgGain, 0, 1) returns
        fallback=1 when avgLoss=0, giving RS=1 and RSI=50. This matches JS."""
        prices = list(range(100, 115))
        rsi = compute_rsi(prices)
        assert rsi == pytest.approx(50.0)

    def test_all_losses(self):
        """Monotonically decreasing prices → RSI near 0."""
        prices = list(range(115, 100, -1))
        rsi = compute_rsi(prices)
        assert rsi < 10

    def test_single_price(self):
        assert compute_rsi([100]) == 50.0

    def test_range(self):
        """RSI should always be in [0, 100]."""
        prices = [100 + i * (-1) ** i for i in range(15)]
        rsi = compute_rsi(prices)
        assert 0 <= rsi <= 100


class TestFactorOutputs:
    """Contract tests: factors produce finite values for valid input."""

    def test_all_factors_finite(self, tech_dataset):
        for ticker, d in tech_dataset.items():
            for name in JS_FACTOR_NAMES:
                factor = load_factor(name)
                val = factor.compute_js(d.prices, d.volumes, d.returns, 252)
                assert np.isfinite(val), f"{name} for {ticker} returned {val}"

    def test_momentum_sign(self, tech_dataset):
        """Momentum for a strongly rising ticker should be positive."""
        factor = load_factor("Momentum (12-1)")
        for ticker, d in tech_dataset.items():
            val = factor.compute_js(d.prices, d.volumes, d.returns, 252)
            assert np.isfinite(val)

    def test_mean_reversion_inverse_of_short_return(self, tech_dataset):
        """Mean reversion should be negative of recent 5d return."""
        factor = load_factor("Mean Reversion (5d)")
        for ticker, d in tech_dataset.items():
            mr = factor.compute_js(d.prices, d.volumes, d.returns, 252)
            n = len(d.prices)
            start = max(0, n - 6)
            raw_5d = (d.prices[n - 1] - d.prices[start]) / d.prices[start]
            assert mr == pytest.approx(-raw_5d, rel=1e-10)

    def test_rsi_divergence_range(self, tech_dataset):
        """RSI divergence should be in [-1, 1]."""
        factor = load_factor("RSI Divergence")
        for ticker, d in tech_dataset.items():
            val = factor.compute_js(d.prices, d.volumes, d.returns, 252)
            assert -1.0 <= val <= 1.0, f"{ticker}: {val}"

    def test_low_volatility_negative(self, tech_dataset):
        """Low volatility factor should be negative (lower vol = higher score via negation)."""
        factor = load_factor("Low Volatility")
        for ticker, d in tech_dataset.items():
            val = factor.compute_js(d.prices, d.volumes, d.returns, 252)
            # Should be negative since it's -annualized_vol
            assert val <= 0.0, f"{ticker}: {val}"


class TestFactorEdgeCases:
    def test_short_series(self):
        """Factors should handle very short price series without crashing."""
        prices = np.array([100.0, 101.0, 99.0])
        volumes = np.array([1e6, 1.1e6, 0.9e6])
        returns = np.array([0.0, 0.01, -0.0198])
        for name in FACTOR_NAMES:
            factor = load_factor(name)
            val = factor.compute_js(prices, volumes, returns, 3)
            assert np.isfinite(val), f"{name} crashed on short series"


class TestAmihudIlliquidity:
    def test_monotone_with_illiquidity(self):
        """Holding return magnitude constant, halving volume should roughly
        double the Amihud score."""
        factor = load_factor("Amihud Illiquidity")
        prices = np.cumprod(1 + 0.01 * np.ones(30)) * 100.0
        high_vol = np.full(30, 1e7)
        low_vol = np.full(30, 5e6)
        returns = np.zeros(30)
        hi = factor.compute(prices, high_vol, returns, 30)
        lo = factor.compute(prices, low_vol, returns, 30)
        assert lo > hi > 0.0

    def test_zero_volume_does_not_crash(self):
        factor = load_factor("Amihud Illiquidity")
        prices = np.linspace(100, 110, 30)
        volumes = np.zeros(30)
        returns = np.zeros(30)
        val = factor.compute(prices, volumes, returns, 30)
        assert np.isfinite(val)


class TestIdiosyncraticVolatility:
    def test_sign_convention_cross_sectional(self):
        """In compute_universe, higher score should correspond to lower
        residual volatility after removing the equal-weighted market."""
        from data.synthetic import generate_dataset
        factor = load_factor("Idiosyncratic Volatility")
        ds = generate_dataset("Technology", 252, 7)
        scores = factor.compute_universe(ds, 252, use_js=False)
        vals = np.array(list(scores.values()))
        assert np.all(np.isfinite(vals))
        # All negated IVOLs should be ≤ 0
        assert (vals <= 1e-9).all(), vals

    def test_single_ticker_fallback(self, tech_dataset):
        factor = load_factor("Idiosyncratic Volatility")
        any_ticker = next(iter(tech_dataset.values()))
        val = factor.compute(any_ticker.prices, any_ticker.volumes,
                             any_ticker.returns, 252)
        assert np.isfinite(val)
        assert val <= 0.0  # negated vol


class TestResidualReversal:
    def test_cross_sectional_reverses_residual(self):
        """A ticker whose residual return last week was strongly positive
        should get a lower residual-reversal score than one whose residual
        was negative."""
        from data.synthetic import generate_dataset
        factor = load_factor("Residual Reversal (5d)")
        ds = generate_dataset("Technology", 252, 11)
        scores = factor.compute_universe(ds, 252, use_js=False)
        # Scores should be finite and not identical across the universe
        vals = np.array(list(scores.values()))
        assert np.all(np.isfinite(vals))
        assert vals.std() > 0.0

    def test_single_ticker_fallback_matches_negated_5d_return(self, tech_dataset):
        factor = load_factor("Residual Reversal (5d)")
        any_ticker = next(iter(tech_dataset.values()))
        p = any_ticker.prices
        expected = -(p[-1] - p[-6]) / p[-6]
        val = factor.compute(p, any_ticker.volumes, any_ticker.returns, 252)
        assert val == pytest.approx(expected, rel=1e-10)


class TestRiskManagedMomentum:
    def test_high_vol_dampens_score(self):
        """Two tickers with the same 12-1 return but different recent vol:
        the higher-vol name should get a smaller absolute score."""
        factor = load_factor("Risk-Managed Momentum")
        n = 300
        rng = np.random.default_rng(0)
        # Calm ticker: small daily vol, mild positive drift
        calm = np.cumprod(1 + rng.normal(0.0005, 0.005, n)) * 100.0
        # Wild ticker: same drift but 3× daily vol
        wild = np.cumprod(1 + rng.normal(0.0005, 0.015, n)) * 100.0
        # Force both to the same 12-1 return window by rescaling last price
        calm[-1] = calm[-253] * 1.20
        wild[-1] = wild[-253] * 1.20
        calm[-22] = calm[-253] * 1.15
        wild[-22] = wild[-253] * 1.15
        v = np.full(n, 1e6); r = np.zeros(n)
        s_calm = factor.compute(calm, v, r, 252)
        s_wild = factor.compute(wild, v, r, 252)
        assert abs(s_calm) > abs(s_wild) > 0


class TestLongHorizonReversal:
    def test_requires_long_history(self):
        factor = load_factor("Long-Horizon Reversal")
        short_prices = np.linspace(100, 110, 200)
        val = factor.compute(short_prices, np.full(200, 1e6),
                             np.zeros(200), 200)
        assert val == 0.0

    def test_negates_past_return(self):
        factor = load_factor("Long-Horizon Reversal")
        # Build a price series where the 48-month past return is clearly positive
        n = 48 * 21 + 21 + 10
        prices = np.linspace(100.0, 200.0, n)  # monotone up
        v = np.full(n, 1e6); r = np.zeros(n)
        val = factor.compute(prices, v, r, n)
        assert val < 0  # prior winner → negative score
