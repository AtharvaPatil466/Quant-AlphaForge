"""Evolutionary engine: orchestrates selection, crossover, mutation across generations."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from agents.base_agent import BaseAgent
from agents.agent_pool import AgentPool
from env.trading_env import TradingEnv
from agents.maml import MAMLTrainer
from evolution.fitness import evaluate_population, evaluate_population_multi_objective
from evolution.nsga2 import nsga2_select, compute_multi_objectives
from evolution.selection import tournament_select_pair
from evolution.mutation import mutate, adaptive_sigma
from evolution.crossover import crossover
from evolution.speciation import SpeciationManager

logger = logging.getLogger(__name__)


@dataclass
class GenerationStats:
    generation: int
    best_fitness: float
    mean_fitness: float
    fitness_std: float
    sigma: float
    best_agent_id: str
    val_sharpe: float = 0.0
    ppo_policy_loss: float = 0.0
    ppo_value_loss: float = 0.0


class EvolutionaryEngine:
    """Manages neuroevolution of the agent population.

    Each generation:
    1. Evaluate all agents (random training seeds)
    2. PPO fine-tune survivors on their episode trajectories
    3. Keep elites unchanged
    4. Replace worst with offspring (crossover + mutation from survivors)
    5. Adapt mutation sigma based on diversity
    """

    def __init__(
        self,
        pool: AgentPool,
        env: TradingEnv,
        sigma_init: float = 0.02,
        sigma_min: float = 0.001,
        sigma_max: float = 0.10,
        crossover_prob: float = 0.30,
        diversity_threshold: float = 0.5,
        episodes_per_agent: int = 10,
        seed_range: Tuple[int, int] = (0, 899_999),
        ppo_enabled: bool = True,
        maml_enabled: bool = True,
        maml_every_n_gens: int = 5,
        nsga2_enabled: bool = True,
    ):
        self.pool = pool
        self.env = env
        self.sigma = sigma_init
        self.sigma_min = sigma_min
        self.sigma_max = sigma_max
        self.crossover_prob = crossover_prob
        self.diversity_threshold = diversity_threshold
        self.episodes_per_agent = episodes_per_agent
        self.seed_range = seed_range
        self.ppo_enabled = ppo_enabled
        self.generation = 0
        self.history: List[GenerationStats] = []

        # Speciation for behavioral diversity
        obs_dim = env.observation_space.shape[0] if env.observation_space else 57
        self.speciation = SpeciationManager(obs_dim=obs_dim)

        # MAML meta-learning for elite agents (every N generations)
        self.maml_enabled = maml_enabled
        self.maml_every_n_gens = maml_every_n_gens
        self._maml_trainers: dict[str, MAMLTrainer] = {}

        # NSGA-II multi-objective selection
        self.nsga2_enabled = nsga2_enabled
        self._episode_results: dict[str, dict[str, float]] = {}

        # Distributed evaluation (set by Trainer when enabled)
        self.distributed_evaluator = None

    def run_generation(self) -> GenerationStats:
        """Execute one full generation cycle."""
        self.generation += 1
        self.pool.set_generation(self.generation)

        # 1. Evaluate with random training seeds
        if self.distributed_evaluator is not None:
            # Parallel evaluation across CPU cores
            self.distributed_evaluator.evaluate_population(
                self.pool.agents, self.episodes_per_agent, self.seed_range,
            )
        elif self.nsga2_enabled:
            _, self._episode_results = evaluate_population_multi_objective(
                self.pool.agents, self.env, self.episodes_per_agent, self.seed_range
            )
        else:
            evaluate_population(
                self.pool.agents, self.env, self.episodes_per_agent, self.seed_range
            )

        # 2. PPO fine-tune survivors
        ppo_policy_loss = 0.0
        ppo_value_loss = 0.0
        if self.ppo_enabled:
            survivors = self.pool.survivors()
            n_updated = 0
            for agent in survivors:
                if agent.ppo_trainer and len(agent.trajectory) > 0:
                    metrics = agent.train_step()
                    ppo_policy_loss += metrics.get("policy_loss", 0.0)
                    ppo_value_loss += metrics.get("value_loss", 0.0)
                    n_updated += 1
            if n_updated > 0:
                ppo_policy_loss /= n_updated
                ppo_value_loss /= n_updated

        # 2b. MAML meta-update for elites (periodic)
        if (
            self.maml_enabled
            and self.generation % self.maml_every_n_gens == 0
        ):
            for agent in self.pool.elites():
                if agent.ac_network is not None and len(agent.trajectory) > 10:
                    if agent.agent_id not in self._maml_trainers:
                        self._maml_trainers[agent.agent_id] = MAMLTrainer(
                            agent.ac_network
                        )
                    maml = self._maml_trainers[agent.agent_id]
                    # Split trajectory into support/query halves
                    traj = agent.trajectory
                    mid = len(traj) // 2
                    from agents.ppo_trainer import TrajectoryBatch
                    support = TrajectoryBatch()
                    query = TrajectoryBatch()
                    for i in range(mid):
                        support.append(
                            traj.states[i], traj.actions[i], traj.rewards[i],
                            traj.values[i], traj.log_probs[i], traj.dones[i],
                        )
                    for i in range(mid, len(traj)):
                        query.append(
                            traj.states[i], traj.actions[i], traj.rewards[i],
                            traj.values[i], traj.log_probs[i], traj.dones[i],
                        )
                    maml.meta_update([(support, query)])

        # 3. Determine survivors using NSGA-II or standard ranking
        if self.nsga2_enabled and self._episode_results:
            objectives = compute_multi_objectives(
                self.pool.agents, self._episode_results
            )
            n_survive = max(1, int(self.pool.n_agents * self.pool.survivor_fraction))
            nsga2_survivors = nsga2_select(
                self.pool.agents, objectives, n_survive
            )
            survivor_ids = {a.agent_id for a in nsga2_survivors}
            worst = [a for a in self.pool.agents if a.agent_id not in survivor_ids]
        else:
            worst = self.pool.worst()

        # Speciate for diversity-preserving reproduction
        species_list = self.speciation.speciate(self.pool.agents)
        elites = self.pool.elites()
        elite_ids = {a.agent_id for a in elites}
        n_offspring = len(worst)

        if species_list and n_offspring > 0:
            offspring_counts = self.speciation.get_offspring_counts(n_offspring)
            species_map = {s.species_id: s for s in species_list}

            offspring_idx = 0
            slots = list(worst)
            for sid, count in offspring_counts.items():
                sp = species_map.get(sid)
                if sp is None or not sp.members:
                    continue
                for _ in range(count):
                    if offspring_idx >= len(slots):
                        break
                    parent1, parent2 = tournament_select_pair(sp.members)
                    child = crossover(
                        parent1,
                        parent2,
                        self.crossover_prob,
                        new_id=f"gen{self.generation:03d}_{offspring_idx:03d}",
                    )
                    child = mutate(child, self.sigma, new_id=child.agent_id)
                    child.generation = self.generation
                    self.pool.replace(slots[offspring_idx].agent_id, child)
                    offspring_idx += 1

            # Fill any remaining slots with global tournament
            survivors = self.pool.survivors()
            while offspring_idx < len(slots):
                parent1, parent2 = tournament_select_pair(survivors)
                child = crossover(
                    parent1,
                    parent2,
                    self.crossover_prob,
                    new_id=f"gen{self.generation:03d}_{offspring_idx:03d}",
                )
                child = mutate(child, self.sigma, new_id=child.agent_id)
                child.generation = self.generation
                self.pool.replace(slots[offspring_idx].agent_id, child)
                offspring_idx += 1
        else:
            # Fallback: classic replacement without speciation
            survivors = self.pool.survivors()
            offspring_idx = 0
            for old_agent in worst:
                parent1, parent2 = tournament_select_pair(survivors)
                child = crossover(
                    parent1,
                    parent2,
                    self.crossover_prob,
                    new_id=f"gen{self.generation:03d}_{offspring_idx:03d}",
                )
                child = mutate(child, self.sigma, new_id=child.agent_id)
                child.generation = self.generation
                self.pool.replace(old_agent.agent_id, child)
                offspring_idx += 1

        # 4. Adapt sigma with improvement tracking
        improvement_rate = 0.0
        if len(self.history) >= 2:
            prev_best = self.history[-1].best_fitness
            curr_best = self.pool.max_fitness()
            improvement_rate = curr_best - prev_best
        self.sigma = adaptive_sigma(
            self.sigma,
            self.sigma_min,
            self.sigma_max,
            self.pool.fitness_std(),
            self.diversity_threshold,
            improvement_rate=improvement_rate,
        )

        # 5. Record stats
        stats = GenerationStats(
            generation=self.generation,
            best_fitness=self.pool.max_fitness(),
            mean_fitness=self.pool.mean_fitness(),
            fitness_std=self.pool.fitness_std(),
            sigma=self.sigma,
            best_agent_id=self.pool.best().agent_id,
            ppo_policy_loss=ppo_policy_loss,
            ppo_value_loss=ppo_value_loss,
        )
        self.history.append(stats)

        logger.info(
            f"Gen {stats.generation}: best={stats.best_fitness:.4f} "
            f"mean={stats.mean_fitness:.4f} std={stats.fitness_std:.4f} "
            f"sigma={stats.sigma:.4f} ppo_ploss={ppo_policy_loss:.6f}"
        )
        return stats

    def run(self, n_generations: int) -> List[GenerationStats]:
        """Run multiple generations."""
        for _ in range(n_generations):
            self.run_generation()
        return self.history
