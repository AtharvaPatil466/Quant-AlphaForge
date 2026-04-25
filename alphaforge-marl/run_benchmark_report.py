#!/usr/bin/env python3
"""Build a canonical benchmark report for MARL checkpoints and baselines."""

from __future__ import annotations

import argparse
import json
import os
from datetime import date

from env.real_data import generate_real_dataset_windowed
from training.benchmark import build_benchmark_report


def _parse_checkpoint_args(items: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"Checkpoint spec must be name=path, got: {item}")
        name, path = item.split("=", 1)
        out[name.strip()] = path.strip()
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Build MARL benchmark report")
    parser.add_argument("--cache-date", default="2026-03-29", help="Pinned YYYY-MM-DD cache date")
    parser.add_argument("--sector", default="All", help="Sector or 'All'")
    parser.add_argument("--total-days", type=int, default=756, help="Total cached history to load")
    parser.add_argument("--window-size", type=int, default=252, help="Episode window size")
    parser.add_argument(
        "--checkpoint",
        action="append",
        default=[],
        help="Checkpoint spec in name=path form. Repeat for multiple checkpoints.",
    )
    parser.add_argument(
        "--costs",
        default="5,10,25,50",
        help="Comma-separated transaction cost grid in bps",
    )
    parser.add_argument("--output", required=True, help="Output path (.json or .md)")
    args = parser.parse_args()

    checkpoint_paths = _parse_checkpoint_args(args.checkpoint)
    if not checkpoint_paths:
        raise SystemExit("Provide at least one --checkpoint name=path")

    costs = [int(item.strip()) for item in args.costs.split(",") if item.strip()]
    eval_date = date.fromisoformat(args.cache_date)
    windows = generate_real_dataset_windowed(
        sector=args.sector,
        total_days=args.total_days,
        window_size=args.window_size,
        end_date=eval_date,
        cache_dir=".data_cache",
    )
    report = build_benchmark_report(
        checkpoint_paths=checkpoint_paths,
        windows=windows,
        cache_date=args.cache_date,
        costs_bps=costs,
    )
    report.save(args.output)

    print(json.dumps(report.to_dict(), indent=2))
    print(f"\nSaved report to {os.path.abspath(args.output)}")


if __name__ == "__main__":
    main()
