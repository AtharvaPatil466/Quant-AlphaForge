"""
Performance metrics — pure functions for reuse by backtest engine and MARL.

All functions handle empty arrays and edge cases without crashing.
"""

from __future__ import annotations

import math
from typing import Union

import numpy as np

ArrayLike = Union[list, np.ndarray]


def _to_array(arr: ArrayLike) -> np.ndarray:
    if isinstance(arr, np.ndarray):
        return arr.astype(np.float64)
    return np.array(arr, dtype=np.float64)


def annualized_sharpe(daily_returns: ArrayLike) -> float:
    """Annualized Sharpe ratio (assumes zero risk-free rate)."""
    r = _to_array(daily_returns)
    if len(r) < 2:
        return 0.0
    m = float(np.mean(r))
    s = float(np.std(r, ddof=1))
    if s < 1e-12:
        return 0.0
    sharpe = (m / s) * math.sqrt(252)
    return sharpe if math.isfinite(sharpe) else 0.0


def max_drawdown(nav_history: ArrayLike) -> float:
    """Maximum drawdown as a positive fraction (e.g. 0.15 = 15% drawdown)."""
    nav = _to_array(nav_history)
    if len(nav) < 2:
        return 0.0
    peak = nav[0]
    max_dd = 0.0
    for v in nav[1:]:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    return max_dd if math.isfinite(max_dd) else 0.0


def max_drawdown_with_day(nav_history: ArrayLike) -> tuple:
    """Returns (max_dd, day_index) where max drawdown occurred."""
    nav = _to_array(nav_history)
    if len(nav) < 2:
        return 0.0, 0
    peak = nav[0]
    max_dd = 0.0
    max_dd_day = 0
    for i, v in enumerate(nav[1:], 1):
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
            max_dd_day = i
    return (max_dd if math.isfinite(max_dd) else 0.0, max_dd_day)


def win_rate(daily_returns: ArrayLike) -> float:
    """Fraction of days with positive returns."""
    r = _to_array(daily_returns)
    if len(r) == 0:
        return 0.0
    wins = int(np.sum(r > 0))
    return wins / len(r)


def calmar_ratio(ann_return: float, max_dd: float) -> float:
    """Calmar ratio = annualized return / |max drawdown|."""
    if abs(max_dd) < 1e-12:
        return 0.0
    ratio = ann_return / abs(max_dd)
    return ratio if math.isfinite(ratio) else 0.0


def annualized_volatility(daily_returns: ArrayLike) -> float:
    """Annualized volatility from daily returns."""
    r = _to_array(daily_returns)
    if len(r) < 2:
        return 0.0
    vol = float(np.std(r, ddof=1)) * math.sqrt(252)
    return vol if math.isfinite(vol) else 0.0


def rolling_sharpe(
    nav_history: ArrayLike, window: int = 63
) -> np.ndarray:
    """Rolling Sharpe ratio over a given window of NAV values."""
    nav = _to_array(nav_history)
    if len(nav) < window + 1:
        return np.array([], dtype=np.float64)
    # Compute daily returns from NAV
    rets = np.diff(nav) / nav[:-1]
    result = np.full(len(rets), np.nan, dtype=np.float64)
    for i in range(window - 1, len(rets)):
        chunk = rets[i - window + 1 : i + 1]
        m = float(np.mean(chunk))
        s = float(np.std(chunk, ddof=1))
        if s > 1e-12:
            result[i] = (m / s) * math.sqrt(252)
    return result


def information_ratio(
    strategy_rets: ArrayLike, benchmark_rets: ArrayLike
) -> float:
    """Information ratio = mean(excess returns) / std(excess returns)."""
    s = _to_array(strategy_rets)
    b = _to_array(benchmark_rets)
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
