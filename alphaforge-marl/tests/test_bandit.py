"""Tests for the regime bandit system (Phase 4)."""

from __future__ import annotations

import numpy as np
import pytest

from bandit.regime_detector import RegimeDetector, extract_regime_features
from bandit.thompson_sampler import ThompsonSampler
from bandit.capital_allocator import CapitalAllocator


# ── Regime Detector ─────────────────────────────────────────────


class TestRegimeDetector:
    def test_unfitted_returns_zero(self):
        det = RegimeDetector(n_regimes=4)
        features = np.random.randn(4).astype(np.float32)
        regime = det.predict_single(features)
        assert regime == 0

    def test_fit_and_predict(self):
        det = RegimeDetector(n_regimes=3)
        # Create distinct clusters
        features = np.vstack([
            np.random.randn(20, 4) + np.array([0, 0, 0, 0]),
            np.random.randn(20, 4) + np.array([5, 5, 5, 5]),
            np.random.randn(20, 4) + np.array([-5, -5, -5, -5]),
        ]).astype(np.float32)
        det.fit(features)
        assert det.is_fitted

        labels = det.predict(features)
        assert labels.shape == (60,)
        assert set(labels).issubset({0, 1, 2})

    def test_predict_single(self):
        det = RegimeDetector(n_regimes=2)
        features = np.vstack([
            np.ones((30, 4)) * -1,
            np.ones((30, 4)) * 1,
        ]).astype(np.float32)
        det.fit(features)
        r = det.predict_single(np.array([-1, -1, -1, -1], dtype=np.float32))
        assert r in {0, 1}

    def test_extract_regime_features(self):
        n = 100
        returns = np.random.randn(n) * 0.01
        volumes = np.abs(np.random.randn(n)) * 1e6
        prices = 100 + np.cumsum(returns)
        features = extract_regime_features(returns, volumes, prices, window=21)
        assert features.ndim == 2
        assert features.shape[1] == 4
        assert features.shape[0] == n - 21
        assert np.all(np.isfinite(features))


# ── Thompson Sampler ────────────────────────────────────────────


class TestThompsonSampler:
    def test_register_and_select(self):
        sampler = ThompsonSampler(n_regimes=4)
        sampler.register_agent("a1")
        sampler.register_agent("a2")
        selected = sampler.select(0, ["a1", "a2"])
        assert selected in {"a1", "a2"}

    def test_update_positive(self):
        sampler = ThompsonSampler(n_regimes=2)
        sampler.register_agent("a1")
        sampler.update(0, "a1", reward=1.0)
        alpha, beta = sampler.get_posterior(0, "a1")
        assert alpha > 1.0  # Updated from prior

    def test_update_negative(self):
        sampler = ThompsonSampler(n_regimes=2)
        sampler.register_agent("a1")
        sampler.update(0, "a1", reward=-1.0)
        alpha, beta = sampler.get_posterior(0, "a1")
        assert beta > 1.0

    def test_expected_value(self):
        sampler = ThompsonSampler(n_regimes=1, prior_alpha=1.0, prior_beta=1.0)
        sampler.register_agent("a1")
        ev = sampler.expected_value(0, "a1")
        assert abs(ev - 0.5) < 0.01  # Uniform prior → 0.5

    def test_strong_agent_wins_more(self):
        """An agent with many successes should be selected more often."""
        sampler = ThompsonSampler(n_regimes=1)
        sampler.register_agent("good")
        sampler.register_agent("bad")
        for _ in range(50):
            sampler.update(0, "good", reward=2.0)
            sampler.update(0, "bad", reward=-1.0)

        # Sample 100 times, good agent should win majority
        counts = {"good": 0, "bad": 0}
        for _ in range(100):
            selected = sampler.select(0, ["good", "bad"])
            counts[selected] += 1
        assert counts["good"] > counts["bad"]


# ── Capital Allocator ───────────────────────────────────────────


class TestCapitalAllocator:
    def test_allocate_sums_to_one(self):
        det = RegimeDetector(n_regimes=2)
        sampler = ThompsonSampler(n_regimes=2)
        allocator = CapitalAllocator(det, sampler)

        sampler.register_agent("a1")
        sampler.register_agent("a2")
        sampler.register_agent("a3")

        features = np.zeros(4, dtype=np.float32)
        weights = allocator.allocate(features, ["a1", "a2", "a3"])
        assert abs(sum(weights.values()) - 1.0) < 1e-6
        assert all(w >= 0 for w in weights.values())

    def test_allocate_empty_agents(self):
        det = RegimeDetector(n_regimes=2)
        sampler = ThompsonSampler(n_regimes=2)
        allocator = CapitalAllocator(det, sampler)
        weights = allocator.allocate(np.zeros(4), [])
        assert weights == {}

    def test_update_from_results(self):
        det = RegimeDetector(n_regimes=2)
        sampler = ThompsonSampler(n_regimes=2)
        allocator = CapitalAllocator(det, sampler)
        sampler.register_agent("a1")
        features = np.zeros(4, dtype=np.float32)
        allocator.update_from_results(features, {"a1": 1.5})
        alpha, beta = sampler.get_posterior(0, "a1")
        assert alpha > 1.0

    def test_min_weight(self):
        det = RegimeDetector(n_regimes=1)
        sampler = ThompsonSampler(n_regimes=1)
        allocator = CapitalAllocator(det, sampler, min_weight=0.10)
        sampler.register_agent("a1")
        sampler.register_agent("a2")
        # Make a1 much better
        for _ in range(50):
            sampler.update(0, "a1", reward=5.0)
            sampler.update(0, "a2", reward=-5.0)
        weights = allocator.allocate(np.zeros(4), ["a1", "a2"])
        # Even the worst agent should have at least some weight (after renormalization)
        assert all(w > 0 for w in weights.values())
