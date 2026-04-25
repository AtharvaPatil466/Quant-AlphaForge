"""Walk-forward validation framework.

Implements anchored walk-forward analysis with strict temporal splits:
  - Train on historical window (e.g., 2022-2023)
  - Validate on next period (e.g., 2024)
  - Out-of-sample test on final period (e.g., 2025)

No future data ever leaks into training. Each fold trains a fresh population,
evaluates on validation, then records out-of-sample performance.
"""

from __future__ import annotations

import copy
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from training.baselines import (
    MetricDict,
    aggregate_metric_dicts,
    compute_performance_metrics,
    evaluate_baselines,
)

logger = logging.getLogger(__name__)


@dataclass
class WalkForwardFold:
    """A single temporal fold in the walk-forward analysis."""
    fold_id: int
    train_start: date
    train_end: date
    val_start: date
    val_end: date
    test_start: date
    test_end: date

    # Results (filled after evaluation)
    train_best_fitness: float = 0.0
    train_mean_fitness: float = 0.0
    val_sharpe: float = 0.0
    test_sharpe: float = 0.0
    n_generations_trained: int = 0
    best_agent_id: str = ""
    curriculum_stage: str = ""
    regime_at_test: int = 0
    val_metrics: MetricDict = field(default_factory=dict)
    test_metrics: MetricDict = field(default_factory=dict)
    baseline_test_metrics: Dict[str, MetricDict] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fold_id": self.fold_id,
            "train_period": f"{self.train_start} to {self.train_end}",
            "val_period": f"{self.val_start} to {self.val_end}",
            "test_period": f"{self.test_start} to {self.test_end}",
            "train_best_fitness": round(self.train_best_fitness, 4),
            "train_mean_fitness": round(self.train_mean_fitness, 4),
            "val_sharpe": round(self.val_sharpe, 4),
            "test_sharpe": round(self.test_sharpe, 4),
            "n_generations_trained": self.n_generations_trained,
            "best_agent_id": self.best_agent_id,
            "curriculum_stage": self.curriculum_stage,
            "regime_at_test": self.regime_at_test,
            "val_metrics": {k: round(v, 6) for k, v in self.val_metrics.items()},
            "test_metrics": {k: round(v, 6) for k, v in self.test_metrics.items()},
            "baseline_test_metrics": {
                name: {k: round(v, 6) for k, v in metrics.items()}
                for name, metrics in self.baseline_test_metrics.items()
            },
        }


