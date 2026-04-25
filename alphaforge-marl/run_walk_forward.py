#!/usr/bin/env python3
"""Run walk-forward validation on the MARL trading system.

Usage:
    python3 run_walk_forward.py                          # Full run (default: 30 gens)
    python3 run_walk_forward.py --quick                   # Quick smoke test (5 gens, 5 agents)
    python3 run_walk_forward.py --n-gens 50 --sector Technology
    python3 run_walk_forward.py --train-start 2021-01-01 --train-months 36
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)-20s %(levelname)-5s %(message)s",
    datefmt="%H:%M:%S",
)


def main():
    parser = argparse.ArgumentParser(description="Walk-forward validation for AlphaForge MARL")
    parser.add_argument("--quick", action="store_true", help="Quick smoke test (5 gens, 5 agents)")
    parser.add_argument("--n-gens", type=int, default=30, help="Generations per fold (default: 30)")
    parser.add_argument("--sector", default="All", help="Sector or 'All' (default: All)")
    parser.add_argument("--train-start", default="2022-01-01", help="Training start date (YYYY-MM-DD)")
    parser.add_argument("--train-months", type=int, default=24, help="Training window months (default: 24)")
    parser.add_argument("--val-months", type=int, default=12, help="Validation window months (default: 12)")
    parser.add_argument("--test-months", type=int, default=12, help="Test window months (default: 12)")
    parser.add_argument("--config", default=None, help="Config YAML path")
    parser.add_argument(
        "--output",
        default=None,
        help="Save results to .json or .md depending on file extension",
    )
    args = parser.parse_args()

    from training.walk_forward import (
        WalkForwardValidator,
        generate_folds,
        _add_months,
    )
    from training.config import load_config

    train_start = date.fromisoformat(args.train_start)
    n_gens = args.n_gens

    if args.quick:
        n_gens = 5
        # Override config for quick run
        config = load_config(args.config)
        config._data["population"]["n_agents"] = 5
        config._data["population"]["episodes_per_agent"] = 3
        config._data["validation"]["validate_every_n_gens"] = 3
        config._data["evolution"]["maml_enabled"] = False
        config._data["distributed"]["enabled"] = False
    else:
        config = load_config(args.config)

    end_date = _add_months(
        train_start,
        args.train_months + args.val_months + args.test_months,
    )

    folds = generate_folds(
        start_date=train_start,
        end_date=end_date,
        train_months=args.train_months,
        val_months=args.val_months,
        test_months=args.test_months,
        step_months=12,
    )

    print(f"\nWalk-Forward Validation")
    print(f"  Folds: {len(folds)}")
    print(f"  Generations/fold: {n_gens}")
    print(f"  Sector: {args.sector}")
    for f in folds:
        print(f"  Fold {f.fold_id}: train {f.train_start}→{f.train_end} | val {f.val_start}→{f.val_end} | test {f.test_start}→{f.test_end}")
    print()

    validator = WalkForwardValidator(
        config_path=args.config,
        n_generations=n_gens,
        sector=args.sector,
    )
    # If quick mode, inject the modified config
    if args.quick:
        validator.config = config

    result = validator.run(folds)

    print(f"\n{result.report()}")

    if args.output:
        result.save(args.output)
        print(f"\nResults saved to {args.output}")

    return 0 if result.mean_test_sharpe > -1.0 else 1


if __name__ == "__main__":
    sys.exit(main())
