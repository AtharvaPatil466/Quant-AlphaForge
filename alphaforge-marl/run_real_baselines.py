#!/usr/bin/env python3
"""Run baseline strategies through the canonical real-data walk-forward folds."""

from __future__ import annotations

import argparse

from training.real_walk_forward import (
    aggregate_baseline_fold_results,
    canonical_split,
    evaluate_baselines_on_rolling_folds,
    generate_rolling_folds,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate baseline strategies on canonical real-data folds")
    parser.add_argument("--sector", default="All", help="Sector or All")
    parser.add_argument("--lookback", type=int, default=252, help="Window size / episode length")
    parser.add_argument("--tx-cost-bps", type=int, default=5, help="Transaction cost assumption")
    parser.add_argument("--market-dir", default=None, help="Optional parquet market-data directory")
    args = parser.parse_args()

    split = canonical_split()
    folds = generate_rolling_folds(start_date=split.train_start, end_date=split.train_end)
    results = evaluate_baselines_on_rolling_folds(
        sector=args.sector,
        lookback=args.lookback,
        market_dir=args.market_dir,
        tx_cost_bps=args.tx_cost_bps,
        folds=folds,
    )
    aggregate = aggregate_baseline_fold_results(results)

    print("Canonical in-sample rolling folds")
    print(f"  Train master window: {split.train_start} -> {split.train_end}")
    print(f"  Validation holdout:  {split.validation_start} -> {split.validation_end}")
    print(f"  Sacred test start:   {split.test_start}")
    print()
    for item in results:
        print(
            f"Fold {item.fold.fold_id:02d} | "
            f"train {item.fold.train_start} -> {item.fold.train_end} | "
            f"eval {item.fold.eval_start} -> {item.fold.eval_end}"
        )
        for name, metrics in sorted(item.metrics.items()):
            print(
                f"  {name:<20} "
                f"Sharpe={metrics.get('sharpe', 0.0):+6.3f} "
                f"AnnRet={metrics.get('annual_return', 0.0):+7.2%} "
                f"MaxDD={metrics.get('max_drawdown', 0.0):6.2%} "
                f"HitRate={metrics.get('hit_rate', 0.0):6.1%}"
            )
        if not item.metrics:
            print("  no valid windows")
    print()
    print("Aggregate across rolling folds")
    for name, metrics in sorted(aggregate.items()):
        print(
            f"  {name:<20} "
            f"Sharpe={metrics.get('sharpe', 0.0):+6.3f} "
            f"AnnRet={metrics.get('annual_return', 0.0):+7.2%} "
            f"MaxDD={metrics.get('max_drawdown', 0.0):6.2%} "
            f"HitRate={metrics.get('hit_rate', 0.0):6.1%}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
