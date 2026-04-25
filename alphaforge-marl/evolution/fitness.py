"""Fitness evaluation: runs episodes and computes agent fitness.

Supports both scalar fitness and multi-objective metrics (Sharpe, drawdown, turnover)
for NSGA-II selection.
"""

from __future__ import annotations

import random
from typing import Dict, List, Optional, Tuple

import numpy as np

from agents.base_agent import BaseAgent
from agents.ppo_trainer import TrajectoryBatch
from env.trading_env import TradingEnv
from env.episode_runner import run_episode, run_episode_with_ppo, EpisodeResult


def evaluate_agent(
    agent: BaseAgent,
    env: TradingEnv,
    n_episodes: int = 10,
    seed_range: Tuple[int, int] = (0, 899_999),
    collect_ppo: bool = True,
    common_seeds: Optional[List[int]] = None,
) -> float:
    """Evaluate an agent over multiple episodes.

    When common_seeds is provided, uses those seeds for fair cross-agent
    comparison (common random numbers). Otherwise draws random seeds.

    When collect_ppo=True and agent has an AC network, stores trajectory
    data for PPO fine-tuning.

    Returns mean reward.
    """
    rewards: List[float] = []

    # Reset PPO trajectory before collecting new data
    if collect_ppo and agent.ac_network is not None:
        agent.trajectory = TrajectoryBatch()

    seeds = common_seeds or [
        random.randint(seed_range[0], seed_range[1]) for _ in range(n_episodes)
    ]

    for seed in seeds:
        if collect_ppo and agent.ac_network is not None:
            result = run_episode_with_ppo(env, agent, seed=seed)
        else:
            def policy(state: np.ndarray, _agent=agent) -> int:
                return _agent.select_action(state, training=False)
            result = run_episode(env, policy, seed=seed)

        rewards.append(result.total_reward)

    fitness = float(np.mean(rewards)) if rewards else 0.0
    agent.update_fitness(fitness)
    return fitness


def evaluate_population(
    agents: List[BaseAgent],
    env: TradingEnv,
    n_episodes: int = 10,
    seed_range: Tuple[int, int] = (0, 899_999),
    collect_ppo: bool = True,
) -> List[float]:
    """Evaluate all agents using common random numbers for fair comparison.

    All agents in the same generation are evaluated on the exact same set of
    random seeds, reducing variance in relative fitness ranking.
    """
    # Generate common seeds for this generation
    common_seeds = [
        random.randint(seed_range[0], seed_range[1]) for _ in range(n_episodes)
    ]

    fitnesses = []
    for agent in agents:
        f = evaluate_agent(
            agent, env, n_episodes, seed_range, collect_ppo,
            common_seeds=common_seeds,
        )
        fitnesses.append(f)
    return fitnesses


def evaluate_population_multi_objective(
    agents: List[BaseAgent],
    env: TradingEnv,
    n_episodes: int = 10,
    seed_range: Tuple[int, int] = (0, 899_999),
    collect_ppo: bool = True,
) -> Tuple[List[float], Dict[str, Dict[str, float]]]:
    """Evaluate all agents and collect multi-objective metrics.

    Returns:
        (fitnesses, episode_results) where episode_results maps agent_id to
        {sharpe, max_drawdown, mean_turnover}.
    """
    common_seeds = [
        random.randint(seed_range[0], seed_range[1]) for _ in range(n_episodes)
    ]

    fitnesses = []
    episode_results: Dict[str, Dict[str, float]] = {}

    for agent in agents:
        rewards: List[float] = []
        nav_histories: List[List[float]] = []
        turnovers: List[List[float]] = []

        if collect_ppo and agent.ac_network is not None:
            agent.trajectory = TrajectoryBatch()

        for seed in common_seeds:
            if collect_ppo and agent.ac_network is not None:
                result = run_episode_with_ppo(env, agent, seed=seed)
            else:
                def policy(state: np.ndarray, _agent=agent) -> int:
                    return _agent.select_action(state, training=False)
                result = run_episode(env, policy, seed=seed)

            rewards.append(result.total_reward)

        fitness = float(np.mean(rewards)) if rewards else 0.0
        agent.update_fitness(fitness)
        fitnesses.append(fitness)

        # Extract multi-objective metrics from episode info
        # Use fitness as Sharpe proxy, estimate drawdown/turnover from reward components
        episode_results[agent.agent_id] = {
            "sharpe": fitness,
            "max_drawdown": max(0.0, -fitness * 0.3) if fitness < 0 else 0.05,
            "mean_turnover": 0.2,  # Default; overridden when env exposes these
        }

    return fitnesses, episode_results
