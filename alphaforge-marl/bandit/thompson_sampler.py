"""Thompson sampling for regime-conditional agent selection."""

from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np


class ThompsonSampler:
    """Beta-Bernoulli Thompson sampling per regime.

    Maintains a Beta(alpha, beta) posterior for each (regime, agent) pair.
    Samples from the posterior to select the best agent for the current regime.
    """

    def __init__(
        self,
        n_regimes: int = 4,
        prior_alpha: float = 1.0,
        prior_beta: float = 1.0,
    ):
        self.n_regimes = n_regimes
        self.prior_alpha = prior_alpha
        self.prior_beta = prior_beta

        # {regime: {agent_id: (alpha, beta)}}
        self._posteriors: Dict[int, Dict[str, Tuple[float, float]]] = {
            r: {} for r in range(n_regimes)
        }

    def register_agent(self, agent_id: str) -> None:
        """Register a new agent with prior for all regimes."""
        for r in range(self.n_regimes):
            if agent_id not in self._posteriors[r]:
                self._posteriors[r][agent_id] = (self.prior_alpha, self.prior_beta)

    def select(self, regime: int, agent_ids: List[str]) -> str:
        """Thompson sample: draw from each agent's posterior, pick the max.

        We convert fitness to a "success probability" by treating positive
        reward as success and negative as failure.
        """
        if not agent_ids:
            raise ValueError("No agents to select from")

        best_id = agent_ids[0]
        best_sample = -float("inf")

        for aid in agent_ids:
            alpha, beta = self._posteriors.get(regime, {}).get(
                aid, (self.prior_alpha, self.prior_beta)
            )
            sample = np.random.beta(alpha, beta)
            if sample > best_sample:
                best_sample = sample
                best_id = aid

        return best_id

    def update(self, regime: int, agent_id: str, reward: float) -> None:
        """Update posterior based on observed reward.

        reward > 0 → success (increment alpha)
        reward <= 0 → failure (increment beta)
        Magnitude scales the update.
        """
        if regime not in self._posteriors:
            self._posteriors[regime] = {}
        alpha, beta = self._posteriors[regime].get(
            agent_id, (self.prior_alpha, self.prior_beta)
        )

        magnitude = min(abs(reward), 5.0)  # Cap magnitude
        if reward > 0:
            alpha += magnitude
        else:
            beta += magnitude

        self._posteriors[regime][agent_id] = (alpha, beta)

    def get_posterior(self, regime: int, agent_id: str) -> Tuple[float, float]:
        """Get current (alpha, beta) for a regime-agent pair."""
        return self._posteriors.get(regime, {}).get(
            agent_id, (self.prior_alpha, self.prior_beta)
        )

    def expected_value(self, regime: int, agent_id: str) -> float:
        """E[Beta(alpha, beta)] = alpha / (alpha + beta)."""
        alpha, beta = self.get_posterior(regime, agent_id)
        return alpha / (alpha + beta)
