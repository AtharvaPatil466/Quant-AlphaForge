"""Gaussian mutation with adaptive sigma for neuroevolution."""

from __future__ import annotations

import torch

from agents.base_agent import BaseAgent


def mutate(
    agent: BaseAgent,
    sigma: float = 0.02,
    new_id: str | None = None,
    per_param: bool = True,
) -> BaseAgent:
    """Create a mutated copy of the agent.

    When per_param=True (default), scales noise per-parameter by the
    absolute magnitude of each weight, so large weights get proportionally
    larger perturbations and small weights stay small. Falls back to
    homogeneous noise when magnitudes are near-zero.

    When per_param=False, uses classic homogeneous N(0, sigma) noise.
    """
    child = agent.clone(new_id=new_id)
    vec = child.get_param_vector()

    if per_param:
        # Per-parameter adaptive: sigma * (1 + |w|) so noise scales with weight magnitude
        # The +1 prevents near-zero weights from getting zero noise
        scale = sigma * (1.0 + torch.abs(vec))
        noise = torch.randn_like(vec) * scale
    else:
        noise = torch.randn_like(vec) * sigma

    child.set_param_vector(vec + noise)
    child.generation = agent.generation + 1
    return child


def adaptive_sigma(
    base_sigma: float,
    sigma_min: float,
    sigma_max: float,
    fitness_std: float,
    diversity_threshold: float = 0.5,
    improvement_rate: float = 0.0,
) -> float:
    """Adapt mutation strength with multi-level feedback.

    Uses fitness diversity AND improvement rate for finer-grained control:
    - Low diversity + no improvement → large sigma increase (stagnation)
    - Low diversity + improving → moderate sigma increase
    - High diversity + improving → decrease sigma (convergence)
    - High diversity + no improvement → hold steady (exploring but stuck)
    """
    if fitness_std < diversity_threshold:
        if improvement_rate <= 0:
            # Stagnation: aggressive exploration
            sigma = min(sigma_max, base_sigma * 2.0)
        else:
            # Converging but still improving
            sigma = min(sigma_max, base_sigma * 1.3)
    else:
        if improvement_rate > 0:
            # Diverse and improving: tighten search faster
            sigma = max(sigma_min, base_sigma * 0.6)
        else:
            # Diverse but not improving: still reduce slightly
            sigma = max(sigma_min, base_sigma * 0.85)
    return sigma
