"""Speciation: behavioral diversity metrics and species-based selection.

Agents are grouped into species based on behavioral distance (action
distribution similarity). Each species competes internally, preserving
strategy diversity across the population.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np
import torch

from agents.base_agent import BaseAgent


class Species:
    """A group of behaviorally similar agents."""

    def __init__(self, species_id: int, representative: BaseAgent):
        self.species_id = species_id
        self.representative = representative
        self.members: List[BaseAgent] = [representative]
        self.best_fitness: float = representative.fitness
        self.stagnation: int = 0

    def add(self, agent: BaseAgent) -> None:
        self.members.append(agent)

    def update_stats(self) -> None:
        if not self.members:
            return
        new_best = max(a.fitness for a in self.members)
        if new_best > self.best_fitness:
            self.best_fitness = new_best
            self.stagnation = 0
        else:
            self.stagnation += 1

    def adjusted_fitness(self) -> List[float]:
        """Fitness sharing: divide fitness by species size to prevent dominance."""
        n = max(1, len(self.members))
        return [a.fitness / n for a in self.members]


def compute_behavior_vector(
    agent: BaseAgent,
    probe_states: torch.Tensor,
) -> np.ndarray:
    """Compute a behavioral fingerprint: action distribution over probe states.

    Returns a flat vector of action probabilities across all probe states.
    """
    if agent.ac_network is None:
        return np.zeros(probe_states.shape[0] * 5)

    with torch.no_grad():
        probs = agent.ac_network.get_policy(probe_states)
    return probs.numpy().flatten()


def behavioral_distance(bv1: np.ndarray, bv2: np.ndarray) -> float:
    """Jensen-Shannon divergence between two behavioral vectors."""
    # Reshape into action distributions
    n_states = len(bv1) // 5
    if n_states == 0:
        return 0.0
    p = bv1.reshape(n_states, 5)
    q = bv2.reshape(n_states, 5)

    # Average JS divergence across probe states
    eps = 1e-10
    p = np.clip(p, eps, None)
    q = np.clip(q, eps, None)
    m = 0.5 * (p + q)
    js = 0.5 * np.sum(p * np.log(p / m), axis=1) + 0.5 * np.sum(q * np.log(q / m), axis=1)
    return float(np.mean(js))


def generate_probe_states(n_probes: int = 20, obs_dim: int = 57) -> torch.Tensor:
    """Generate fixed probe states for behavioral fingerprinting.

    Uses a fixed seed so probes are consistent across generations.
    """
    rng = np.random.RandomState(42)
    probes = rng.randn(n_probes, obs_dim).astype(np.float32) * 0.5
    return torch.FloatTensor(probes)


class SpeciationManager:
    """Assigns agents to species and manages species lifecycle.

    Uses behavioral distance (action distribution similarity over probe
    states) to cluster agents into species. Species compete internally,
    preventing a single dominant strategy from taking over.
    """

    def __init__(
        self,
        compatibility_threshold: float = 0.15,
        max_stagnation: int = 15,
        obs_dim: int = 57,
        n_probes: int = 20,
    ):
        self.threshold = compatibility_threshold
        self.max_stagnation = max_stagnation
        self.species: List[Species] = []
        self._next_id = 0
        self.probe_states = generate_probe_states(n_probes, obs_dim)

    def speciate(self, agents: List[BaseAgent]) -> List[Species]:
        """Assign all agents to species based on behavioral distance."""
        # Compute behavior vectors
        bvs = {
            a.agent_id: compute_behavior_vector(a, self.probe_states)
            for a in agents
        }

        # Clear existing species members
        for s in self.species:
            s.members = []

        # Assign each agent to nearest species or create new one
        for agent in agents:
            placed = False
            for s in self.species:
                rep_bv = compute_behavior_vector(s.representative, self.probe_states)
                dist = behavioral_distance(bvs[agent.agent_id], rep_bv)
                if dist < self.threshold:
                    s.add(agent)
                    placed = True
                    break

            if not placed:
                new_species = Species(self._next_id, agent)
                self._next_id += 1
                self.species.append(new_species)

        # Remove empty species
        self.species = [s for s in self.species if s.members]

        # Update representatives to be the best member
        for s in self.species:
            s.representative = max(s.members, key=lambda a: a.fitness)
            s.update_stats()

        # Remove stagnant species (keep at least 2)
        if len(self.species) > 2:
            self.species = [
                s for s in self.species
                if s.stagnation < self.max_stagnation
            ] or self.species[:2]

        return self.species

    def get_offspring_counts(self, total_offspring: int) -> Dict[int, int]:
        """Allocate offspring slots to species proportional to adjusted fitness.

        Species with higher adjusted fitness get more offspring, maintaining
        diversity pressure.
        """
        if not self.species:
            return {}

        # Sum adjusted fitness per species
        species_scores = []
        for s in self.species:
            adj = s.adjusted_fitness()
            species_scores.append((s.species_id, max(0.0, sum(adj))))

        total_score = sum(sc for _, sc in species_scores)
        if total_score < 1e-12:
            # Equal distribution
            per = total_offspring // max(1, len(self.species))
            counts = {sid: per for sid, _ in species_scores}
            # Distribute remainder
            remainder = total_offspring - sum(counts.values())
            for sid, _ in species_scores[:remainder]:
                counts[sid] += 1
            return counts

        counts = {}
        allocated = 0
        for sid, score in species_scores:
            n = max(1, int(round(total_offspring * score / total_score)))
            counts[sid] = n
            allocated += n

        # Adjust to exactly match total
        diff = total_offspring - allocated
        if diff != 0:
            best_sid = max(species_scores, key=lambda x: x[1])[0]
            counts[best_sid] = max(1, counts[best_sid] + diff)

        return counts
