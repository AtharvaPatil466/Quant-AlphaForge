"""Compute actual annualized Sharpe ratio on held-out episodes."""

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
from training.checkpoint import load_checkpoint


def eval_sharpe(checkpoint_path: str, n_episodes: int = 50, seed_offset: int = 100_000,
                stochastic: bool = False):
    pool = AgentPool(n_agents=30, agent_type=AgentType.ACTOR_CRITIC,
                     obs_dim=57, n_actions=5, hidden_sizes=[256, 128, 64])
    meta = load_checkpoint(checkpoint_path, pool)
    best = pool.best()

    mode = "stochastic" if stochastic else "greedy"
    print(f"Checkpoint gen {meta['generation']}, agent {best.agent_id} ({mode})")
    print(f"Evaluating {n_episodes} held-out episodes\n")

    env = TradingEnv(episode_length=252)

    all_daily_returns = []  # all daily returns pooled
    per_episode_sharpes = []
    per_episode_total_returns = []
    per_episode_max_dd = []

    for ep in range(n_episodes):
        seed = seed_offset + ep
        obs, _ = env.reset(seed=seed)
        done = False
        while not done:
            state_t = torch.FloatTensor(obs).unsqueeze(0)
            with torch.no_grad():
                if stochastic:
                    action_t, _, _, _ = best.ac_network.get_action_and_value(state_t)
                    action = action_t.item()
                else:
                    probs = best.ac_network.get_policy(state_t)
                    action = probs.argmax(dim=-1).item()
            obs, reward, terminated, truncated, info = env.step(action)
            done = terminated or truncated

        daily_rets = np.array(env._daily_returns, dtype=np.float64)
        nav_hist = np.array(env._nav_history, dtype=np.float64)

        all_daily_returns.extend(daily_rets.tolist())

        # Per-episode annualized Sharpe
        if len(daily_rets) > 1:
            mu = np.mean(daily_rets)
            sigma = np.std(daily_rets, ddof=1)
            ep_sharpe = (mu / sigma) * math.sqrt(252) if sigma > 1e-12 else 0.0
        else:
            ep_sharpe = 0.0
        per_episode_sharpes.append(ep_sharpe)

        # Total return
        total_ret = (nav_hist[-1] / nav_hist[0]) - 1.0
        per_episode_total_returns.append(total_ret)

        # Max drawdown
        peak = np.maximum.accumulate(nav_hist)
        dd = (peak - nav_hist) / np.where(peak > 0, peak, 1.0)
        per_episode_max_dd.append(float(np.max(dd)))

    # Pooled Sharpe (all daily returns across all episodes)
    all_rets = np.array(all_daily_returns)
    pooled_mu = np.mean(all_rets)
    pooled_sigma = np.std(all_rets, ddof=1)
    pooled_sharpe = (pooled_mu / pooled_sigma) * math.sqrt(252) if pooled_sigma > 1e-12 else 0.0

    ep_sharpes = np.array(per_episode_sharpes)
    total_rets = np.array(per_episode_total_returns)
    max_dds = np.array(per_episode_max_dd)

    print(f"{'='*60}")
    print(f"  Held-Out Sharpe Analysis ({n_episodes} episodes)")
    print(f"{'='*60}")
    print(f"  Pooled Annualized Sharpe:    {pooled_sharpe:+.4f}")
    print(f"  Mean Per-Episode Sharpe:     {np.mean(ep_sharpes):+.4f}")
    print(f"  Median Per-Episode Sharpe:   {np.median(ep_sharpes):+.4f}")
    print(f"  Sharpe Std:                  {np.std(ep_sharpes, ddof=1):.4f}")
    print(f"  % Episodes Sharpe > 0:       {np.mean(ep_sharpes > 0) * 100:.1f}%")
    print(f"  % Episodes Sharpe > 0.5:     {np.mean(ep_sharpes > 0.5) * 100:.1f}%")
    print(f"  % Episodes Sharpe > 1.0:     {np.mean(ep_sharpes > 1.0) * 100:.1f}%")
    print(f"  Mean Total Return:           {np.mean(total_rets)*100:+.2f}%")
    print(f"  Mean Max Drawdown:           {np.mean(max_dds)*100:.2f}%")
    print(f"  Total daily returns:         {len(all_rets)}")
    print(f"{'='*60}")
    print()
    print(f"  Per-episode Sharpe distribution:")
    print(f"    Min:  {np.min(ep_sharpes):+.4f}")
    print(f"    25%:  {np.percentile(ep_sharpes, 25):+.4f}")
    print(f"    50%:  {np.median(ep_sharpes):+.4f}")
    print(f"    75%:  {np.percentile(ep_sharpes, 75):+.4f}")
    print(f"    Max:  {np.max(ep_sharpes):+.4f}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", default=None)
    parser.add_argument("--episodes", type=int, default=50)
    parser.add_argument("--seed-offset", type=int, default=100_000)
    parser.add_argument("--stochastic", action="store_true", help="Use stochastic policy (sample from distribution)")
    args = parser.parse_args()

    checkpoints = [args.checkpoint] if args.checkpoint else [
        "checkpoints/checkpoint_gen0010.pt",
        "checkpoints/checkpoint_gen0020.pt",
        "checkpoints/checkpoint_gen0030.pt",
        "checkpoints/checkpoint_gen0040.pt",
        "checkpoints/checkpoint_gen0050.pt",
    ]
    for ckpt in checkpoints:
        if os.path.exists(ckpt):
            eval_sharpe(ckpt, args.episodes, args.seed_offset, stochastic=args.stochastic)
            print()
