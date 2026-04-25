"""Layer-level crossover for neuroevolution."""

from __future__ import annotations

import random
from typing import List

import torch

from agents.base_agent import BaseAgent


def crossover(
    parent1: BaseAgent,
    parent2: BaseAgent,
    crossover_prob: float = 0.30,
    new_id: str | None = None,
) -> BaseAgent:
    """Layer-level crossover: for each parameter tensor, randomly pick from parent1 or parent2.

    Each layer has `crossover_prob` chance of coming from parent2 (otherwise parent1).
    """
    child = parent1.clone(new_id=new_id)

    # Get parameter lists from both parents
    if child.ac_network is not None and parent2.ac_network is not None:
        _crossover_params(
            list(child.ac_network.parameters()),
            list(parent2.ac_network.parameters()),
            crossover_prob,
        )
    if child.dqn_head is not None and parent2.dqn_head is not None:
        _crossover_params(
            list(child.dqn_head.q_net.parameters()),
            list(parent2.dqn_head.q_net.parameters()),
            crossover_prob,
        )

    child.generation = max(parent1.generation, parent2.generation) + 1
    return child


def _crossover_params(
    child_params: List[torch.nn.Parameter],
    parent2_params: List[torch.nn.Parameter],
    prob: float,
) -> None:
    """In-place layer-level crossover."""
    for cp, p2p in zip(child_params, parent2_params):
        if random.random() < prob:
            cp.data.copy_(p2p.data)


def uniform_crossover(
    parent1: BaseAgent,
    parent2: BaseAgent,
    new_id: str | None = None,
) -> BaseAgent:
    """Element-wise uniform crossover: each weight has 50% chance from each parent."""
    child = parent1.clone(new_id=new_id)
    vec1 = parent1.get_param_vector()
    vec2 = parent2.get_param_vector()
    mask = torch.rand_like(vec1) > 0.5
    child_vec = torch.where(mask, vec1, vec2)
    child.set_param_vector(child_vec)
    child.generation = max(parent1.generation, parent2.generation) + 1
    return child
