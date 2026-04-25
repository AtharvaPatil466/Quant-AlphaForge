"""
Feature engineering — vectorized computations for the full universe.

All functions accept numpy arrays or pandas Series and return the same type.
NaN handling: NaN in → NaN out, no silent fill.
"""

from __future__ import annotations

import math
from typing import Union

import numpy as np

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False


ArrayLike = Union[np.ndarray, "pd.Series"]


def _to_numpy(arr: ArrayLike) -> np.ndarray:
    if HAS_PANDAS and isinstance(arr, pd.Series):
        return arr.values.astype(np.float64)
    return np.asarray(arr, dtype=np.float64)


def _wrap_output(result: np.ndarray, original: ArrayLike) -> ArrayLike:
    """Return result in the same type as the original input."""
    if HAS_PANDAS and isinstance(original, pd.Series):
        return pd.Series(result, index=original.index, name=original.name)
    return result


def log_returns(prices: ArrayLike, window: int = 1) -> ArrayLike:
    """Rolling log return over a given window.

    Formula: ln(P_t / P_{t-window})
    """
    p = _to_numpy(prices)
    result = np.full_like(p, np.nan)
    for i in range(window, len(p)):
        if p[i - window] > 0 and p[i] > 0:
            result[i] = math.log(p[i] / p[i - window])
    return _wrap_output(result, prices)


def volume_ratio(volumes: ArrayLike, window: int = 20) -> ArrayLike:
    """Ratio of current volume to rolling mean volume.

    Formula: V_t / mean(V_{t-window:t})
    """
    v = _to_numpy(volumes)
    result = np.full_like(v, np.nan, dtype=np.float64)
    for i in range(window, len(v)):
        avg = np.mean(v[i - window : i])
        if avg > 0:
            result[i] = v[i] / avg
    return _wrap_output(result, volumes)


def realized_vol(returns: ArrayLike, window: int = 21) -> ArrayLike:
    """Rolling annualized volatility from daily returns.

    Formula: std(R_{t-window:t}, ddof=1) × sqrt(252)
    """
    r = _to_numpy(returns)
    result = np.full(len(r), np.nan, dtype=np.float64)
    for i in range(window, len(r)):
        chunk = r[i - window : i]
        if np.any(np.isfinite(chunk)):
            result[i] = float(np.nanstd(chunk, ddof=1)) * math.sqrt(252)
    return _wrap_output(result, returns)


def rsi(prices: ArrayLike, period: int = 14) -> ArrayLike:
    """Relative Strength Index.

    Uses Wilder's smoothing method (SMA-based for simplicity matching JS).
    Output bounded [0, 100]. NaN for insufficient data.
    """
    p = _to_numpy(prices)
    result = np.full(len(p), np.nan, dtype=np.float64)

    for i in range(period, len(p)):
        changes = np.diff(p[i - period : i + 1])
        gains = np.where(changes > 0, changes, 0.0)
        losses = np.where(changes < 0, -changes, 0.0)
        avg_gain = np.mean(gains)
        avg_loss = np.mean(losses)
        if avg_loss == 0:
            result[i] = 100.0 if avg_gain > 0 else 50.0
        else:
            rs = avg_gain / avg_loss
            result[i] = 100.0 - 100.0 / (1.0 + rs)

    return _wrap_output(result, prices)


def autocorrelation(returns: ArrayLike, lag: int = 1) -> ArrayLike:
    """Rolling autocorrelation coefficient at a given lag.

    Uses a rolling window of 60 observations.
    """
    r = _to_numpy(returns)
    window = max(60, lag + 10)
    result = np.full(len(r), np.nan, dtype=np.float64)

    for i in range(window, len(r)):
        chunk = r[i - window : i]
        if np.all(np.isfinite(chunk)):
            x = chunk[: -lag]
            y = chunk[lag:]
            mx, my = np.mean(x), np.mean(y)
            num = np.sum((x - mx) * (y - my))
            dx = np.sum((x - mx) ** 2)
            dy = np.sum((y - my) ** 2)
            denom = math.sqrt(dx * dy)
            result[i] = num / denom if denom > 1e-12 else 0.0

    return _wrap_output(result, returns)


def hurst_exponent(prices: ArrayLike, window: int = 100) -> ArrayLike:
    """Rolling Hurst exponent — indicates trending (H>0.5) vs mean-reverting (H<0.5).

    Uses rescaled range (R/S) analysis.
    """
    p = _to_numpy(prices)
    result = np.full(len(p), np.nan, dtype=np.float64)

    for i in range(window, len(p)):
        log_rets = np.diff(np.log(np.maximum(p[i - window : i + 1], 1e-10)))
        n = len(log_rets)
        if n < 20 or not np.all(np.isfinite(log_rets)):
            continue

        # R/S analysis at multiple sub-period lengths
        max_k = n // 2
        if max_k < 4:
            continue

        rs_list = []
        ns_list = []
        for k in [max_k // 4, max_k // 2, max_k]:
            if k < 4:
                continue
            num_segments = n // k
            rs_vals = []
            for seg in range(num_segments):
                sub = log_rets[seg * k : (seg + 1) * k]
                m = np.mean(sub)
                s = np.std(sub, ddof=1)
                if s < 1e-12:
                    continue
                cumdev = np.cumsum(sub - m)
                r = np.max(cumdev) - np.min(cumdev)
                rs_vals.append(r / s)
            if rs_vals:
                rs_list.append(math.log(np.mean(rs_vals)))
                ns_list.append(math.log(k))

        if len(rs_list) >= 2:
            # Simple linear regression: log(R/S) = H * log(n) + c
            x = np.array(ns_list)
            y = np.array(rs_list)
            mx, my = np.mean(x), np.mean(y)
            num = np.sum((x - mx) * (y - my))
            denom = np.sum((x - mx) ** 2)
            h = num / denom if denom > 1e-12 else 0.5
            result[i] = np.clip(h, 0.0, 1.0)

    return _wrap_output(result, prices)


def z_score(series: ArrayLike, window: int = 252) -> ArrayLike:
    """Rolling z-score: (x - rolling_mean) / rolling_std.

    NaN for insufficient data.
    """
    s = _to_numpy(series)
    result = np.full(len(s), np.nan, dtype=np.float64)
    for i in range(window, len(s)):
        chunk = s[i - window : i + 1]
        finite = chunk[np.isfinite(chunk)]
        if len(finite) < 2:
            continue
        m = np.mean(finite)
        sd = np.std(finite, ddof=1)
        if sd > 1e-12 and np.isfinite(s[i]):
            result[i] = (s[i] - m) / sd
    return _wrap_output(result, series)


def normalize_cross_sectional(matrix: np.ndarray) -> np.ndarray:
    """Z-score each row of a matrix (cross-sectional normalization per day).

    Input:  (n_days, n_tickers) or (n_tickers,) for single-day.
    Output: same shape, mean ≈ 0 and std ≈ 1 across tickers per day.
    """
    arr = np.asarray(matrix, dtype=np.float64)
    if arr.ndim == 1:
        arr = arr.reshape(1, -1)

    result = np.zeros_like(arr)
    for i in range(arr.shape[0]):
        row = arr[i]
        finite_mask = np.isfinite(row)
        if np.sum(finite_mask) < 2:
            result[i] = 0.0
            continue
        finite = row[finite_mask]
        m = np.mean(finite)
        s = np.std(finite, ddof=1)
        if s < 1e-12:
            result[i] = 0.0
        else:
            result[i] = np.where(finite_mask, (row - m) / s, 0.0)

    return result.squeeze() if matrix.ndim == 1 else result
