#!/usr/bin/env python3
"""Run a small ablation batch and score checkpoints on cached real windows.

This is meant for fast, repeatable comparisons between a few config variants
using the same strict cached real-data evaluation windows.
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import os
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List

from evaluate_real_market import evaluate_agent_on_env, load_best_agent
from env.real_data import generate_real_dataset_windowed
from env.trading_env import TradingEnv
from training.config import Config, load_config
from training.trainer import Trainer


@dataclass(frozen=True)
class Variant:
    name: str
    description: str
    overrides: Dict[str, Any]


def deep_update(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively update a nested dict."""
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_update(base[key], value)
        else:
            base[key] = value
    return base


def build_variants() -> List[Variant]:
    """Return the first-pass generalization ablations."""
    return [
        Variant(
            name="base_longer",
            description="Current strict-real conservative setup with more training runway.",
            overrides={},
        ),
        Variant(
            name="reward_softened",
            description="Slightly softer no-trade penalties to encourage selective participation.",
            overrides={
                "reward": {
                    "participation_bonus": 0.003,
                    "inactivity_penalty": 0.005,
                    "turnover_penalty_coeff": 0.15,
                },
            },
        ),
        Variant(
            name="larger_network",
            description="More capacity while keeping the rest of the conservative recipe intact.",
            overrides={
                "network": {
                    "hidden_sizes": [256, 128, 64],
                    "use_attention": False,
                },
            },
        ),
    ]


def make_config(
    base_config_path: str | None,
    variant: Variant,
    cache_date: str,
    n_agents: int,
    episodes_per_agent: int,
    n_generations: int,
    n_val_episodes: int,
) -> Config:
    base = load_config(base_config_path)
    data = copy.deepcopy(base._data)
    deep_update(
        data,
        {
            "population": {
                "n_agents": n_agents,
                "episodes_per_agent": episodes_per_agent,
                "n_generations": n_generations,
            },
            "validation": {
                "n_val_episodes": n_val_episodes,
            },
            "data": {
                "mode": "real_strict",
                "strict_real_data": True,
                "end_date": cache_date,
            },
        },
    )
    deep_update(data, variant.overrides)
    return Config(_data=data)


def evaluate_checkpoint(
    checkpoint_path: str,
    windows,
    n_eval_episodes: int,
) -> Dict[str, float]:
    agent, meta = load_best_agent(checkpoint_path)
    env = TradingEnv(
        sector="All",
        lookback=252,
        episode_length=252,
        data_mode="real_strict",
        strict_real_data=True,
        real_data_cache_dir=".data_cache",
        tx_cost_bps=5,
        max_position=0.05,
        max_gross_exposure=1.50,
        stop_loss=0.03,
    )
    env._real_windows = windows
    results = evaluate_agent_on_env(agent, env, n_episodes=min(n_eval_episodes, len(windows)))
    results["checkpoint"] = checkpoint_path
    results["val_sharpe"] = float(meta.get("extra", {}).get("val_sharpe", 0.0))
    return results


def run_variant(
    variant: Variant,
    base_config_path: str | None,
    output_root: str,
    cache_date: str,
    windows,
    n_agents: int,
    episodes_per_agent: int,
    n_generations: int,
    n_val_episodes: int,
    n_eval_episodes: int,
) -> Dict[str, Any]:
    checkpoint_dir = os.path.join(output_root, variant.name)
    os.makedirs(checkpoint_dir, exist_ok=True)

    logging.info("Running variant %s", variant.name)
    config = make_config(
        base_config_path=base_config_path,
        variant=variant,
        cache_date=cache_date,
        n_agents=n_agents,
        episodes_per_agent=episodes_per_agent,
        n_generations=n_generations,
        n_val_episodes=n_val_episodes,
    )
    trainer = Trainer(
        config=config,
        checkpoint_dir=checkpoint_dir,
        log_path=os.path.join(checkpoint_dir, "training.jsonl"),
    )
    trainer.env._real_windows = windows
    history = trainer.train(n_generations=n_generations)
    final = history[-1] if history else None

    best_val_path = os.path.join(checkpoint_dir, "checkpoint_best_val.pt")
    best_stable_path = os.path.join(checkpoint_dir, "checkpoint_best_stable.pt")
    best_val_metrics = evaluate_checkpoint(best_val_path, windows, n_eval_episodes)
    best_stable_metrics = evaluate_checkpoint(best_stable_path, windows, n_eval_episodes)
    winner = (
        ("best_val", best_val_metrics)
        if best_val_metrics["mean_sharpe"] >= best_stable_metrics["mean_sharpe"]
        else ("best_stable", best_stable_metrics)
    )

    return {
        "name": variant.name,
        "description": variant.description,
        "checkpoint_dir": checkpoint_dir,
        "final_generation": final.generation if final else 0,
        "final_best_fitness": final.best_fitness if final else 0.0,
        "final_mean_fitness": final.mean_fitness if final else 0.0,
        "best_val_eval": best_val_metrics,
        "best_stable_eval": best_stable_metrics,
        "winner_label": winner[0],
        "winner_eval": winner[1],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run MARL ablation batch")
    parser.add_argument("--config", type=str, default=None, help="Base config YAML")
    parser.add_argument("--output-root", type=str, required=True, help="Output directory for all runs")
    parser.add_argument("--cache-date", type=str, default="2026-03-29", help="YYYY-MM-DD cache date to evaluate")
    parser.add_argument("--generations", type=int, default=8, help="Generations per variant")
    parser.add_argument("--n-agents", type=int, default=12, help="Agents per variant")
    parser.add_argument("--episodes-per-agent", type=int, default=4, help="Episodes per agent")
    parser.add_argument("--n-val-episodes", type=int, default=5, help="Validation episodes per validation pass")
    parser.add_argument("--n-eval-episodes", type=int, default=5, help="Cached real episodes for final evaluation")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    eval_date = date.fromisoformat(args.cache_date)
    windows = generate_real_dataset_windowed(
        sector="All",
        total_days=756,
        window_size=252,
        end_date=eval_date,
        cache_dir=".data_cache",
    )
    if not windows:
        raise RuntimeError("No cached real windows found for evaluation")

    os.makedirs(args.output_root, exist_ok=True)
    results = []
    for variant in build_variants():
        results.append(
            run_variant(
                variant=variant,
                base_config_path=args.config,
                output_root=args.output_root,
                cache_date=args.cache_date,
                windows=windows,
                n_agents=args.n_agents,
                episodes_per_agent=args.episodes_per_agent,
                n_generations=args.generations,
                n_val_episodes=args.n_val_episodes,
                n_eval_episodes=args.n_eval_episodes,
            )
        )

    results.sort(key=lambda item: item["winner_eval"]["mean_sharpe"], reverse=True)
    summary_path = os.path.join(args.output_root, "summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump({"cache_date": args.cache_date, "results": results}, f, indent=2)

    print(json.dumps({"cache_date": args.cache_date, "results": results}, indent=2))
    print(f"\nSaved summary to {summary_path}")


if __name__ == "__main__":
    main()
