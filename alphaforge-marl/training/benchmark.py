"""Canonical benchmark utilities for MARL checkpoints and simple baselines."""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, Iterable, List, Mapping, Sequence

import numpy as np

from env.trading_env import TradingEnv
from training.baselines import MetricDict, aggregate_metric_dicts, evaluate_baselines
from evaluate_real_market import load_best_agent


Dataset = Mapping[str, Any]


def _window_returns(window: Dataset) -> np.ndarray:
    tickers = list(window.keys())
    if not tickers:
        return np.zeros(0, dtype=np.float64)
    min_len = min(len(window[t].returns) for t in tickers)
    if min_len <= 0:
        return np.zeros(0, dtype=np.float64)
    rets = np.zeros(min_len, dtype=np.float64)
    for ticker in tickers:
        rets += np.asarray(window[ticker].returns[:min_len], dtype=np.float64) / len(tickers)
    return rets


def classify_window_regimes(windows: Sequence[Dataset]) -> List[str]:
    """Assign a coarse regime label to each window from window-level return/vol."""
    if not windows:
        return []

    summaries = []
    vols = []
    for window in windows:
        rets = _window_returns(window)
        mean_ret = float(np.mean(rets)) if len(rets) else 0.0
        vol = float(np.std(rets, ddof=1)) if len(rets) > 1 else 0.0
        summaries.append((mean_ret, vol))
        vols.append(vol)
    vol_threshold = float(np.median(vols)) if vols else 0.0

    labels = []
    for mean_ret, vol in summaries:
        direction = "bull" if mean_ret >= 0.0 else "bear"
        speed = "high_vol" if vol >= vol_threshold else "low_vol"
        labels.append(f"{direction}_{speed}")
    return labels


def _run_agent_on_window(
    checkpoint_path: str,
    window: Dataset,
    tx_cost_bps: int,
    seed: int,
) -> MetricDict:
    agent, _meta = load_best_agent(checkpoint_path)
    lookback = min(len(ps.prices) for ps in window.values()) if window else 252
    env = TradingEnv(
        sector="All",
        lookback=lookback,
        episode_length=lookback,
        data_mode="real_strict",
        strict_real_data=True,
        tx_cost_bps=tx_cost_bps,
        max_position=0.05,
        max_gross_exposure=1.50,
        stop_loss=0.03,
    )
    env._real_windows = [window]
    obs, _info = env.reset(seed=seed)
    done = False
    actions = []
    while not done:
        action = int(agent.select_action(obs, training=False))
        actions.append(action)
        obs, _reward, terminated, truncated, _info = env.step(action)
        done = terminated or truncated

    from training.baselines import compute_performance_metrics

    metrics = compute_performance_metrics(
        env._daily_returns,
        env._nav_history,
        env._daily_turnover,
    )
    active_steps = sum(1 for action in actions if action != 0)
    metrics["activity_ratio"] = active_steps / max(len(actions), 1)
    metrics["gross_exposure"] = float(np.mean([abs(v) for v in env._positions.values()])) if env._positions else 0.0
    return metrics


def evaluate_checkpoint_cost_grid(
    checkpoint_path: str,
    windows: Sequence[Dataset],
    costs_bps: Sequence[int],
) -> Dict[str, MetricDict]:
    """Evaluate one checkpoint across a transaction-cost grid."""
    out: Dict[str, MetricDict] = {}
    for cost in costs_bps:
        per_window = [
            _run_agent_on_window(checkpoint_path, window, tx_cost_bps=int(cost), seed=idx)
            for idx, window in enumerate(windows)
        ]
        out[str(int(cost))] = aggregate_metric_dicts(per_window)
    return out


def evaluate_checkpoint_regime_breakdown(
    checkpoint_path: str,
    windows: Sequence[Dataset],
    costs_bps: int,
) -> Dict[str, MetricDict]:
    """Break one checkpoint's performance down by coarse market regime."""
    labels = classify_window_regimes(windows)
    grouped: Dict[str, List[MetricDict]] = {}
    for idx, (window, label) in enumerate(zip(windows, labels)):
        grouped.setdefault(label, []).append(
            _run_agent_on_window(checkpoint_path, window, tx_cost_bps=int(costs_bps), seed=idx)
        )
    return {
        label: aggregate_metric_dicts(metrics)
        for label, metrics in sorted(grouped.items())
    }