@dataclass
class WalkForwardResult:
    """Aggregated results across all walk-forward folds."""
    folds: List[WalkForwardFold] = field(default_factory=list)

    @property
    def mean_val_sharpe(self) -> float:
        vals = [f.val_sharpe for f in self.folds if f.val_sharpe != 0.0]
        return float(np.mean(vals)) if vals else 0.0

    @property
    def mean_test_sharpe(self) -> float:
        tests = [f.test_sharpe for f in self.folds if f.test_sharpe != 0.0]
        return float(np.mean(tests)) if tests else 0.0

    @property
    def val_test_correlation(self) -> float:
        """Correlation between validation and test Sharpe across folds."""
        if len(self.folds) < 2:
            return 0.0
        vals = np.array([f.val_sharpe for f in self.folds])
        tests = np.array([f.test_sharpe for f in self.folds])
        if np.std(vals) < 1e-10 or np.std(tests) < 1e-10:
            return 0.0
        return float(np.corrcoef(vals, tests)[0, 1])

    @property
    def overfitting_ratio(self) -> float:
        """Ratio of test vs validation performance. <1.0 suggests overfitting."""
        if abs(self.mean_val_sharpe) < 1e-10:
            return 0.0
        return self.mean_test_sharpe / self.mean_val_sharpe

    @property
    def baseline_mean_test_metrics(self) -> Dict[str, MetricDict]:
        """Average baseline metrics across folds."""
        by_name: Dict[str, List[MetricDict]] = {}
        for fold in self.folds:
            for name, metrics in fold.baseline_test_metrics.items():
                by_name.setdefault(name, []).append(metrics)
        return {
            name: aggregate_metric_dicts(metric_list)
            for name, metric_list in sorted(by_name.items())
        }

    def summary(self) -> Dict[str, Any]:
        return {
            "n_folds": len(self.folds),
            "mean_val_sharpe": round(self.mean_val_sharpe, 4),
            "mean_test_sharpe": round(self.mean_test_sharpe, 4),
            "val_test_correlation": round(self.val_test_correlation, 4),
            "overfitting_ratio": round(self.overfitting_ratio, 4),
            "baseline_mean_test_metrics": {
                name: {k: round(v, 6) for k, v in metrics.items()}
                for name, metrics in self.baseline_mean_test_metrics.items()
            },
            "folds": [f.to_dict() for f in self.folds],
        }

    def save(self, path: str) -> None:
        """Save the walk-forward result as JSON or Markdown based on extension."""
        if path.lower().endswith(".md"):
            with open(path, "w") as f:
                f.write(self.to_markdown())
            return
        with open(path, "w") as f:
            json.dump(self.summary(), f, indent=2)

    def report(self) -> str:
        """Human-readable walk-forward report."""
        return self.to_markdown()

    def to_markdown(self) -> str:
        """Human-readable walk-forward report."""
        lines = [
            "=" * 60,
            "WALK-FORWARD VALIDATION REPORT",
            "=" * 60,
            f"Folds: {len(self.folds)}",
            f"Mean Validation Sharpe:  {self.mean_val_sharpe:+.4f}",
            f"Mean Test Sharpe:        {self.mean_test_sharpe:+.4f}",
            f"Val/Test Correlation:    {self.val_test_correlation:+.4f}",
            f"Overfitting Ratio:       {self.overfitting_ratio:.4f}",
            "",
        ]
        for f in self.folds:
            lines.append(f"--- Fold {f.fold_id} ---")
            lines.append(f"  Train: {f.train_start} → {f.train_end}")
            lines.append(f"  Val:   {f.val_start} → {f.val_end}")
            lines.append(f"  Test:  {f.test_start} → {f.test_end}")
            lines.append(f"  Train best fitness: {f.train_best_fitness:+.4f}")
            lines.append(f"  Val Sharpe:  {f.val_sharpe:+.4f}")
            lines.append(f"  Test Sharpe: {f.test_sharpe:+.4f}")
            lines.append(f"  Generations: {f.n_generations_trained}")
            lines.append(f"  Best agent: {f.best_agent_id}")
            if f.test_metrics:
                lines.append(
                    "  Test metrics: "
                    f"ann_ret={f.test_metrics.get('annual_return', 0.0):+.2%}, "
                    f"max_dd={f.test_metrics.get('max_drawdown', 0.0):.2%}, "
                    f"turnover={f.test_metrics.get('avg_turnover', 0.0):.3f}, "
                    f"hit_rate={f.test_metrics.get('hit_rate', 0.0):.1%}"
                )
            lines.append("")
        if self.baseline_mean_test_metrics:
            lines.append("Mean Test Metrics vs Baselines")
            lines.append(
                f"  {'Strategy':<20} {'Sharpe':>8} {'AnnRet':>10} {'MaxDD':>8} {'HitRate':>8}"
            )
            marl_metrics = aggregate_metric_dicts(
                [f.test_metrics for f in self.folds if f.test_metrics]
            )
            if marl_metrics:
                lines.append(
                    f"  {'marl_agent':<20} "
                    f"{marl_metrics.get('sharpe', 0.0):>+8.3f} "
                    f"{marl_metrics.get('annual_return', 0.0):>+9.2%} "
                    f"{marl_metrics.get('max_drawdown', 0.0):>7.2%} "
                    f"{marl_metrics.get('hit_rate', 0.0):>7.1%}"
                )
            for name, metrics in self.baseline_mean_test_metrics.items():
                lines.append(
                    f"  {name:<20} "
                    f"{metrics.get('sharpe', 0.0):>+8.3f} "
                    f"{metrics.get('annual_return', 0.0):>+9.2%} "
                    f"{metrics.get('max_drawdown', 0.0):>7.2%} "
                    f"{metrics.get('hit_rate', 0.0):>7.1%}"
                )
            lines.append("")
        lines.append("=" * 60)

        if self.overfitting_ratio < 0.5:
            lines.append("WARNING: Significant overfitting detected (ratio < 0.5)")
        elif self.overfitting_ratio > 0.8:
            lines.append("Good: Strategy generalizes well (ratio > 0.8)")
        else:
            lines.append("Moderate: Some overfitting present (0.5 < ratio < 0.8)")

        return "\n".join(lines)


