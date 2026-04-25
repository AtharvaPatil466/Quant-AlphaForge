"""
Factor attribution tests — OLS decomposition correctness.
"""

import numpy as np
import pytest

from backtest.attribution import attribute_returns, AttributionResult


class TestAttribution:
    def test_basic_attribution(self):
        rng = np.random.RandomState(42)
        T = 252
        # Create factor returns
        f1 = rng.normal(0, 0.01, T)
        f2 = rng.normal(0, 0.01, T)
        # Portfolio = 0.5*f1 + 0.3*f2 + noise
        port = 0.5 * f1 + 0.3 * f2 + rng.normal(0, 0.002, T)

        result = attribute_returns(port, {"factor1": f1, "factor2": f2})
        assert isinstance(result, AttributionResult)
        assert result.factor_exposures["factor1"] == pytest.approx(0.5, abs=0.1)
        assert result.factor_exposures["factor2"] == pytest.approx(0.3, abs=0.1)
        assert result.r_squared > 0.8

    def test_no_factors(self):
        port = np.random.RandomState(42).normal(0, 0.01, 100)
        result = attribute_returns(port, {})
        assert result.r_squared == 0.0

    def test_short_series(self):
        port = np.array([0.01, 0.02])
        f1 = np.array([0.005, 0.01])
        result = attribute_returns(port, {"f1": f1})
        assert result.r_squared == 0.0

    def test_r_squared_bounded(self):
        rng = np.random.RandomState(42)
        T = 252
        f1 = rng.normal(0, 0.01, T)
        port = f1 + rng.normal(0, 0.005, T)
        result = attribute_returns(port, {"f1": f1})
        assert 0.0 <= result.r_squared <= 1.0
