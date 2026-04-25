#!/usr/bin/env python3
"""Evaluate trained MARL agents on real market data via yfinance.

Loads the best agent from a checkpoint, runs it through TradingEnv in
real-data mode across multiple out-of-sample windows, and reports
performance metrics: Sharpe, total return, max drawdown, win rate.

Usage:
    python3 evaluate_real_market.py
    python3 evaluate_real_market.py --checkpoint checkpoints_v3/checkpoint_best_val.pt
    python3 evaluate_real_market.py --sector Technology --episodes 10
    python3 evaluate_real_market.py --all-checkpoints   # compare all checkpoint dirs
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from typing import Dict, List

import numpy as np
import torch

# Ensure imports resolve
sys.path.insert(0, os.path.dirname(__file__))

from agents.agent_pool import AgentPool
from agents.base_agent import AgentType
from env.trading_env import TradingEnv
from training.checkpoint import load_checkpoint


def evaluate_agent_on_env(
    agent,
    env: TradingEnv,
    n_episodes: int = 10,
    seed_start: int = 2_000_000,
) -> Dict[str, float]:
    """Run one agent through multiple real-data episodes and collect metrics."""
    sharpes: List[float] = []
    returns: List[float] = []
    max_dds: List[float] = []
    win_rates: List[float] = []

    for ep in range(n_episodes):
        seed = seed_start + ep
        obs, _ = env.reset(seed=seed)
        if env._get_info().get("resolved_data_source") != "real":
            raise RuntimeError(
                "Real-market evaluation did not load a valid real dataset. "
                "Run with a populated cache or restore network access."
            )
        done = False
        total_reward = 0.0

        while not done:
            action = agent.select_action(obs, training=False)
            obs, reward, terminated, truncated, info = env.step(action)
            total_reward += reward
            done = terminated or truncated

        # Episode metrics from env internals
        nav_arr = np.array(env._nav_history)
        daily_rets = np.array(env._daily_returns)

        # Sharpe
        if len(daily_rets) >= 2:
            mu = float(np.mean(daily_rets))
            sigma = float(np.std(daily_rets, ddof=1))
            sharpe = (mu / sigma) * math.sqrt(252) if sigma > 1e-12 else 0.0
        else:
            sharpe = 0.0

        # Total return
        total_ret = (nav_arr[-1] / nav_arr[0] - 1.0) if len(nav_arr) > 1 else 0.0

        # Max drawdown
        peak = np.maximum.accumulate(nav_arr)
        dd = (peak - nav_arr) / np.where(peak > 0, peak, 1.0)
        max_dd = float(np.max(dd)) if len(dd) > 0 else 0.0

        # Monthly win rate
        monthly = []
        for i in range(0, len(daily_rets), 21):
            chunk = daily_rets[i : i + 21]
            if len(chunk) > 0:
                monthly.append(float(np.sum(chunk)))
        win_rate = sum(1 for m in monthly if m > 0) / max(len(monthly), 1)

        sharpes.append(sharpe)
        returns.append(total_ret)
        max_dds.append(max_dd)
        win_rates.append(win_rate)

    return {
        "mean_sharpe": float(np.mean(sharpes)),
        "std_sharpe": float(np.std(sharpes)),
        "mean_return": float(np.mean(returns)),
        "mean_max_dd": float(np.mean(max_dds)),
        "mean_win_rate": float(np.mean(win_rates)),
        "best_sharpe": float(np.max(sharpes)),
        "worst_sharpe": float(np.min(sharpes)),
        "n_episodes": n_episodes,
    }


def _infer_architecture(param_count: int) -> tuple[list[int], bool]:
    """Infer hidden sizes and attention flag from checkpoint param count."""
    from agents.actor_critic import ActorCriticNetwork

    candidate_hidden_sizes = [
        [128, 64],
        [256, 128, 64],
        [64, 32],
        [32, 16],
    ]
    for hidden_sizes in candidate_hidden_sizes:
        for use_attn in [True, False]:
            net = ActorCriticNetwork(57, 5, hidden_sizes, use_attention=use_attn)
            if net.n_params() == param_count:
                return hidden_sizes, use_attn
    return [256, 128, 64], True


def load_best_agent(checkpoint_path: str) -> tuple:
    """Load checkpoint and return (best_agent, metadata)."""
    ckpt = torch.load(checkpoint_path, weights_only=False)
    n_agents = ckpt["n_agents"]
    param_count = len(ckpt["agents"][0]["params"])

    # Detect architecture from param count
    hidden_sizes, use_attn = _infer_architecture(param_count)

    # Monkey-patch ActorCriticNetwork default to match checkpoint
    import agents.actor_critic as ac_mod
    _orig_init = ac_mod.ActorCriticNetwork.__init__

    def _patched_init(self, obs_dim=57, n_actions=5, hidden_sizes=None, activation="relu", use_attention=True):
        resolved_hidden_sizes = hidden_sizes or list(hidden_sizes_detected)
        _orig_init(
            self,
            obs_dim,
            n_actions,
            resolved_hidden_sizes,
            activation,
            use_attention=use_attn,
        )

    hidden_sizes_detected = list(hidden_sizes)
    ac_mod.ActorCriticNetwork.__init__ = _patched_init

    pool = AgentPool(
        n_agents=n_agents,
        obs_dim=57,
        n_actions=5,
        hidden_sizes=hidden_sizes_detected,
        use_attention=use_attn,
    )
    meta = load_checkpoint(checkpoint_path, pool)

    # Restore original init
    ac_mod.ActorCriticNetwork.__init__ = _orig_init

    best = pool.ranked()[0]
    return best, meta


def run_evaluation(
    checkpoint_path: str,
    sector: str = "All",
    n_episodes: int = 10,
    lookback: int = 252,
    end_date: str | None = None,
) -> Dict[str, float]:
    """Full evaluation pipeline: load agent, create real env, evaluate."""
    print(f"\n{'='*60}")
    print(f"Checkpoint : {checkpoint_path}")
    print(f"Sector     : {sector}")
    print(f"Episodes   : {n_episodes}")
    print(f"Lookback   : {lookback} days")
    print(f"{'='*60}")

    # Load best agent
    agent, meta = load_best_agent(checkpoint_path)
    gen = meta["generation"]
    extra = meta.get("extra", {})
    print(f"Agent      : {agent.agent_id} (gen {gen}, fitness {agent.fitness:.4f})")
    if extra.get("val_sharpe"):
        print(f"Val Sharpe : {extra['val_sharpe']:.4f}")

    # Create environment in real-data mode
    env = TradingEnv(
        sector=sector,
        lookback=lookback,
        episode_length=lookback,
        data_mode="real_strict",
        real_data_cache_dir=".data_cache",
        real_data_end_date=end_date,
        strict_real_data=True,
        tx_cost_bps=5,
        max_position=0.05,
        max_gross_exposure=1.50,
        stop_loss=0.03,
    )

    print(f"\nFetching real market data...")
    results = evaluate_agent_on_env(agent, env, n_episodes=n_episodes)

    # Print results
    print(f"\n{'─'*40}")
    print(f"  REAL MARKET RESULTS ({n_episodes} episodes)")
    print(f"{'─'*40}")
    print(f"  Mean Sharpe    : {results['mean_sharpe']:+.4f} ± {results['std_sharpe']:.4f}")
    print(f"  Best Sharpe    : {results['best_sharpe']:+.4f}")
    print(f"  Worst Sharpe   : {results['worst_sharpe']:+.4f}")
    print(f"  Mean Return    : {results['mean_return']:+.2%}")
    print(f"  Mean Max DD    : {results['mean_max_dd']:.2%}")
    print(f"  Mean Win Rate  : {results['mean_win_rate']:.1%}")
    print(f"{'─'*40}")

    # Overfitting check
    val_sharpe = extra.get("val_sharpe", 0.0)
    if val_sharpe and val_sharpe > 0:
        ratio = results["mean_sharpe"] / val_sharpe
        label = "OK" if ratio > 0.5 else "OVERFITTING"
        print(f"  OOS/Val ratio  : {ratio:.2f} ({label})")

    return results


def find_checkpoint_dirs() -> List[str]:
    """Find all checkpoint directories with a best_val checkpoint."""
    base = os.path.dirname(__file__)
    dirs = []
    for name in sorted(os.listdir(base)):
        path = os.path.join(base, name)
        if os.path.isdir(path) and name.startswith("checkpoints"):
            best = os.path.join(path, "checkpoint_best_val.pt")
            if os.path.exists(best):
                dirs.append(best)
    return dirs


def main():
    parser = argparse.ArgumentParser(description="Evaluate MARL agents on real market data")
    parser.add_argument(
        "--checkpoint", "-c",
        default="checkpoints_tuned/checkpoint_best_val.pt",
        help="Path to checkpoint file",
    )
    parser.add_argument("--sector", "-s", default="All", help="Sector or 'All'")
    parser.add_argument("--episodes", "-n", type=int, default=10, help="Number of episodes")
    parser.add_argument("--lookback", type=int, default=252, help="Lookback days per episode")
    parser.add_argument("--end-date", type=str, default=None, help="Pinned YYYY-MM-DD for cached real data")
    parser.add_argument(
        "--all-checkpoints", action="store_true",
        help="Evaluate all checkpoint dirs and compare",
    )
    args = parser.parse_args()

    if args.all_checkpoints:
        ckpts = find_checkpoint_dirs()
        if not ckpts:
            print("No checkpoint directories found.")
            return
        print(f"Found {len(ckpts)} checkpoints to evaluate\n")
        all_results = {}
        for cp in ckpts:
            label = os.path.basename(os.path.dirname(cp))
            results = run_evaluation(cp, args.sector, args.episodes, args.lookback, args.end_date)
            all_results[label] = results

        # Summary table
        print(f"\n{'='*60}")
        print(f"  COMPARISON ACROSS CHECKPOINTS")
        print(f"{'='*60}")
        print(f"  {'Checkpoint':<25} {'Sharpe':>8} {'Return':>8} {'MaxDD':>8} {'WinRate':>8}")
        print(f"  {'─'*25} {'─'*8} {'─'*8} {'─'*8} {'─'*8}")
        for label, r in sorted(all_results.items(), key=lambda x: x[1]["mean_sharpe"], reverse=True):
            print(
                f"  {label:<25} {r['mean_sharpe']:>+8.3f} "
                f"{r['mean_return']:>+7.1%} {r['mean_max_dd']:>7.1%} "
                f"{r['mean_win_rate']:>7.0%}"
            )
    else:
        run_evaluation(args.checkpoint, args.sector, args.episodes, args.lookback, args.end_date)


if __name__ == "__main__":
    main()
