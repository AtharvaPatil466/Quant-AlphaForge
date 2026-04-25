#!/usr/bin/env python3
"""Run repeated retrains and summarize OOS stability on pinned cached windows."""

from __future__ import annotations

import argparse
import copy
import json
import os
from datetime import date

from env.real_data import generate_real_dataset_windowed
from training.benchmark import evaluate_checkpoint_cost_grid
from training.config import load_config
from training.trainer import Trainer


def main() -> None:
    parser = argparse.ArgumentParser(description="Repeated retrains for MARL stability checks")
    parser.add_argument("--config", required=True, help="Config YAML path")
    parser.add_argument("--output-root", required=True, help="Directory for repeated run outputs")
    parser.add_argument("--cache-date", default="2026-03-29", help="Pinned YYYY-MM-DD cache date")
    parser.add_argument("--runs", type=int, default=3, help="Number of repeated retrains")
    parser.add_argument("--generations", type=int, default=None, help="Override generations")
    parser.add_argument("--cost-bps", type=int, default=5, help="OOS evaluation transaction cost")
    args = parser.parse_args()

    eval_date = date.fromisoformat(args.cache_date)
    windows = generate_real_dataset_windowed(
        sector="All",
        total_days=756,
        window_size=252,
        end_date=eval_date,
        cache_dir=".data_cache",
    )

    os.makedirs(args.output_root, exist_ok=True)
    base = load_config(args.config)
    results = []
    for run_idx in range(args.runs):
        cfg = load_config(args.config)
        cfg._data = copy.deepcopy(base._data)
        cfg._data.setdefault("alpha_engine", {})
        cfg._data["alpha_engine"]["base_seed"] = int(base.alpha_engine.get("base_seed", 42)) + run_idx
        cfg._data.setdefault("seeds", {})
        seed_offset = run_idx * 1_000_000
        cfg._data["seeds"]["train_min"] = int(base.seeds.get("train_min", 0)) + seed_offset
        cfg._data["seeds"]["train_max"] = int(base.seeds.get("train_max", 899999)) + seed_offset
        cfg._data["seeds"]["val_min"] = int(base.seeds.get("val_min", 900000)) + seed_offset
        cfg._data["seeds"]["val_max"] = int(base.seeds.get("val_max", 999999)) + seed_offset
        cfg._data.setdefault("data", {})
        cfg._data["data"]["end_date"] = args.cache_date

        checkpoint_dir = os.path.join(args.output_root, f"run_{run_idx:02d}")
        trainer = Trainer(config=cfg, checkpoint_dir=checkpoint_dir, log_path=os.path.join(checkpoint_dir, "training.jsonl"))
        history = trainer.train(n_generations=args.generations or cfg.population.get("n_generations", 20))
        checkpoint_path = os.path.join(checkpoint_dir, "checkpoint_best_val.pt")
        metrics = evaluate_checkpoint_cost_grid(checkpoint_path, windows, [args.cost_bps])[str(args.cost_bps)]
        results.append({
            "run": run_idx,
            "checkpoint": checkpoint_path,
            "best_val_sharpe": trainer.best_val_sharpe,
            "oos_metrics": metrics,
            "final_generation": history[-1].generation if history else 0,
        })

    sharpe_values = [item["oos_metrics"].get("sharpe", 0.0) for item in results]
    summary = {
        "cache_date": args.cache_date,
        "runs": results,
        "mean_oos_sharpe": sum(sharpe_values) / max(len(sharpe_values), 1),
        "min_oos_sharpe": min(sharpe_values) if sharpe_values else 0.0,
        "max_oos_sharpe": max(sharpe_values) if sharpe_values else 0.0,
    }
    out_path = os.path.join(args.output_root, "stability_summary.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))
    print(f"\nSaved stability summary to {out_path}")


if __name__ == "__main__":
    main()
