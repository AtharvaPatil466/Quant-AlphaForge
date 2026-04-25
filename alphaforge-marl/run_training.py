"""Run a full MARL training session from the command line.

Usage:
    python3 run_training.py                    # 50 generations (default config)
    python3 run_training.py --generations 10   # custom generation count
    python3 run_training.py --quick            # 5 generations, small population (smoke test)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time

# Ensure imports work
_MARL = os.path.dirname(__file__)
_ROOT = os.path.dirname(os.path.dirname(__file__))
for p in [os.path.join(_ROOT, "alphaforge-python"), _MARL]:
    if p not in sys.path:
        sys.path.insert(0, p)

from training.config import Config, load_config
from training.trainer import Trainer
from evolution.evolutionary_engine import GenerationStats


def main():
    parser = argparse.ArgumentParser(description="AlphaForge MARL Training")
    parser.add_argument("--generations", type=int, default=None, help="Number of generations")
    parser.add_argument("--config", type=str, default=None, help="Path to config YAML")
    parser.add_argument("--quick", action="store_true", help="Quick smoke test (5 gen, 4 agents)")
    parser.add_argument("--checkpoint-dir", type=str, default="checkpoints", help="Checkpoint directory")
    parser.add_argument("--resume", type=str, default=None, help="Resume from checkpoint path")
    parser.add_argument(
        "--real-only",
        action="store_true",
        help="Train with strict real market data only (no synthetic fallback)",
    )
    parser.add_argument(
        "--reference-strategy",
        type=str,
        default=None,
        help="Reward reference strategy for relative performance (e.g. equal_weight, ridge_excess_top5)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.quick:
        config = Config(_data={
            "population": {
                "n_agents": 6,
                "episodes_per_agent": 3,
                "n_generations": 5,
                "elite_fraction": 0.20,
                "survivor_fraction": 0.50,
            },
            "mutation": {
                "sigma_init": 0.005,
                "sigma_min": 0.001,
                "sigma_max": 0.03,
                "diversity_threshold": 0.2,
                "crossover_prob": 0.30,
            },
            "ppo": {"learning_rate": 3e-4},
            "dqn": {},
            "environment": {
                "episode_length": 50,
                "max_position": 0.05,
                "max_gross_exposure": 1.50,
                "stop_loss": 0.03,
                "tx_cost_bps": 5,
                "obs_dim": 57,
                "n_actions": 5,
                "catastrophic_nav": 0.50,
            },
            "reward": {
                "drawdown_penalty_coeff": 2.0,
                "drawdown_threshold": 0.10,
                "consistency_bonus": 0.20,
                "consistency_threshold": 0.55,
                "turnover_penalty_coeff": 0.10,
            },
            "bandit": {
                "n_regimes": 2,
                "bandit_prior_alpha": 1.0,
                "bandit_prior_beta": 1.0,
            },
            "network": {
                "hidden_sizes": [64, 32],
                "activation": "relu",
            },
            "alpha_engine": {"base_seed": 42},
        })
        n_gen = 5
    else:
        config = load_config(args.config)
        n_gen = args.generations or config.population.get("n_generations", 50)

    if args.real_only:
        config._data.setdefault("data", {})
        config._data["data"]["mode"] = "real_strict"
        config._data["data"]["strict_real_data"] = True
    if args.reference_strategy:
        config._data.setdefault("reward", {})
        config._data["reward"]["relative_reference_strategy"] = args.reference_strategy

    log_path = os.path.join(args.checkpoint_dir, "training.jsonl")

    def on_generation(stats: GenerationStats):
        bar_len = 30
        filled = int(bar_len * stats.generation / n_gen)
        bar = "█" * filled + "░" * (bar_len - filled)
        val_str = f"val={stats.val_sharpe:+.4f}" if stats.val_sharpe != 0.0 else "val=--"
        print(
            f"  [{bar}] Gen {stats.generation:3d}/{n_gen} | "
            f"best={stats.best_fitness:+.4f} | mean={stats.mean_fitness:+.4f} | "
            f"σ_mut={stats.sigma:.4f} | ppo_loss={stats.ppo_policy_loss:.4f} | "
            f"{val_str} | {stats.best_agent_id}"
        )

    trainer = Trainer(
        config=config,
        checkpoint_dir=args.checkpoint_dir,
        log_path=log_path,
        on_generation=on_generation,
    )

    if args.resume:
        trainer.resume(args.resume)
        print(f"Resumed from generation {trainer.generation}")

    print(f"\n{'='*70}")
    print(f"  AlphaForge MARL Training")
    print(f"  Agents: {config.population.get('n_agents', 30)} | "
          f"Generations: {n_gen} | "
          f"Episodes/agent: {config.population.get('episodes_per_agent', 10)}")
    print(f"  Network: {config.network.get('hidden_sizes', [256,128,64])} | "
          f"Episode length: {config.environment.get('episode_length', 252)}d")
    print(f"{'='*70}\n")

    t0 = time.time()
    history = trainer.train(n_generations=n_gen)
    elapsed = time.time() - t0

    if history:
        final = history[-1]
        print(f"\n{'='*70}")
        print(f"  Training Complete")
        print(f"  Generations: {final.generation} | Time: {elapsed:.1f}s")
        print(f"  Best Fitness:  {final.best_fitness:+.4f} (agent: {final.best_agent_id})")
        print(f"  Mean Fitness:  {final.mean_fitness:+.4f}")
        print(f"  Fitness Std:   {final.fitness_std:.4f}")
        print(f"  Final Sigma:   {final.sigma:.4f}")
        print(f"  Checkpoints:   {args.checkpoint_dir}/")
        print(f"{'='*70}\n")
    else:
        print("No training history generated.")


if __name__ == "__main__":
    main()