def generate_folds(
    start_date: date = date(2022, 1, 1),
    end_date: date = date(2025, 12, 31),
    train_months: int = 24,
    val_months: int = 12,
    test_months: int = 12,
    step_months: int = 12,
) -> List[WalkForwardFold]:
    """Generate temporal folds for walk-forward analysis.

    Default: train 2022-2023, validate 2024, test 2025.
    With step_months < test_months, creates rolling folds.

    Args:
        start_date: Earliest date for training data.
        end_date: Latest date for test data.
        train_months: Training window in months.
        val_months: Validation window in months.
        test_months: Test window in months.
        step_months: How much to advance between folds.

    Returns:
        List of WalkForwardFold with date boundaries.
    """
    folds = []
    fold_id = 0
    current_start = start_date

    while True:
        train_start = current_start
        train_end = _add_months(train_start, train_months)
        val_start = train_end
        val_end = _add_months(val_start, val_months)
        test_start = val_end
        test_end = _add_months(test_start, test_months)

        if test_end > end_date + timedelta(days=31):
            break

        folds.append(WalkForwardFold(
            fold_id=fold_id,
            train_start=train_start,
            train_end=train_end - timedelta(days=1),
            val_start=val_start,
            val_end=val_end - timedelta(days=1),
            test_start=test_start,
            test_end=min(test_end - timedelta(days=1), end_date),
        ))
        fold_id += 1
        current_start = _add_months(current_start, step_months)

    return folds


def _add_months(d: date, months: int) -> date:
    """Add months to a date, handling month overflow."""
    month = d.month + months
    year = d.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    day = min(d.day, 28)  # Safe for all months
    return date(year, month, day)


