"""Evaluate the best agent from a checkpoint on held-out episodes (unseen seeds)."""

from __future__ import annotations

import os
import sys
import math

import numpy as np

_MARL = os.path.dirname(__file__)
_ROOT = os.path.dirname(os.path.dirname(__file__))
for p in [os.path.join(_ROOT, "alphaforge-python"), _MARL]:
    if p not in sys.path:
        sys.path.insert(0, p)

import torch
from agents.agent_pool import AgentPool
from agents.base_agent import AgentType
from env.trading_env import TradingEnv
from env.episode_runner import run_episode, EpisodeResult
from training.checkpoint import load_checkpoint


def evaluate_holdout(checkpoint_path: str, n_episodes: int = 50, seed_offset: int = 100_000):
    """Load best agent from checkpoint, run on held-out seeds."""

    # Build pool matching default config
    pool = AgentPool(
        n_agents=30,
        agent_type=AgentType.ACTOR_CRITIC,
        obs_dim=57,
        n_actions=5,
        hidden_sizes=[256, 128, 64],
    )
    meta = load_checkpoint(checkpoint_path, pool)
    gen = meta["generation"]

    # Find best agent
    best = pool.best()
    print(f"Loaded checkpoint gen {gen}, best agent: {best.agent_id} (train fitness: {best.fitness:.4f})")
    print(f"Evaluating on {n_episodes} held-out episodes (seeds {seed_offset}–{seed_offset + n_episodes - 1})\n")

    env = TradingEnv(episode_length=252)

    rewards = []
    navs = []
    for ep in range(n_episodes):
        seed = seed_offset + ep

        def policy(state, _agent=best):
            return _agent.select_action(state, training=False)

        result = run_episode(env, policy, seed=seed)
        rewards.append(result.total_reward)
        navs.append(result.final_nav)

    rewards = np.array(rewards)
    navs = np.array(navs)

    mean_reward = float(np.mean(rewards))
    std_reward = float(np.std(rewards, ddof=1))
    median_reward = float(np.median(rewards))
    pct_positive = float(np.mean(rewards > 0)) * 100
    mean_nav = float(np.mean(navs))
    min_nav = float(np.min(navs))
    max_nav = float(np.max(navs))

    # Sharpe of episode rewards (treat each episode as an independent return)
    sharpe_of_rewards = mean_reward / std_reward * math.sqrt(n_episodes) if std_reward > 1e-12 else 0.0

    print(f"{'='*60}")
    print(f"  Held-Out Evaluation Results ({n_episodes} episodes)")
    print(f"{'='*60}")
    print(f"  Mean Reward (Sharpe-based):  {mean_reward:+.4f}")
    print(f"  Std Reward:                  {std_reward:.4f}")
    print(f"  Median Reward:               {median_reward:+.4f}")
    print(f"  % Episodes Positive:         {pct_positive:.1f}%")
    print(f"  Reward Sharpe (cross-ep):    {sharpe_of_rewards:.4f}")
    print(f"  Mean Final NAV:              {mean_nav:.2f}")
    print(f"  NAV Range:                   [{min_nav:.2f}, {max_nav:.2f}]")
    print(f"{'='*60}")
    print()

    # Per-episode detail
    print("  Episode breakdown (first 20):")
    print(f"  {'Seed':>8}  {'Reward':>10}  {'NAV':>10}")
    print(f"  {'----':>8}  {'------':>10}  {'---':>10}")
    for i in range(min(20, n_episodes)):
        print(f"  {seed_offset + i:>8}  {rewards[i]:>+10.4f}  {navs[i]:>10.2f}")
    if n_episodes > 20:
        print(f"  ... ({n_episodes - 20} more episodes)")

    return {
        "mean_reward": mean_reward,
        "std_reward": std_reward,
        "median_reward": median_reward,
        "pct_positive": pct_positive,
        "mean_nav": mean_nav,
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", default="checkpoints/checkpoint_gen0050.pt")
    parser.add_argument("--episodes", type=int, default=50)
    parser.add_argument("--seed-offset", type=int, default=100_000)
    args = parser.parse_args()
    evaluate_holdout(args.checkpoint, args.episodes, args.seed_offset)
