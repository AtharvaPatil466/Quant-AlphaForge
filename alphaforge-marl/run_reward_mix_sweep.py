#!/usr/bin/env python3
"""Sweep benchmark-relative reward mix values and benchmark the results."""

from __future__ import annotations

import argparse
import copy
import json
import os
from datetime import date
from typing import Any, Dict, List

from env.real_data import generate_real_dataset_windowed
from training.benchmark import build_benchmark_report
from training.config import Config, load_config
from training.trainer import Trainer


def _slugify_mix(value: float) -> str:
    return f"{value:.2f}".replace(".", "")


def _make_config(base: Config, mix: float, cache_date: str) -> Config:
    data = copy.deepcopy(base._data)
    data.setdefault("reward", {})
    data["reward"]["benchmark_relative_mix"] = float(mix)
    data.setdefault("data", {})
    data["data"]["mode"] = "real_strict"
    data["data"]["strict_real_data"] = True
    data["data"]["end_date"] = cache_date
    return Config(_data=data)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sweep benchmark-relative reward mix values")
    parser.add_argument("--config", required=True, help="Base config YAML path")
    parser.add_argument("--output-root", required=True, help="Directory for all sweep outputs")
    parser.add_argument("--cache-date", default="2026-03-29", help="Pinned YYYY-MM-DD cache date")
    parser.add_argument("--generations", type=int, default=20, help="Generations per mix")
    parser.add_argument(
        "--mixes",
        default="0.25,0.35,0.50",
        help="Comma-separated benchmark_relative_mix values",
    )
    parser.add_argument(
        "--costs",
        default="5,10,25,50",
        help="Comma-separated transaction cost grid for benchmark report",
    )
    args = parser.parse_args()

    os.makedirs(args.output_root, exist_ok=True)
    mixes = [float(item.strip()) for item in args.mixes.split(",") if item.strip()]
    costs = [int(item.strip()) for item in args.costs.split(",") if item.strip()]
    base = load_config(args.config)

    eval_date = date.fromisoformat(args.cache_date)
    windows = generate_real_dataset_windowed(
        sector=base.data.get("sector", "All"),
        total_days=max(756, int(base.data.get("lookback_days", 252)) * 3),
        window_size=int(base.data.get("lookback_days", 252)),
        end_date=eval_date,
        cache_dir=base.data.get("cache_dir", ".data_cache"),
    )

    checkpoint_paths: Dict[str, str] = {}
    summary: Dict[str, Any] = {
        "cache_date": args.cache_date,
        "mixes": [],
    }

    for mix in mixes:
        label = f"mix_{_slugify_mix(mix)}"
        checkpoint_dir = os.path.join(args.output_root, label)
        cfg = _make_config(base, mix, args.cache_date)
        trainer = Trainer(
            config=cfg,
            checkpoint_dir=checkpoint_dir,
            log_path=os.path.join(checkpoint_dir, "training.jsonl"),
        )
        history = trainer.train(n_generations=args.generations)

        best_val = os.path.join(checkpoint_dir, "checkpoint_best_val.pt")
        best_stable = os.path.join(checkpoint_dir, "checkpoint_best_stable.pt")
        checkpoint_paths[f"{label}_best_val"] = best_val
        checkpoint_paths[f"{label}_best_stable"] = best_stable

        summary["mixes"].append({
            "label": label,
            "benchmark_relative_mix": mix,
            "checkpoint_dir": checkpoint_dir,
            "best_val_checkpoint": best_val,
            "best_stable_checkpoint": best_stable,
            "best_val_generation": trainer.best_val_generation,
            "best_val_sharpe": trainer.best_val_sharpe,
            "best_stable_generation": trainer.best_stable_generation,
            "best_stable_score": trainer.best_stable_score,
            "shortlist": trainer.checkpoint_shortlist,
            "final_generation": history[-1].generation if history else 0,
        })

    report = build_benchmark_report(
        checkpoint_paths=checkpoint_paths,
        windows=windows,
        cache_date=args.cache_date,
        costs_bps=costs,
    )

    summary["benchmark_report"] = report.to_dict()

    json_path = os.path.join(args.output_root, "reward_mix_sweep_summary.json")
    md_path = os.path.join(args.output_root, "reward_mix_sweep_report.md")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    report.save(md_path)

    print(json.dumps(summary, indent=2))
    print(f"\nSaved summary to {json_path}")
    print(f"Saved report to {md_path}")


if __name__ == "__main__":
    main()
