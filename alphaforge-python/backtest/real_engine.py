"""Real-data factor backtest against the local parquet market-data store."""

from __future__ import annotations

from datetime import date
from typing import Dict, List

import numpy as np

from backtest import metrics as bm
from backtest.engine import BacktestConfig, BacktestMetrics, BacktestResult
from data.real_dataset import load_real_history
from data.synthetic import PriceSeries, clamp, mean, safe_div, sanitize_number, stddev, validate_series
from factors.registry import load_factor


def _score_cross_section(
    dataset: Dict[str, PriceSeries],
    factor_name: str,
    lookback: int,
) -> Dict[str, float]:
    factor = load_factor(factor_name)
    tickers = list(dataset.keys())
    raw_scores = {
        ticker: factor.compute_js(
            dataset[ticker].prices,
            dataset[ticker].volumes,
            dataset[ticker].returns,
            lookback,
        )
        for ticker in tickers
    }
    values = np.asarray(list(raw_scores.values()), dtype=np.float64)
    mu = mean(values)
    sigma = max(1e-8, stddev(values))
    return {
        ticker: sanitize_number(safe_div(raw_scores[ticker] - mu, sigma, 0.0), 0.0)
        for ticker in tickers
    }


def run_real_backtest(
    config: BacktestConfig,
    *,
    end_date: date | str | None = None,
    market_dir: str | None = None,
) -> BacktestResult:
    warmup_days = max(252, config.lookback)
    total_days = warmup_days + config.lookback + 5
    history = load_real_history(
        sector=config.sector,
        lookback=total_days,
        end_date=end_date,
        market_dir=market_dir,
        min_rows=warmup_days + 5,
        align="inner",
    )
    if not history:
        return BacktestResult(error="No validated real-market data available for the requested universe.")

    tickers = sorted(history.keys())
    n_days = min(len(df) for df in history.values())
    if n_days <= warmup_days + 1:
        return BacktestResult(error="Not enough clean real-market history for the requested backtest window.")

    backtest_days = min(config.lookback, n_days - warmup_days - 1)
    start_idx = n_days - backtest_days - 1

    nav = [100.0]
    benchmark_nav = [100.0]
    drawdowns: List[float] = []
    daily_returns: List[float] = []
    benchmark_returns: List[float] = []
    peak = 100.0
    wins = 0
    total_trades = 0
    max_drawdown_val = 0.0
    max_drawdown_day = 0
    tx_cost = config.tx_cost_bps / 10000.0
    current_long: List[str] = []
    current_short: List[str] = []

    for offset, decision_idx in enumerate(range(start_idx, n_days - 1), start=1):
        if not current_long or (offset - 1) % max(1, config.holding_period) == 0:
            trailing = {
                ticker: PriceSeries(
                    ticker=ticker,
                    name=ticker,
                    prices=history[ticker]["Close"].iloc[: decision_idx + 1].to_numpy(dtype=np.float64),
                    volumes=history[ticker]["Volume"].iloc[: decision_idx + 1].to_numpy(dtype=np.float64),
                    returns=np.zeros(decision_idx + 1, dtype=np.float64),
                )
                for ticker in tickers
            }
            for ps in trailing.values():
                ps.returns[1:] = np.diff(ps.prices) / np.maximum(ps.prices[:-1], 1e-10)

            scores = _score_cross_section(trailing, config.factor_name, config.lookback)
            ranked = sorted(scores, key=scores.get, reverse=True)
            leg_size = max(1, int(len(ranked) * config.position_size / 100))
            current_long = ranked[:leg_size]
            current_short = ranked[-leg_size:]
            rebalance_cost = tx_cost * (2 if config.long_short else 1)
        else:
            rebalance_cost = 0.0

        next_idx = decision_idx + 1
        port_return = 0.0
        for ticker in current_long:
            px = history[ticker]["Close"].iloc[decision_idx]
            nxt = history[ticker]["Close"].iloc[next_idx]
            ret = safe_div(nxt - px, px, 0.0)
            ret = max(ret, -config.stop_loss / 100.0)
            port_return += safe_div(ret, len(current_long), 0.0)

        if config.long_short and current_short:
            for ticker in current_short:
                px = history[ticker]["Close"].iloc[decision_idx]
                nxt = history[ticker]["Close"].iloc[next_idx]
                ret = safe_div(nxt - px, px, 0.0)
                short_ret = -min(ret, config.stop_loss / 100.0)
                port_return += safe_div(short_ret, len(current_short), 0.0)

        port_return -= rebalance_cost

        bench_return = float(
            np.mean(
                [
                    safe_div(
                        history[ticker]["Close"].iloc[next_idx] - history[ticker]["Close"].iloc[decision_idx],
                        history[ticker]["Close"].iloc[decision_idx],
                        0.0,
                    )
                    for ticker in tickers
                ]
            )
        )

        new_nav = nav[-1] * (1 + clamp(port_return, -0.20, 0.20))
        nav.append(max(0.01, sanitize_number(new_nav, nav[-1])))
        benchmark_nav.append(max(0.01, sanitize_number(benchmark_nav[-1] * (1 + bench_return), benchmark_nav[-1])))
        daily_returns.append(sanitize_number(port_return, 0.0))
        benchmark_returns.append(sanitize_number(bench_return, 0.0))
        wins += int(port_return > 0)
        total_trades += 1

        if nav[-1] > peak:
            peak = nav[-1]
        dd = safe_div(peak - nav[-1], peak, 0.0)
        drawdowns.append(dd)
        if dd > max_drawdown_val:
            max_drawdown_val = dd
            max_drawdown_day = offset

    nav_arr = np.asarray(nav, dtype=np.float64)
    bench_arr = np.asarray(benchmark_nav, dtype=np.float64)
    if not validate_series(nav_arr) or not validate_series(bench_arr):
        return BacktestResult(error="Real-data simulation produced invalid values.")

    total_return = safe_div(nav[-1] - 100.0, 100.0, 0.0)
    bench_return_val = safe_div(benchmark_nav[-1] - 100.0, 100.0, 0.0)
    avg_return = mean(daily_returns)
    std_return = max(1e-8, stddev(daily_returns))
    sharpe = sanitize_number(safe_div(avg_return, std_return, 0.0) * (252 ** 0.5), 0.0)
    ann_vol_val = std_return * (252 ** 0.5) if std_return > 1e-8 else 0.0

    metrics = BacktestMetrics(
        sharpe=sharpe,
        total_return=total_return,
        bench_return=bench_return_val,
        max_dd=max_drawdown_val,
        max_dd_day=max_drawdown_day,
        win_rate=safe_div(wins, total_trades, 0.0),
        ann_vol=ann_vol_val,
        calmar=safe_div(total_return, max_drawdown_val, 0.0) if max_drawdown_val > 0 else 0.0,
        sortino=bm.sortino_ratio(daily_returns),
        ann_return=bm.annualized_return(nav),
    )
    return BacktestResult(
        nav=nav,
        benchmark_nav=benchmark_nav,
        drawdowns=drawdowns,
        monthly_returns=bm.monthly_returns(nav),
        daily_returns=daily_returns,
        metrics=metrics,
    )
