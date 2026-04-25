"""Capital allocation across agents based on regime-conditional Thompson sampling."""

from __future__ import annotations

from typing import Dict, List

import numpy as np

from bandit.thompson_sampler import ThompsonSampler
from bandit.regime_detector import RegimeDetector


class CapitalAllocator:
    """Allocates capital weights to agents based on regime detection + bandit.

    The allocator:
    1. Detects the current market regime
    2. Uses Thompson sampling to score agents for this regime
    3. Normalizes scores into capital weights
    """

    def __init__(
        self,
        regime_detector: RegimeDetector,
        sampler: ThompsonSampler,
        min_weight: float = 0.05,
    ):
        self.regime_detector = regime_detector
        self.sampler = sampler
        self.min_weight = min_weight

    def allocate(
        self,
        regime_features: np.ndarray,
        agent_ids: List[str],
    ) -> Dict[str, float]:
        """Compute capital allocation for agents given current regime features.

        Args:
            regime_features: 1D array of regime features (autocorr, vol, hurst, vol_ratio).
            agent_ids: List of agent IDs to allocate across.

        Returns:
            Dict mapping agent_id -> capital weight (sums to 1.0).
        """
        if not agent_ids:
            return {}

        regime = self.regime_detector.predict_single(regime_features)

        # Thompson sample expected values for each agent
        scores: Dict[str, float] = {}
        for aid in agent_ids:
            scores[aid] = self.sampler.expected_value(regime, aid)

        # Softmax-like normalization with minimum weight
        total = sum(scores.values())
        if total < 1e-12:
            # Equal weight fallback
            w = 1.0 / len(agent_ids)
            return {aid: w for aid in agent_ids}

        weights = {aid: max(self.min_weight, s / total) for aid, s in scores.items()}

        # Re-normalize to sum to 1
        w_total = sum(weights.values())
        weights = {aid: w / w_total for aid, w in weights.items()}

        return weights

    def update_from_results(
        self,
        regime_features: np.ndarray,
        agent_rewards: Dict[str, float],
    ) -> None:
        """Update bandit posteriors from agent performance.

        Args:
            regime_features: Features of the regime during which agents traded.
            agent_rewards: Dict mapping agent_id -> episode reward.
        """
        regime = self.regime_detector.predict_single(regime_features)
        for agent_id, reward in agent_rewards.items():
            self.sampler.update(regime, agent_id, reward)
