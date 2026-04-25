"""Tests for enhanced compute() methods (plan formulas, not JS parity)."""

import numpy as np
import pytest

from data.synthetic import generate_dataset
from factors.registry import load_factor, FACTOR_NAMES


@pytest.fixture
def tech_dataset():
    return generate_dataset("Technology", 252, 42)


class TestEnhancedFactors:
    def test_all_compute_finite(self, tech_dataset):
        """Enhanced compute() produces finite values for all factors."""
        for ticker, d in tech_dataset.items():
            for name in FACTOR_NAMES:
                factor = load_factor(name)
                val = factor.compute(d.prices, d.volumes, d.returns, 252)
                assert np.isfinite(val), f"{name} compute() for {ticker} = {val}"

    def test_momentum_enhanced(self, tech_dataset):
        """Enhanced momentum uses 12m-1m formula."""
        factor = load_factor("Momentum (12-1)")
        for ticker, d in tech_dataset.items():
            val = factor.compute(d.prices, d.volumes, d.returns, 252)
            assert np.isfinite(val)

    def test_volume_surge_enhanced(self, tech_dataset):
        factor = load_factor("Volume Surge")
        for ticker, d in tech_dataset.items():
            val = factor.compute(d.prices, d.volumes, d.returns, 252)
            assert np.isfinite(val)

    def test_rsi_divergence_enhanced(self, tech_dataset):
        factor = load_factor("RSI Divergence")
        for ticker, d in tech_dataset.items():
            val = factor.compute(d.prices, d.volumes, d.returns, 252)
            assert np.isfinite(val)

    def test_earnings_drift_enhanced(self, tech_dataset):
        factor = load_factor("Earnings Drift")
        for ticker, d in tech_dataset.items():
            val = factor.compute(d.prices, d.volumes, d.returns, 252)
            assert np.isfinite(val)

    def test_compute_universe(self, tech_dataset):
        """compute_universe returns dict of ticker -> score."""
        factor = load_factor("Momentum (12-1)")
        raw = factor.compute_universe(tech_dataset, 252, use_js=False)
        assert len(raw) == len(tech_dataset)
        for v in raw.values():
            assert np.isfinite(v)

    def test_score_universe(self, tech_dataset):
        """score_universe returns z-scored values."""
        factor = load_factor("Momentum (12-1)")
        scored = factor.score_universe(tech_dataset, 252)
        assert len(scored) == len(tech_dataset)
        vals = list(scored.values())
        # z-scores should have mean ~0
        assert abs(np.mean(vals)) < 0.5
