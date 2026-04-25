"""Tournament and rank-based selection for evolutionary engine."""

from __future__ import annotations

import random
from typing import List

from agents.base_agent import BaseAgent


def tournament_select(
    agents: List[BaseAgent],
    tournament_size: int = 3,
) -> BaseAgent:
    """Select one agent via tournament selection."""
    contestants = random.sample(agents, min(tournament_size, len(agents)))
    return max(contestants, key=lambda a: a.fitness)


def tournament_select_pair(
    agents: List[BaseAgent],
    tournament_size: int = 3,
) -> tuple[BaseAgent, BaseAgent]:
    """Select two distinct parents via tournament selection."""
    parent1 = tournament_select(agents, tournament_size)
    # Ensure parent2 is different
    remaining = [a for a in agents if a.agent_id != parent1.agent_id]
    if not remaining:
        remaining = agents
    parent2 = tournament_select(remaining, tournament_size)
    return parent1, parent2


def rank_select(agents: List[BaseAgent]) -> BaseAgent:
    """Rank-proportional selection: higher rank = higher probability."""
    ranked = sorted(agents, key=lambda a: a.fitness)
    n = len(ranked)
    # Rank weights: 1, 2, ..., n
    weights = list(range(1, n + 1))
    total = sum(weights)
    probs = [w / total for w in weights]
    return random.choices(ranked, weights=probs, k=1)[0]