@dataclass
class BenchmarkReport:
    cache_date: str
    checkpoint_metrics: Dict[str, MetricDict] = field(default_factory=dict)
    baseline_metrics: Dict[str, MetricDict] = field(default_factory=dict)
    checkpoint_cost_grid: Dict[str, Dict[str, MetricDict]] = field(default_factory=dict)
    baseline_cost_grid: Dict[str, Dict[str, MetricDict]] = field(default_factory=dict)
    checkpoint_regimes: Dict[str, Dict[str, MetricDict]] = field(default_factory=dict)
    baseline_regimes: Dict[str, Dict[str, MetricDict]] = field(default_factory=dict)
    checkpoint_metadata: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cache_date": self.cache_date,
            "checkpoint_metrics": self.checkpoint_metrics,
            "baseline_metrics": self.baseline_metrics,
            "checkpoint_cost_grid": self.checkpoint_cost_grid,
            "baseline_cost_grid": self.baseline_cost_grid,
            "checkpoint_regimes": self.checkpoint_regimes,
            "baseline_regimes": self.baseline_regimes,
            "checkpoint_metadata": self.checkpoint_metadata,
        }

    def to_markdown(self) -> str:
        lines = [
            "# MARL Benchmark Report",
            "",
            f"Cache date: `{self.cache_date}`",
            "",
            "## Overall",
            "",
            "| Strategy | Sharpe | AnnRet | MaxDD | Turnover | HitRate |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
        combined = []
        for name, metrics in self.checkpoint_metrics.items():
            combined.append((name, metrics))
        for name, metrics in self.baseline_metrics.items():
            combined.append((name, metrics))
        combined.sort(key=lambda item: item[1].get("sharpe", 0.0), reverse=True)
        for name, metrics in combined:
            lines.append(
                f"| {name} | {metrics.get('sharpe', 0.0):+.3f} | "
                f"{metrics.get('annual_return', 0.0):+.2%} | "
                f"{metrics.get('max_drawdown', 0.0):.2%} | "
                f"{metrics.get('avg_turnover', 0.0):.3f} | "
                f"{metrics.get('hit_rate', 0.0):.1%} |"
            )

        lines.extend(["", "## Cost Sensitivity", ""])
        for name, cost_grid in self.checkpoint_cost_grid.items():
            lines.append(f"### {name}")
            lines.append("")
            lines.append("| Cost (bps) | Sharpe | AnnRet | MaxDD |")
            lines.append("| --- | ---: | ---: | ---: |")
            for cost, metrics in sorted(cost_grid.items(), key=lambda item: int(item[0])):
                lines.append(
                    f"| {cost} | {metrics.get('sharpe', 0.0):+.3f} | "
                    f"{metrics.get('annual_return', 0.0):+.2%} | "
                    f"{metrics.get('max_drawdown', 0.0):.2%} |"
                )
            lines.append("")

        lines.extend(["## Regime Breakdown", ""])
        for name, regimes in self.checkpoint_regimes.items():
            lines.append(f"### {name}")
            lines.append("")
            lines.append("| Regime | Sharpe | AnnRet | MaxDD | HitRate |")
            lines.append("| --- | ---: | ---: | ---: | ---: |")
            for regime, metrics in regimes.items():
                lines.append(
                    f"| {regime} | {metrics.get('sharpe', 0.0):+.3f} | "
                    f"{metrics.get('annual_return', 0.0):+.2%} | "
                    f"{metrics.get('max_drawdown', 0.0):.2%} | "
                    f"{metrics.get('hit_rate', 0.0):.1%} |"
                )
            lines.append("")
        return "\n".join(lines)

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        if path.lower().endswith(".md"):
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.to_markdown())
            return
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)


def build_benchmark_report(
    checkpoint_paths: Mapping[str, str],
    windows: Sequence[Dataset],
    cache_date: str,
    costs_bps: Sequence[int] = (5, 10, 25, 50),
) -> BenchmarkReport:
    """Build a canonical report for checkpoints and standard baselines."""
    report = BenchmarkReport(cache_date=cache_date)

    report.baseline_metrics = evaluate_baselines(windows, tx_cost_bps=int(costs_bps[0]))
    report.baseline_cost_grid = {
        str(int(cost)): evaluate_baselines(windows, tx_cost_bps=int(cost))
        for cost in costs_bps
    }

    baseline_regimes: Dict[str, Dict[str, List[MetricDict]]] = {}
    labels = classify_window_regimes(windows)
    for cost in costs_bps[:1]:
        for idx, (label, window) in enumerate(zip(labels, windows)):
            baselines = evaluate_baselines([window], tx_cost_bps=int(cost))
            for strategy, metrics in baselines.items():
                baseline_regimes.setdefault(strategy, {}).setdefault(label, []).append(metrics)
    report.baseline_regimes = {
        strategy: {
            label: aggregate_metric_dicts(metrics)
            for label, metrics in sorted(grouped.items())
        }
        for strategy, grouped in sorted(baseline_regimes.items())
    }

    for name, path in checkpoint_paths.items():
        report.checkpoint_cost_grid[name] = evaluate_checkpoint_cost_grid(path, windows, costs_bps)
        report.checkpoint_metrics[name] = report.checkpoint_cost_grid[name][str(int(costs_bps[0]))]
        report.checkpoint_regimes[name] = evaluate_checkpoint_regime_breakdown(path, windows, int(costs_bps[0]))
        _agent, meta = load_best_agent(path)
        report.checkpoint_metadata[name] = meta.get("extra", {})

    return report
