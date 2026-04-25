"""
Performance metrics — all 9 functions specified in the plan.

Pure functions for reuse by backtest engine, scanner, and MARL reward.
All functions handle empty arrays and edge cases without crashing.
"""

from __future__ import annotations

import math
from typing import List, Tuple, Union

import numpy as np

ArrayLike = Union[list, np.ndarray]


def _to_array(arr: ArrayLike) -> np.ndarray:
    if isinstance(arr, np.ndarray):
        return arr.astype(np.float64)
    return np.array(arr, dtype=np.float64)


def sharpe_ratio(returns: ArrayLike, periods_per_year: int = 252) -> float:
    """Annualized Sharpe ratio (assumes zero risk-free rate)."""
    r = _to_array(returns)
    if len(r) < 2:
        return 0.0
    m = float(np.mean(r))
    s = float(np.std(r, ddof=1))
    if s < 1e-12:
        return 0.0
    result = (m / s) * math.sqrt(periods_per_year)
    return result if math.isfinite(result) else 0.0


def max_drawdown(nav_series: ArrayLike) -> Tuple[float, int, int]:
    """Maximum drawdown as (dd_fraction, peak_day, trough_day).

    Returns positive fraction (e.g. 0.15 = 15% drawdown).
    """
    nav = _to_array(nav_series)
    if len(nav) < 2:
        return (0.0, 0, 0)
    peak = nav[0]
    peak_day = 0
    max_dd = 0.0
    max_dd_peak = 0
    max_dd_trough = 0
    for i in range(1, len(nav)):
        if nav[i] > peak:
            peak = nav[i]
            peak_day = i
        dd = (peak - nav[i]) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
            max_dd_peak = peak_day
            max_dd_trough = i
    return (max_dd if math.isfinite(max_dd) else 0.0, max_dd_peak, max_dd_trough)


def calmar_ratio(returns: ArrayLike, nav_series: ArrayLike) -> float:
    """Calmar ratio = annualized return / |max drawdown|."""
    ann_ret = annualized_return(nav_series)
    dd, _, _ = max_drawdown(nav_series)
    if abs(dd) < 1e-12:
        return 0.0
    ratio = ann_ret / abs(dd)
    return ratio if math.isfinite(ratio) else 0.0


def win_rate(returns: ArrayLike) -> float:
    """Fraction of periods with positive returns."""
    r = _to_array(returns)
    if len(r) == 0:
        return 0.0
    return float(np.sum(r > 0)) / len(r)


def annualized_return(nav_series: ArrayLike, periods: int = 252) -> float:
    """Annualized return from a NAV series.

    Formula: (NAV_end / NAV_start)^(periods / n_days) - 1
    """
    nav = _to_array(nav_series)
    if len(nav) < 2 or nav[0] <= 0:
        return 0.0
    total_return = nav[-1] / nav[0]
    if total_return <= 0:
        return -1.0
    n_days = len(nav) - 1
    ann = total_return ** (periods / n_days) - 1
    return ann if math.isfinite(ann) else 0.0


def annualized_vol(returns: ArrayLike, periods: int = 252) -> float:
    """Annualized volatility from daily returns."""
    r = _to_array(returns)
    if len(r) < 2:
        return 0.0
    vol = float(np.std(r, ddof=1)) * math.sqrt(periods)
    return vol if math.isfinite(vol) else 0.0


def information_ratio(
    strategy_returns: ArrayLike, benchmark_returns: ArrayLike
) -> float:
    """Information ratio = mean(excess returns) / std(excess returns), annualized."""
    s = _to_array(strategy_returns)
    b = _to_array(benchmark_returns)
    min_len = min(len(s), len(b))
    if min_len < 2:
        return 0.0
    excess = s[:min_len] - b[:min_len]
    m = float(np.mean(excess))
    sd = float(np.std(excess, ddof=1))
    if sd < 1e-12:
        return 0.0
    ir = (m / sd) * math.sqrt(252)
    return ir if math.isfinite(ir) else 0.0


def sortino_ratio(returns: ArrayLike, periods: int = 252) -> float:
    """Sortino ratio — Sharpe variant using only downside deviation.

    Formula: mean(R) / std(R[R<0]) × sqrt(periods)
    """
    r = _to_array(returns)
    if len(r) < 2:
        return 0.0
    m = float(np.mean(r))
    downside = r[r < 0]
    if len(downside) < 2:
        return 0.0 if m <= 0 else float("inf")
    dd = float(np.std(downside, ddof=1))
    if dd < 1e-12:
        return 0.0
    result = (m / dd) * math.sqrt(periods)
    return result if math.isfinite(result) else 0.0


def monthly_returns(nav_series: ArrayLike) -> List[float]:
    """Monthly returns computed from 21-day NAV chunks (matching JS)."""
    nav = _to_array(nav_series)
    if len(nav) < 2:
        return []
    daily_rets = np.diff(nav) / nav[:-1]
    months = []
    for i in range(0, len(daily_rets), 21):
        chunk = daily_rets[i : i + 21]
        month_ret = float(np.prod(1 + chunk) - 1)
        months.append(month_ret if math.isfinite(month_ret) else 0.0)
    return months


# ── Additional utility metrics ───────────────────────────────────────────────

def rolling_sharpe(
    nav_series: ArrayLike, window: int = 63
) -> np.ndarray:
    """Rolling Sharpe ratio over a given window of NAV values."""
    nav = _to_array(nav_series)
    if len(nav) < window + 1:
        return np.array([], dtype=np.float64)
    rets = np.diff(nav) / nav[:-1]
    result = np.full(len(rets), np.nan, dtype=np.float64)
    for i in range(window - 1, len(rets)):
        chunk = rets[i - window + 1 : i + 1]
        m = float(np.mean(chunk))
        s = float(np.std(chunk, ddof=1))
        if s > 1e-12:
            result[i] = (m / s) * math.sqrt(252)
    return result
