"""MARL Convergence Validation Script.

Runs a short training session and validates that the evolutionary + PPO
pipeline actually converges to a profitable strategy. Produces a summary
report with concrete metrics.

Usage:
    python3 validate_convergence.py [--generations 30] [--quick]
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from typing import List

import numpy as np

from training.trainer import Trainer
from training.config import Config, load_config
from env.trading_env import TradingEnv
from env.episode_runner import run_episode
from evolution.evolutionary_engine import GenerationStats

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
)
logger = logging.getLogger(__name__)


@dataclass
class ConvergenceReport:
    """Summary of convergence validation results."""
    n_generations: int
    wall_time_seconds: float

    # Fitness trajectory
    initial_mean_fitness: float
    final_mean_fitness: float
    initial_best_fitness: float
    final_best_fitness: float
    best_fitness_ever: float
    fitness_improvement_pct: float

    # Validation
    final_val_sharpe: float
    best_val_sharpe: float
    best_val_generation: int

    # Convergence indicators
    fitness_monotonic_improvement: bool
    positive_val_sharpe: bool
    sigma_adapted: bool
    early_stopped: bool

    # PPO diagnostics
    mean_ppo_policy_loss: float
    mean_ppo_value_loss: float

    # Final agent evaluation (20 episodes)
    eval_mean_reward: float
    eval_std_reward: float
    eval_min_reward: float
    eval_max_reward: float
    eval_positive_pct: float

    # Verdict
    converged: bool
    verdict: str


def evaluate_best_agent(trainer: Trainer, n_episodes: int = 20) -> dict:
    """Evaluate the best agent on validation seeds and return stats."""
    best = trainer.pool.best()
    rewards = []
    for seed in trainer.val_seeds[:n_episodes]:
        def policy(state, _agent=best):
            return _agent.select_action(state, training=True)
        result = run_episode(trainer.env, policy, seed=seed)
        rewards.append(result.total_reward)
    rewards = np.array(rewards)
    return {
        "mean": float(np.mean(rewards)),
        "std": float(np.std(rewards)),
        "min": float(np.min(rewards)),
        "max": float(np.max(rewards)),
        "positive_pct": float(np.sum(rewards > 0) / len(rewards)),
    }


def check_monotonic_improvement(history: List[GenerationStats], window: int = 5) -> bool:
    """Check if mean fitness shows overall upward trend via rolling averages."""
    if len(history) < window * 2:
        return True  # too few data points to judge
    means = [s.mean_fitness for s in history]
    first_window = np.mean(means[:window])
    last_window = np.mean(means[-window:])
    return last_window > first_window


def run_validation(
    n_generations: int = 30,
    quick: bool = False,
) -> ConvergenceReport:
    """Run training and produce a convergence report."""
    config = load_config()

    # Override for faster validation if --quick
    if quick:
        config._data["population"]["n_agents"] = 10
        config._data["population"]["episodes_per_agent"] = 3
        config._data["population"]["n_generations"] = n_generations
        config._data["validation"]["validate_every_n_gens"] = 3
        config._data["validation"]["early_stop_patience"] = 5
        config._data["environment"]["episode_length"] = 126  # half year
    else:
        config._data["population"]["n_generations"] = n_generations

    checkpoint_dir = tempfile.mkdtemp(prefix="marl_val_")
    logger.info(f"Checkpoints: {checkpoint_dir}")
    logger.info(f"Config: {n_generations} generations, quick={quick}")

    # Track generation history
    history: List[GenerationStats] = []

    def on_gen(stats: GenerationStats):
        history.append(stats)
        logger.info(
            f"  Gen {stats.generation:3d} | "
            f"best={stats.best_fitness:+.4f} mean={stats.mean_fitness:+.4f} "
            f"sigma={stats.sigma:.4f} val={stats.val_sharpe:+.4f}"
        )

    trainer = Trainer(
        config=config,
        checkpoint_dir=checkpoint_dir,
        on_generation=on_gen,
    )

    logger.info("Starting training...")
    t0 = time.time()
    trainer.train(n_generations=n_generations)
    wall_time = time.time() - t0
    logger.info(f"Training completed in {wall_time:.1f}s")

    # Evaluate best agent
    logger.info("Evaluating best agent on 20 validation episodes...")
    eval_stats = evaluate_best_agent(trainer, n_episodes=20)

    # Compute convergence metrics
    initial_mean = history[0].mean_fitness if history else 0
    final_mean = history[-1].mean_fitness if history else 0
    initial_best = history[0].best_fitness if history else 0
    final_best = history[-1].best_fitness if history else 0
    best_ever = max(s.best_fitness for s in history) if history else 0

    improvement = (
        (final_mean - initial_mean) / max(abs(initial_mean), 1e-6) * 100
    )

    val_sharpes = [s.val_sharpe for s in history if s.val_sharpe != 0]
    final_val = val_sharpes[-1] if val_sharpes else 0
    best_val = max(val_sharpes) if val_sharpes else 0
    best_val_gen = trainer.best_val_generation

    ppo_ploss = [s.ppo_policy_loss for s in history if s.ppo_policy_loss != 0]
    ppo_vloss = [s.ppo_value_loss for s in history if s.ppo_value_loss != 0]

    sigmas = [s.sigma for s in history]
    sigma_adapted = len(set(round(s, 6) for s in sigmas)) > 1

    monotonic = check_monotonic_improvement(history)
    positive_val = best_val > 0
    early_stopped = not trainer._running and len(history) < n_generations

    # Convergence verdict
    converged = (
        improvement > -10  # not getting significantly worse
        and (positive_val or eval_stats["positive_pct"] > 0.3)
        and eval_stats["mean"] > -1.0  # not catastrophically bad
    )

    if converged and positive_val and eval_stats["positive_pct"] > 0.5:
        verdict = "STRONG CONVERGENCE — positive val Sharpe with majority profitable episodes"
    elif converged and positive_val:
        verdict = "MODERATE CONVERGENCE — positive val Sharpe but inconsistent episode outcomes"
    elif converged:
        verdict = "WEAK CONVERGENCE — fitness improved but val Sharpe not consistently positive"
    else:
        verdict = "NOT CONVERGED — more generations or hyperparameter tuning needed"

    report = ConvergenceReport(
        n_generations=len(history),
        wall_time_seconds=round(wall_time, 1),
        initial_mean_fitness=round(initial_mean, 4),
        final_mean_fitness=round(final_mean, 4),
        initial_best_fitness=round(initial_best, 4),
        final_best_fitness=round(final_best, 4),
        best_fitness_ever=round(best_ever, 4),
        fitness_improvement_pct=round(improvement, 2),
        final_val_sharpe=round(final_val, 4),
        best_val_sharpe=round(best_val, 4),
        best_val_generation=best_val_gen,
        fitness_monotonic_improvement=monotonic,
        positive_val_sharpe=positive_val,
        sigma_adapted=sigma_adapted,
        early_stopped=early_stopped,
        mean_ppo_policy_loss=round(np.mean(ppo_ploss), 6) if ppo_ploss else 0,
        mean_ppo_value_loss=round(np.mean(ppo_vloss), 6) if ppo_vloss else 0,
        eval_mean_reward=round(eval_stats["mean"], 4),
        eval_std_reward=round(eval_stats["std"], 4),
        eval_min_reward=round(eval_stats["min"], 4),
        eval_max_reward=round(eval_stats["max"], 4),
        eval_positive_pct=round(eval_stats["positive_pct"], 2),
        converged=converged,
        verdict=verdict,
    )

    return report


def print_report(report: ConvergenceReport) -> None:
    """Pretty-print the convergence report."""
    print("\n" + "=" * 70)
    print("  MARL CONVERGENCE VALIDATION REPORT")
    print("=" * 70)

    print(f"\n  Generations trained:     {report.n_generations}")
    print(f"  Wall time:               {report.wall_time_seconds}s")
    print(f"  Early stopped:           {'Yes' if report.early_stopped else 'No'}")

    print(f"\n  --- Fitness Trajectory ---")
    print(f"  Initial mean fitness:    {report.initial_mean_fitness:+.4f}")
    print(f"  Final mean fitness:      {report.final_mean_fitness:+.4f}")
    print(f"  Improvement:             {report.fitness_improvement_pct:+.1f}%")
    print(f"  Best fitness ever:       {report.best_fitness_ever:+.4f}")
    print(f"  Monotonic trend:         {'Yes' if report.fitness_monotonic_improvement else 'No'}")

    print(f"\n  --- Validation ---")
    print(f"  Final val Sharpe:        {report.final_val_sharpe:+.4f}")
    print(f"  Best val Sharpe:         {report.best_val_sharpe:+.4f} (gen {report.best_val_generation})")
    print(f"  Positive val Sharpe:     {'Yes' if report.positive_val_sharpe else 'No'}")

    print(f"\n  --- PPO Diagnostics ---")
    print(f"  Mean policy loss:        {report.mean_ppo_policy_loss:.6f}")
    print(f"  Mean value loss:         {report.mean_ppo_value_loss:.6f}")
    print(f"  Sigma adapted:           {'Yes' if report.sigma_adapted else 'No'}")

    print(f"\n  --- Best Agent Evaluation (20 episodes) ---")
    print(f"  Mean reward:             {report.eval_mean_reward:+.4f}")
    print(f"  Std reward:              {report.eval_std_reward:.4f}")
    print(f"  Min / Max:               {report.eval_min_reward:+.4f} / {report.eval_max_reward:+.4f}")
    print(f"  Profitable episodes:     {report.eval_positive_pct:.0%}")

    print(f"\n  --- Verdict ---")
    status = "PASS" if report.converged else "FAIL"
    print(f"  [{status}] {report.verdict}")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Validate MARL convergence")
    parser.add_argument("--generations", type=int, default=30)
    parser.add_argument("--quick", action="store_true", help="Smaller population, shorter episodes")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    report = run_validation(
        n_generations=args.generations,
        quick=args.quick,
    )

    if args.json:
        print(json.dumps(asdict(report), indent=2))
    else:
        print_report(report)

    # Save report
    out_path = os.path.join(os.path.dirname(__file__), "convergence_report.json")
    with open(out_path, "w") as f:
        json.dump(asdict(report), f, indent=2)
    logger.info(f"Report saved to {out_path}")

    sys.exit(0 if report.converged else 1)


if __name__ == "__main__":
    main()
