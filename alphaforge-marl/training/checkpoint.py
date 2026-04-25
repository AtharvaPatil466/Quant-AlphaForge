"""Checkpoint saving and loading for MARL training."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

import torch

from agents.base_agent import BaseAgent
from agents.agent_pool import AgentPool


def save_checkpoint(
    pool: AgentPool,
    generation: int,
    sigma: float,
    path: str,
    extra: Dict[str, Any] | None = None,
) -> str:
    """Save population checkpoint to disk.

    Saves:
    - Each agent's parameter vector and metadata
    - Generation number and sigma
    - Any extra metadata
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    agents_data = []
    for agent in pool.agents:
        agents_data.append({
            "agent_id": agent.agent_id,
            "agent_type": agent.agent_type.value,
            "fitness": agent.fitness,
            "fitness_history": agent.fitness_history,
            "generation": agent.generation,
            "params": agent.get_param_vector().tolist(),
        })

    checkpoint = {
        "generation": generation,
        "sigma": sigma,
        "n_agents": pool.n_agents,
        "agents": agents_data,
        "extra": extra or {},
    }

    torch.save(checkpoint, path)
    return path


def load_checkpoint(
    path: str,
    pool: AgentPool,
) -> Dict[str, Any]:
    """Load population from checkpoint.

    Returns dict with generation, sigma, and extra metadata.
    """
    checkpoint = torch.load(path, weights_only=False)

    for i, agent_data in enumerate(checkpoint["agents"]):
        if i < len(pool.agents):
            agent = pool.agents[i]
            agent.agent_id = agent_data["agent_id"]
            agent.fitness = agent_data["fitness"]
            agent.fitness_history = agent_data["fitness_history"]
            agent.generation = agent_data["generation"]
            params = torch.FloatTensor(agent_data["params"])
            agent.set_param_vector(params)

    return {
        "generation": checkpoint["generation"],
        "sigma": checkpoint["sigma"],
        "extra": checkpoint.get("extra", {}),
    }