class WalkForwardValidator:
    """Runs walk-forward validation using the MARL training pipeline.

    For each fold:
    1. Fetch real data bounded by the fold's date ranges
    2. Train a fresh population on the training window
    3. Evaluate best agent on validation window
    4. Evaluate best agent on test window (out-of-sample)
    5. Record all metrics
    """

    def __init__(
        self,
        config_path: Optional[str] = None,
        n_generations: int = 30,
        checkpoint_dir: str = "checkpoints/walk_forward",
        cache_dir: str = ".data_cache",
        sector: str = "All",
    ):
        from training.config import load_config
        self.config = load_config(config_path)
        self.n_generations = n_generations
        self.checkpoint_dir = checkpoint_dir
        self.cache_dir = cache_dir
        self.sector = sector

    def run(
        self,
        folds: Optional[List[WalkForwardFold]] = None,
    ) -> WalkForwardResult:
        """Execute walk-forward validation across all folds."""
        if folds is None:
            folds = generate_folds()

        result = WalkForwardResult()

        for fold in folds:
            logger.info(
                f"=== Walk-Forward Fold {fold.fold_id} ===\n"
                f"  Train: {fold.train_start} → {fold.train_end}\n"
                f"  Val:   {fold.val_start} → {fold.val_end}\n"
                f"  Test:  {fold.test_start} → {fold.test_end}"
            )

            try:
                self._run_fold(fold)
            except Exception as e:
                logger.error(f"Fold {fold.fold_id} failed: {e}")
                # Record failure but continue
                fold.val_sharpe = 0.0
                fold.test_sharpe = 0.0

            result.folds.append(fold)
            logger.info(
                f"Fold {fold.fold_id} done: "
                f"val_sharpe={fold.val_sharpe:.4f} "
                f"test_sharpe={fold.test_sharpe:.4f}"
            )

        logger.info(f"\n{result.report()}")
        return result

    def _run_fold(self, fold: WalkForwardFold) -> None:
        """Train and evaluate a single fold."""
        from env.real_data import ALL_TICKERS, REAL_UNIVERSE
        from training.trainer import Trainer

        # 1. Fetch date-bounded data for each period
        tickers = ALL_TICKERS if self.sector == "All" else REAL_UNIVERSE.get(
            self.sector, ALL_TICKERS
        )

        train_data = self._fetch_period_data(
            tickers, fold.train_start, fold.train_end
        )
        val_data = self._fetch_period_data(
            tickers, fold.val_start, fold.val_end
        )
        test_data = self._fetch_period_data(
            tickers, fold.test_start, fold.test_end
        )

        if not train_data or not val_data:
            logger.warning(f"Fold {fold.fold_id}: insufficient data, skipping")
            return

        # 2. Train on training window
        #    Override config for this fold
        fold_config = copy.deepcopy(self.config)
        fold_checkpoint_dir = os.path.join(
            self.checkpoint_dir, f"fold_{fold.fold_id:02d}"
        )
        os.makedirs(fold_checkpoint_dir, exist_ok=True)

        trainer = Trainer(
            config=fold_config,
            checkpoint_dir=fold_checkpoint_dir,
            log_path=os.path.join(fold_checkpoint_dir, "training.jsonl"),
        )

        # Inject pre-loaded training data into the environment
        # so it doesn't fetch its own data
        trainer.env._real_windows = self._make_windows(
            train_data, trainer.env.lookback
        )
        trainer.env.data_mode = "real_strict"
        trainer.env.strict_real_data = True

        history = trainer.train(n_generations=self.n_generations)

        if history:
            fold.train_best_fitness = history[-1].best_fitness
            fold.train_mean_fitness = history[-1].mean_fitness
            fold.n_generations_trained = len(history)

        # Get best agent
        best_agent = trainer.pool.best()
        fold.best_agent_id = best_agent.agent_id

        if hasattr(trainer, 'curriculum') and trainer.curriculum.current_stage:
            fold.curriculum_stage = trainer.curriculum.current_stage.name

        # 3. Evaluate on validation window
        fold.val_metrics = self._evaluate_agent_on_data_metrics(
            best_agent, trainer.env, val_data
        )
        fold.val_sharpe = fold.val_metrics.get("sharpe", 0.0)

        # 4. Evaluate on test window (out-of-sample)
        if test_data:
            fold.test_metrics = self._evaluate_agent_on_data_metrics(
                best_agent, trainer.env, test_data
            )
            fold.test_sharpe = fold.test_metrics.get("sharpe", 0.0)
            fold.baseline_test_metrics = self._evaluate_baselines_on_data(
                test_data,
                window_size=trainer.env.lookback,
                tx_cost_bps=int(trainer.env.tx_cost * 10000),
            )

        # 5. Detect regime at test time
        if trainer.regime_detector.is_fitted:
            fold.regime_at_test = trainer._detect_current_regime()

    def _fetch_period_data(
        self,
        tickers: List[str],
        start: date,
        end: date,
    ) -> Dict[str, "pd.DataFrame"]:
        """Fetch real data for a specific date range."""
        import pandas as pd
        from env.real_data import fetch_real_data

        # Fetch with enough buffer, then slice to exact range
        total_days = (end - start).days
        cal_days = int(total_days * 0.7)  # Approximate trading days

        raw = fetch_real_data(
            tickers,
            days=cal_days + 50,  # Extra buffer
            end_date=end,
            cache_dir=self.cache_dir,
        )

        # Trim to exact date range
        trimmed = {}
        for ticker, df in raw.items():
            mask = (df.index.date >= start) & (df.index.date <= end)
            sliced = df.loc[mask]
            if len(sliced) >= 20:  # Need at least 20 trading days
                trimmed[ticker] = sliced

        return trimmed

    def _make_windows(
        self,
        period_data: Dict[str, "pd.DataFrame"],
        window_size: int,
    ) -> List[Dict]:
        """Create sliding windows from period data for episode diversity."""
        from env.real_data import ohlcv_to_price_series, validate_real_data

        min_len = min(
            (len(df) for df in period_data.values()), default=0
        )
        if min_len < window_size:
            # Single window with all available data
            return [ohlcv_to_price_series(period_data)]

        windows = []
        n_windows = min_len - window_size + 1
        step = max(1, n_windows // 15)  # ~15 diverse windows

        for start in range(0, n_windows, step):
            end = start + window_size
            windowed = {}
            for ticker, df in period_data.items():
                if len(df) >= end:
                    windowed[ticker] = df.iloc[start:end].copy()
            if windowed:
                dataset = ohlcv_to_price_series(windowed)
                if validate_real_data(dataset, min_days=window_size // 2):
                    windows.append(dataset)

        return windows if windows else [ohlcv_to_price_series(period_data)]

    def _evaluate_agent_on_data_metrics(
        self,
        agent,
        env,
        period_data: Dict[str, "pd.DataFrame"],
    ) -> MetricDict:
        """Evaluate an agent on a specific data period and average path metrics."""
        from env.episode_runner import run_episode

        windows = self._make_windows(period_data, env.lookback)
        if not windows:
            return {}

        metrics_list: List[MetricDict] = []
        # Save original env state
        original_windows = env._real_windows
        original_mode = env.data_mode
        original_strict = env.strict_real_data

        env._real_windows = windows
        env.data_mode = "real_strict"
        env.strict_real_data = True

        for i, _window in enumerate(windows):
            def policy(state, _agent=agent):
                return _agent.select_action(state, training=False)
            try:
                run_episode(env, policy, seed=i * 1000)
                metrics_list.append(
                    compute_performance_metrics(
                        env._daily_returns,
                        env._nav_history,
                        env._daily_turnover,
                    )
                )
            except Exception as e:
                logger.warning(f"Eval episode {i} failed: {e}")

        # Restore env state
        env._real_windows = original_windows
        env.data_mode = original_mode
        env.strict_real_data = original_strict

        return aggregate_metric_dicts(metrics_list)

    def _evaluate_baselines_on_data(
        self,
        period_data: Dict[str, "pd.DataFrame"],
        window_size: int,
        tx_cost_bps: int,
    ) -> Dict[str, MetricDict]:
        """Evaluate simple benchmark strategies on the same real-data windows."""
        windows = self._make_windows(period_data, window_size)
        if not windows:
            return {}
        return evaluate_baselines(windows, tx_cost_bps=tx_cost_bps)


def run_walk_forward(
    config_path: Optional[str] = None,
    n_generations: int = 30,
    sector: str = "All",
    train_start: date = date(2022, 1, 1),
    train_months: int = 24,
    val_months: int = 12,
    test_months: int = 12,
) -> WalkForwardResult:
    """Convenience function to run a standard walk-forward analysis.

    Default: Train 2022-2023, Validate 2024, Test 2025.
    """
    end_date = _add_months(train_start, train_months + val_months + test_months)

    folds = generate_folds(
        start_date=train_start,
        end_date=end_date,
        train_months=train_months,
        val_months=val_months,
        test_months=test_months,
        step_months=12,
    )

    validator = WalkForwardValidator(
        config_path=config_path,
        n_generations=n_generations,
        sector=sector,
    )

    return validator.run(folds)
