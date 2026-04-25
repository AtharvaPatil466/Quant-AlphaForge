"""Ensemble: mixture of experts using regime-conditional agent weighting.

Maintains a Pareto front of agents (diverse strategies) and blends their
action distributions at inference time, weighted by the regime bandit.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np
import torch

from agents.base_agent import BaseAgent
from bandit.capital_allocator import CapitalAllocator


class ParetoFront:
    """Maintains a set of non-dominated agents across multiple objectives.

    An agent is Pareto-optimal if no other agent is better on ALL objectives.
    This preserves diverse strategies (e.g., high-Sharpe vs low-drawdown).
    """

    def __init__(self, max_size: int = 10):
        self.max_size = max_size
        self.members: List[Tuple[BaseAgent, Dict[str, float]]] = []

    def update(
        self,
        agents: List[BaseAgent],
        objectives: Dict[str, List[float]],
    ) -> List[BaseAgent]:
        """Update Pareto front from agent pool.

        Args:
            agents: List of agents to consider.
            objectives: Dict mapping objective name to list of values
                       (same order as agents). Higher is better for all.

        Returns:
            List of Pareto-optimal agents.
        """
        n = len(agents)
        obj_names = list(objectives.keys())
        obj_matrix = np.array([objectives[k] for k in obj_names]).T  # (n, n_obj)

        # Find non-dominated set
        dominated = set()
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                # j dominates i if j >= i on all objectives and j > i on at least one
                if (obj_matrix[j] >= obj_matrix[i]).all() and (obj_matrix[j] > obj_matrix[i]).any():
                    dominated.add(i)
                    break

        pareto = [
            (agents[i], {k: float(obj_matrix[i, ki]) for ki, k in enumerate(obj_names)})
            for i in range(n)
            if i not in dominated
        ]

        # Limit size: keep most diverse if too many
        if len(pareto) > self.max_size:
            pareto = sorted(pareto, key=lambda x: -sum(x[1].values()))[:self.max_size]

        self.members = pareto
        return [a for a, _ in pareto]


class EnsemblePolicy:
    """Blends action distributions from multiple agents using regime weights.

    At inference time:
    1. Detect regime via CapitalAllocator
    2. Get regime-conditional weights for each agent
    3. Weighted average of action distributions
    4. Sample or argmax from the blended distribution
    """

    def __init__(
        self,
        agents: List[BaseAgent],
        allocator: Optional[CapitalAllocator] = None,
    ):
        self.agents = list(agents)
        self.allocator = allocator
        self._weights: Dict[str, float] = {}

    def set_agents(self, agents: List[BaseAgent]) -> None:
        self.agents = list(agents)

    def select_action(
        self,
        state: np.ndarray,
        regime_features: Optional[np.ndarray] = None,
        training: bool = False,
    ) -> int:
        """Select action by blending agent distributions.

        Args:
            state: Current observation.
            regime_features: If provided + allocator set, uses regime-weighted blending.
            training: If True, sample from blended distribution; else argmax.
        """
        if not self.agents:
            return 0

        state_t = torch.FloatTensor(state).unsqueeze(0)

        # Get weights from regime bandit or use uniform
        if self.allocator is not None and regime_features is not None:
            agent_ids = [a.agent_id for a in self.agents]
            self._weights = self.allocator.allocate(regime_features, agent_ids)
        else:
            w = 1.0 / len(self.agents)
            self._weights = {a.agent_id: w for a in self.agents}

        # Blend action distributions
        blended = torch.zeros(5)
        for agent in self.agents:
            w = self._weights.get(agent.agent_id, 0.0)
            if w < 1e-10 or agent.ac_network is None:
                continue
            with torch.no_grad():
                probs = agent.ac_network.get_policy(state_t).squeeze(0)
            blended += w * probs

        # Normalize
        total = blended.sum()
        if total < 1e-10:
            blended = torch.ones(5) / 5.0
        else:
            blended = blended / total

        if training:
            dist = torch.distributions.Categorical(probs=blended)
            return dist.sample().item()
        else:
            return blended.argmax().item()

    @property
    def weights(self) -> Dict[str, float]:
        """Last-used agent weights."""
        return dict(self._weights)
