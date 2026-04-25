"""Canonical real-data walk-forward utilities for the migration plan."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
import os
import sys
from typing import Dict, List

import numpy as np

from training.baselines import MetricDict, aggregate_metric_dicts, evaluate_baselines


_ALPHA_ENGINE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "alphaforge-python",
)
if _ALPHA_ENGINE not in sys.path:
    sys.path.insert(0, _ALPHA_ENGINE)


@dataclass(frozen=True)
class CanonicalSplit:
    train_start: date = date(2010, 1, 1)
    train_end: date = date(2019, 12, 31)
    validation_start: date = date(2020, 1, 1)
    validation_end: date = date(2021, 12, 31)
    test_start: date = date(2022, 1, 1)
    test_end: date | None = None


@dataclass(frozen=True)
class RollingFold:
    fold_id: int
    train_start: date
    train_end: date
    eval_start: date
    eval_end: date


@dataclass
class BaselineFoldResult:
    fold: RollingFold
    metrics: Dict[str, MetricDict] = field(default_factory=dict)


def _add_months(d: date, months: int) -> date:
    month = d.month + months
    year = d.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    day = min(d.day, 28)
    return date(year, month, day)


def canonical_split() -> CanonicalSplit:
    return CanonicalSplit()


def generate_rolling_folds(
    *,
    start_date: date = date(2010, 1, 1),
    end_date: date = date(2019, 12, 31),
    train_years: int = 3,
    eval_months: int = 6,
    step_months: int = 6,
) -> List[RollingFold]:
    """Generate 3-year / 6-month rolling folds inside the in-sample training window."""
    folds: List[RollingFold] = []
    current = start_date
    fold_id = 0
    train_months = train_years * 12

    while True:
        train_end_exclusive = _add_months(current, train_months)
        eval_end_exclusive = _add_months(train_end_exclusive, eval_months)
        if eval_end_exclusive - timedelta(days=1) > end_date:
            break
        folds.append(
            RollingFold(
                fold_id=fold_id,
                train_start=current,
                train_end=train_end_exclusive - timedelta(days=1),
                eval_start=train_end_exclusive,
                eval_end=eval_end_exclusive - timedelta(days=1),
            )
        )
        fold_id += 1
        current = _add_months(current, step_months)

    return folds


def build_windows_for_period(
    *,
    sector: str,
    period_start: date,
    period_end: date,
    lookback: int,
    market_dir: str | None = None,
    n_windows: int | None = None,
) -> List[Dict[str, object]]:
    """Create aligned rolling dataset windows for a fixed time period.

    Each window is `lookback` trading days long, but the window end date must
    fall inside the requested period. This preserves the causal warmup history
    needed for indicators while keeping evaluation outcomes inside the fold.
    """
    from data.real_dataset import load_real_history, history_to_dataset

    history = load_real_history(
        sector=sector,
        lookback=max(lookback, 252),
        start_date=period_start - timedelta(days=max(lookback * 4, 365)),
        end_date=period_end,
        market_dir=market_dir,
        min_rows=lookback,
        align="inner",
    )
    if not history:
        return []

    reference_index = next(iter(history.values())).index if history else []
    if len(reference_index) < lookback:
        return []

    candidate_end_positions = [
        idx
        for idx, stamp in enumerate(reference_index)
        if period_start <= stamp.date() <= period_end and idx + 1 >= lookback
    ]
    if not candidate_end_positions:
        return []

    if n_windows is None or n_windows >= len(candidate_end_positions):
        selected_end_positions = candidate_end_positions
    else:
        pick_idx = np.linspace(0, len(candidate_end_positions) - 1, num=n_windows, dtype=int)
        selected_end_positions = [candidate_end_positions[int(idx)] for idx in pick_idx]

    windows: List[Dict[str, object]] = []
    for end_pos in selected_end_positions:
        start = end_pos - lookback + 1
        end = end_pos + 1
        sliced = {
            ticker: df.iloc[start:end].copy()
            for ticker, df in history.items()
            if len(df) >= end
        }
        if sliced:
            windows.append(history_to_dataset(sliced))
    return windows


def evaluate_baselines_on_rolling_folds(
    *,
    sector: str,
    lookback: int,
    market_dir: str | None = None,
    tx_cost_bps: int = 5,
    folds: List[RollingFold] | None = None,
) -> List[BaselineFoldResult]:
    if folds is None:
        split = canonical_split()
        folds = generate_rolling_folds(start_date=split.train_start, end_date=split.train_end)

    results: List[BaselineFoldResult] = []
    for fold in folds:
        windows = build_windows_for_period(
            sector=sector,
            period_start=fold.eval_start,
            period_end=fold.eval_end,
            lookback=lookback,
            market_dir=market_dir,
            n_windows=None,
        )
        metrics = evaluate_baselines(windows, tx_cost_bps=tx_cost_bps) if windows else {}
        results.append(BaselineFoldResult(fold=fold, metrics=metrics))
    return results


def aggregate_baseline_fold_results(results: List[BaselineFoldResult]) -> Dict[str, MetricDict]:
    by_name: Dict[str, List[MetricDict]] = {}
    for item in results:
        for name, metrics in item.metrics.items():
            by_name.setdefault(name, []).append(metrics)
    return {
        name: aggregate_metric_dicts(metrics)
        for name, metrics in sorted(by_name.items())
    }
