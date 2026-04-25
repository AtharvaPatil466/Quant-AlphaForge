"""Distributed training: parallel agent evaluation across CPU cores.

Uses multiprocessing to evaluate agents in parallel. Each worker gets a
copy of the environment and runs episodes independently. Results are
collected by the main process for selection and evolution.
"""

from __future__ import annotations

import multiprocessing as mp
import os
from dataclasses import dataclass
from functools import partial
from typing import Dict, List, Optional, Tuple

import numpy as np
import torch

from agents.base_agent import BaseAgent, AgentType
from agents.ppo_trainer import TrajectoryBatch


@dataclass
class EvalResult:
    """Result of evaluating a single agent."""
    agent_id: str
    fitness: float
    rewards: List[float]
    trajectory_states: Optional[List[np.ndarray]] = None
    trajectory_actions: Optional[List[int]] = None
    trajectory_rewards: Optional[List[float]] = None
    trajectory_values: Optional[List[float]] = None
    trajectory_log_probs: Optional[List[float]] = None
    trajectory_dones: Optional[List[bool]] = None


def _worker_evaluate_agent(
    agent_params: Tuple[str, List[float], List[int], str],
    env_kwargs: Dict,
    n_episodes: int,
    seeds: List[int],
    collect_ppo: bool,
    hidden_sizes: List[int],
    obs_dim: int,
    n_actions: int,
) -> EvalResult:
    """Worker function for parallel agent evaluation.

    Receives agent params as flat list (serializable), reconstructs the
    agent locally, runs episodes, and returns results.
    """
    agent_id, param_list, hs, activation = agent_params

    # Reconstruct agent in worker process
    from agents.base_agent import BaseAgent, AgentType
    from agents.actor_critic import ActorCriticNetwork
    from env.trading_env import TradingEnv
    from env.episode_runner import run_episode, run_episode_with_ppo

    agent = BaseAgent(
        agent_type=AgentType.ACTOR_CRITIC,
        obs_dim=obs_dim,
        n_actions=n_actions,
        hidden_sizes=hs,
        activation=activation,
        agent_id=agent_id,
    )
    agent.set_param_vector(torch.FloatTensor(param_list))

    env = TradingEnv(**env_kwargs)

    rewards = []
    if collect_ppo:
        agent.trajectory = TrajectoryBatch()

    for seed in seeds:
        if collect_ppo and agent.ac_network is not None:
            result = run_episode_with_ppo(env, agent, seed=seed)
        else:
            def policy(state, _agent=agent):
                return _agent.select_action(state, training=False)
            result = run_episode(env, policy, seed=seed)
        rewards.append(result.total_reward)

    fitness = float(np.mean(rewards)) if rewards else 0.0

    # Serialize trajectory for PPO (if collected)
    eval_result = EvalResult(
        agent_id=agent_id,
        fitness=fitness,
        rewards=rewards,
    )

    if collect_ppo and len(agent.trajectory) > 0:
        traj = agent.trajectory
        eval_result.trajectory_states = traj.states
        eval_result.trajectory_actions = traj.actions
        eval_result.trajectory_rewards = traj.rewards
        eval_result.trajectory_values = traj.values
        eval_result.trajectory_log_probs = traj.log_probs
        eval_result.trajectory_dones = traj.dones

    return eval_result


class DistributedEvaluator:
    """Parallel agent evaluator using multiprocessing.

    Distributes agent episodes across CPU cores. Each agent's evaluation
    is an independent task — no inter-agent communication during eval.
    """

    def __init__(
        self,
        n_workers: Optional[int] = None,
        env_kwargs: Optional[Dict] = None,
    ):
        self.n_workers = n_workers or max(1, mp.cpu_count() - 1)
        self.env_kwargs = env_kwargs or {}
        self._pool: Optional[mp.Pool] = None

    def start(self) -> None:
        """Start the worker pool."""
        if self._pool is None:
            # Use 'spawn' to avoid fork-related issues with PyTorch
            ctx = mp.get_context("spawn")
            self._pool = ctx.Pool(processes=self.n_workers)

    def stop(self) -> None:
        """Shut down the worker pool."""
        if self._pool is not None:
            self._pool.terminate()
            self._pool.join()
            self._pool = None

    def evaluate_population(
        self,
        agents: List[BaseAgent],
        n_episodes: int = 10,
        seed_range: Tuple[int, int] = (0, 899_999),
        collect_ppo: bool = True,
    ) -> List[float]:
        """Evaluate all agents in parallel.

        Returns list of fitness values in the same order as agents.
        Also updates each agent's fitness and trajectory in-place.
        """
        import random

        # Generate common seeds
        common_seeds = [
            random.randint(seed_range[0], seed_range[1])
            for _ in range(n_episodes)
        ]

        # Serialize agent params for workers
        agent_params = []
        for a in agents:
            agent_params.append((
                a.agent_id,
                a.get_param_vector().tolist(),
                a.hidden_sizes,
                a.activation,
            ))

        obs_dim = agents[0].obs_dim if agents else 57
        n_actions = agents[0].n_actions if agents else 5

        worker_fn = partial(
            _worker_evaluate_agent,
            env_kwargs=self.env_kwargs,
            n_episodes=n_episodes,
            seeds=common_seeds,
            collect_ppo=collect_ppo,
            hidden_sizes=agents[0].hidden_sizes if agents else [256, 128, 64],
            obs_dim=obs_dim,
            n_actions=n_actions,
        )

        if self._pool is not None and len(agents) > 1:
            # Parallel evaluation
            results = self._pool.map(worker_fn, agent_params)
        else:
            # Fallback: sequential
            results = [worker_fn(ap) for ap in agent_params]

        # Map results back to agents
        result_map = {r.agent_id: r for r in results}
        fitnesses = []

        for agent in agents:
            r = result_map.get(agent.agent_id)
            if r is None:
                agent.update_fitness(0.0)
                fitnesses.append(0.0)
                continue

            agent.update_fitness(r.fitness)
            fitnesses.append(r.fitness)

            # Restore PPO trajectory
            if collect_ppo and r.trajectory_states is not None:
                agent.trajectory = TrajectoryBatch()
                for i in range(len(r.trajectory_states)):
                    agent.trajectory.append(
                        state=r.trajectory_states[i],
                        action=r.trajectory_actions[i],
                        reward=r.trajectory_rewards[i],
                        value=r.trajectory_values[i],
                        log_prob=r.trajectory_log_probs[i],
                        done=r.trajectory_dones[i],
                    )

        return fitnesses

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()

    def __del__(self):
        self.stop()
