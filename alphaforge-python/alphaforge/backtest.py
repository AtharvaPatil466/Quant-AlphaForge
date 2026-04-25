"""
Long-short backtest simulation engine — port of JS runBacktest.

Produces NAV history, benchmark, drawdowns, monthly returns, and performance
metrics. Must match JS output for identical inputs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

from .data import (
    PriceSeries,
    generate_dataset,
    safe_div,
    sanitize_number,
    clamp,
    validate_series,
    mean,
    stddev,
)
from .scoring import compute_factor_scores_js
from .factors import JS_FACTOR_NAMES


@dataclass
class BacktestConfig:
    sector: str = "Technology"
    lookback: int = 252
    factor_name: str = "Momentum (12-1)"
    holding_period: int = 10
    position_size: int = 10        # % of universe per leg (maps to JS positionSize)
    stop_loss: float = 5.0         # % (maps to JS stopLoss)
    tx_cost_bps: int = 5
    base_seed: int = 42


@dataclass
class BacktestMetrics:
    sharpe: Optional[float] = None
    total_return: Optional[float] = None
    bench_return: Optional[float] = None
    max_dd: Optional[float] = None
    max_dd_day: int = 0
    win_rate: Optional[float] = None
    ann_vol: Optional[float] = None
    calmar: Optional[float] = None


@dataclass
class BacktestResult:
    nav: List[float] = field(default_factory=list)
    benchmark_nav: List[float] = field(default_factory=list)
    drawdowns: List[float] = field(default_factory=list)
    monthly_returns: List[float] = field(default_factory=list)
    daily_returns: List[float] = field(default_factory=list)
    metrics: BacktestMetrics = field(default_factory=BacktestMetrics)
    error: Optional[str] = None


def run_backtest(config: BacktestConfig) -> BacktestResult:
    """Port of JS runBacktest from data.js.

    Matches JS logic exactly:
    - Pre-generate all price series
    - Score tickers by selected factor
    - Long top N%, short bottom N%
    - Apply tx cost on rebalance days
    - Stop-loss check against peak NAV
    - Benchmark: equal-weight all tickers
    - Monthly returns: 21-day chunks
    """
    dataset = generate_dataset(config.sector, config.lookback, config.base_seed)
    tickers = list(dataset.keys())

    if not tickers:
        return BacktestResult(error="No tickers in selected universe.")

    num_days = len(dataset[tickers[0]].prices)

    # Score tickers for factor ranking
    scores = compute_factor_scores_js(dataset, config.lookback)

    # Rank tickers by selected factor (descending)
    factor = config.factor_name
    ranked = sorted(tickers, key=lambda t: scores.get(t, {}).get(factor, 0), reverse=True)

    long_count = max(1, int(len(ranked) * config.position_size / 100))
    long_tickers = ranked[:long_count]
    short_tickers = ranked[-long_count:]

    tx_cost = config.tx_cost_bps / 10000

    nav = [100.0]
    benchmark_nav = [100.0]
    daily_returns = []
    benchmark_returns = []
    drawdowns = []

    peak = 100.0
    max_drawdown = 0.0
    max_drawdown_day = 0
    wins = 0
    total_trades = 0

    for day in range(1, num_days):
        # Portfolio daily return (equal-weight long-short)
        port_return = 0.0
        for t in long_tickers:
            port_return += safe_div(dataset[t].returns[day], long_count, 0.0)
        for t in short_tickers:
            port_return -= safe_div(dataset[t].returns[day], long_count, 0.0)

        # Factor boost for simulation realism
        factor_boost = scores.get(ranked[0], {}).get(factor, 0.0) * 0.0002
        port_return += sanitize_number(factor_boost, 0.0)

        # Transaction costs on rebalance days
        if day % config.holding_period == 0:
            port_return -= tx_cost * 2  # round-trip

        # Stop-loss check
        current_nav = nav[-1]
        stop_loss_level = peak * (1 - config.stop_loss / 100)
        if current_nav < stop_loss_level:
            port_return = max(port_return, -config.stop_loss / 100)

        new_nav = current_nav * (1 + clamp(port_return, -0.20, 0.20))
        nav.append(max(0.01, sanitize_number(new_nav, current_nav)))
        daily_returns.append(sanitize_number(port_return, 0.0))

        # Benchmark (equal-weight all tickers)
        bench_return = 0.0
        for t in tickers:
            bench_return += safe_div(dataset[t].returns[day], len(tickers), 0.0)
        new_bench = benchmark_nav[-1] * (1 + bench_return)
        benchmark_nav.append(max(0.01, sanitize_number(new_bench, benchmark_nav[-1])))
        benchmark_returns.append(sanitize_number(bench_return, 0.0))

        # Track wins
        if port_return > 0:
            wins += 1
        total_trades += 1

        # Drawdown
        if nav[-1] > peak:
            peak = nav[-1]
        dd = safe_div(peak - nav[-1], peak, 0.0)
        drawdowns.append(sanitize_number(dd, 0.0))
        if dd > max_drawdown:
            max_drawdown = dd
            max_drawdown_day = day

    # Validate series
    nav_arr = np.array(nav)
    bench_arr = np.array(benchmark_nav)
    if not validate_series(nav_arr) or not validate_series(bench_arr):
        return BacktestResult(
            error="Simulation produced invalid values — try adjusting parameters"
        )

    # Compute metrics
    total_return = safe_div(nav[-1] - 100, 100, 0.0)
    bench_return_val = safe_div(benchmark_nav[-1] - 100, 100, 0.0)
    avg_return = mean(daily_returns)
    std_return = max(1e-8, stddev(daily_returns))
    sharpe = sanitize_number(safe_div(avg_return, std_return, 0.0) * (252 ** 0.5), 0.0)
    win_rate_val = safe_div(wins, total_trades, 0.0)

    # Monthly returns (21-day chunks, matching JS)
    monthly_returns = []
    for i in range(0, len(daily_returns), 21):
        chunk = daily_returns[i : i + 21]
        month_ret = 1.0
        for r in chunk:
            month_ret *= (1 + r)
        month_ret -= 1
        monthly_returns.append(sanitize_number(month_ret, 0.0))

    # Annualized vol and Calmar
    ann_vol = std_return * (252 ** 0.5) if std_return > 1e-8 else 0.0
    ann_return = total_return  # approximate
    calmar = safe_div(ann_return, max_drawdown, 0.0) if max_drawdown > 0 else 0.0

    metrics = BacktestMetrics(
        sharpe=sharpe if np.isfinite(sharpe) else None,
        total_return=total_return if np.isfinite(total_return) else None,
        bench_return=bench_return_val if np.isfinite(bench_return_val) else None,
        max_dd=max_drawdown if np.isfinite(max_drawdown) else None,
        max_dd_day=max_drawdown_day,
        win_rate=win_rate_val if np.isfinite(win_rate_val) else None,
        ann_vol=ann_vol if np.isfinite(ann_vol) else None,
        calmar=calmar if np.isfinite(calmar) else None,
    )

    return BacktestResult(
        nav=nav,
        benchmark_nav=benchmark_nav,
        drawdowns=drawdowns,
        monthly_returns=monthly_returns,
        daily_returns=daily_returns,
        metrics=metrics,
    )
