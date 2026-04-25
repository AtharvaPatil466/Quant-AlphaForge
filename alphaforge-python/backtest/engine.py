"""
Long-short backtest simulation engine — port of JS runBacktest.

Produces NAV history, benchmark, drawdowns, monthly returns, and performance
metrics. The JS-parity path matches JS output for identical inputs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

from data.synthetic import (
    PriceSeries,
    generate_dataset,
    safe_div,
    sanitize_number,
    clamp,
    validate_series,
    mean,
    stddev,
)
from factors.registry import load_factor, JS_FACTOR_NAMES
from backtest import metrics as bm


@dataclass
class BacktestConfig:
    sector: str = "Technology"
    lookback: int = 252
    factor_name: str = "Momentum (12-1)"
    holding_period: int = 10
    position_size: int = 10        # % of universe per leg
    stop_loss: float = 5.0         # %
    tx_cost_bps: int = 5
    base_seed: int = 42
    long_short: bool = True
    top_n_pct: float = 0.25


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
    sortino: Optional[float] = None
    ann_return: Optional[float] = None


@dataclass
class BacktestResult:
    nav: List[float] = field(default_factory=list)
    benchmark_nav: List[float] = field(default_factory=list)
    drawdowns: List[float] = field(default_factory=list)
    monthly_returns: List[float] = field(default_factory=list)
    daily_returns: List[float] = field(default_factory=list)
    metrics: BacktestMetrics = field(default_factory=BacktestMetrics)
    error: Optional[str] = None


def _compute_factor_scores_js(
    dataset: Dict[str, PriceSeries], lookback: int
) -> Dict[str, Dict[str, float]]:
    """Compute z-scored factor values using JS-parity path. Returns
    ticker -> {factor: z_score, '_composite': float, '_signal': str}.
    """
    tickers = list(dataset.keys())
    if not tickers:
        return {}

    # Raw scores for all JS factors
    raw_scores: Dict[str, Dict[str, float]] = {}
    for ticker in tickers:
        d = dataset[ticker]
        raw_scores[ticker] = {}
        for fname in JS_FACTOR_NAMES:
            factor = load_factor(fname)
            raw_scores[ticker][fname] = factor.compute_js(
                d.prices, d.volumes, d.returns, lookback
            )

    # Cross-sectional z-score normalization
    z_scored: Dict[str, Dict[str, float]] = {t: {} for t in tickers}
    for fname in JS_FACTOR_NAMES:
        raw_vals = np.array([raw_scores[t][fname] for t in tickers])
        mu = mean(raw_vals)
        sigma = max(1e-8, stddev(raw_vals))
        for ticker in tickers:
            z = safe_div(raw_scores[ticker][fname] - mu, sigma, 0.0)
            z_scored[ticker][fname] = sanitize_number(z, 0.0)

    # Composite
    for ticker in tickers:
        fv = [z_scored[ticker][f] for f in JS_FACTOR_NAMES]
        composite = mean(fv) * 40
        z_scored[ticker]["_composite"] = clamp(sanitize_number(composite, 0.0), -100, 100)
        if composite > 40:
            z_scored[ticker]["_signal"] = "LONG"
        elif composite < -40:
            z_scored[ticker]["_signal"] = "SHORT"
        else:
            z_scored[ticker]["_signal"] = "NEUTRAL"

    return z_scored


def run_backtest(config: BacktestConfig) -> BacktestResult:
    """Run a full long-short backtest matching JS logic exactly.

    Simulation logic (matching JS):
    1. Generate price series for all tickers
    2. Score and rank by factor
    3. Long top N%, short bottom N%
    4. Apply tx cost on rebalance days
    5. Stop-loss check against peak NAV
    6. Benchmark: equal-weight all tickers
    7. Monthly returns: 21-day chunks
    """
    dataset = generate_dataset(config.sector, config.lookback, config.base_seed)
    tickers = list(dataset.keys())

    if not tickers:
        return BacktestResult(error="No tickers in selected universe.")

    num_days = len(dataset[tickers[0]].prices)

    # Score tickers
    scores = _compute_factor_scores_js(dataset, config.lookback)
    factor = config.factor_name

    # Rank by selected factor (descending)
    ranked = sorted(
        tickers, key=lambda t: scores.get(t, {}).get(factor, 0), reverse=True
    )

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
    max_drawdown_val = 0.0
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
            port_return -= tx_cost * 2

        # Stop-loss check
        current_nav = nav[-1]
        stop_loss_level = peak * (1 - config.stop_loss / 100)
        if current_nav < stop_loss_level:
            port_return = max(port_return, -config.stop_loss / 100)

        new_nav = current_nav * (1 + clamp(port_return, -0.20, 0.20))
        nav.append(max(0.01, sanitize_number(new_nav, current_nav)))
        daily_returns.append(sanitize_number(port_return, 0.0))

        # Benchmark
        bench_return = 0.0
        for t in tickers:
            bench_return += safe_div(dataset[t].returns[day], len(tickers), 0.0)
        new_bench = benchmark_nav[-1] * (1 + bench_return)
        benchmark_nav.append(max(0.01, sanitize_number(new_bench, benchmark_nav[-1])))
        benchmark_returns.append(sanitize_number(bench_return, 0.0))

        if port_return > 0:
            wins += 1
        total_trades += 1

        if nav[-1] > peak:
            peak = nav[-1]
        dd = safe_div(peak - nav[-1], peak, 0.0)
        drawdowns.append(sanitize_number(dd, 0.0))
        if dd > max_drawdown_val:
            max_drawdown_val = dd
            max_drawdown_day = day

    # Validate
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

    # Monthly returns (21-day chunks)
    monthly_rets = bm.monthly_returns(nav)

    # Additional metrics
    ann_vol_val = std_return * (252 ** 0.5) if std_return > 1e-8 else 0.0
    calmar_val = safe_div(total_return, max_drawdown_val, 0.0) if max_drawdown_val > 0 else 0.0
    sortino_val = bm.sortino_ratio(daily_returns)
    ann_return_val = bm.annualized_return(nav)

    bt_metrics = BacktestMetrics(
        sharpe=sharpe if np.isfinite(sharpe) else None,
        total_return=total_return if np.isfinite(total_return) else None,
        bench_return=bench_return_val if np.isfinite(bench_return_val) else None,
        max_dd=max_drawdown_val if np.isfinite(max_drawdown_val) else None,
        max_dd_day=max_drawdown_day,
        win_rate=win_rate_val if np.isfinite(win_rate_val) else None,
        ann_vol=ann_vol_val if np.isfinite(ann_vol_val) else None,
        calmar=calmar_val if np.isfinite(calmar_val) else None,
        sortino=sortino_val if np.isfinite(sortino_val) else None,
        ann_return=ann_return_val if np.isfinite(ann_return_val) else None,
    )

    return BacktestResult(
        nav=nav,
        benchmark_nav=benchmark_nav,
        drawdowns=drawdowns,
        monthly_returns=monthly_rets,
        daily_returns=daily_returns,
        metrics=bt_metrics,
    )
