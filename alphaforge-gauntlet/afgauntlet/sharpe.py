"""Sharpe + higher-moment primitives (canonical).

Consolidated verbatim from ``alphaforge-vix/gauntlet/stats.py`` so the
reconciliation tests pass to float equality. Pure numpy/python — no scipy.

Annualization convention: 252 trading days/year. Sharpe is computed against
zero (no risk-free subtraction at this layer — carry is handled upstream in
each substrate's NAV calculation).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

ANNUALIZATION = 252.0
_ZERO_STD_TOL = 1e-12


def annualized_sharpe(daily_returns: np.ndarray | pd.Series,
                      annualization: float = ANNUALIZATION) -> float:
    """Vanilla annualized Sharpe: mean / std × √252. Zero if std is at or
    near machine zero (FP-tolerant)."""
    if isinstance(daily_returns, pd.Series):
        daily_returns = daily_returns.dropna().to_numpy()
    daily_returns = np.asarray(daily_returns, dtype=float)
    if daily_returns.size < 2:
        return float("nan")
    mu = float(np.mean(daily_returns))
    sd = float(np.std(daily_returns, ddof=1))
    if sd < _ZERO_STD_TOL or not np.isfinite(sd):
        return 0.0
    return mu / sd * math.sqrt(annualization)


def _moment(x: np.ndarray, k: int) -> float:
    """k-th sample central moment."""
    mu = np.mean(x)
    return float(np.mean((x - mu) ** k))


def sample_skewness(returns: np.ndarray) -> float:
    """Population skewness g_1 = m3 / m2^(3/2) (numpy default convention)."""
    m2 = _moment(returns, 2)
    if m2 == 0.0:
        return 0.0
    m3 = _moment(returns, 3)
    return m3 / (m2 ** 1.5)


def sample_excess_kurtosis(returns: np.ndarray) -> float:
    """Population excess kurtosis g_2 = m4 / m2^2 − 3."""
    m2 = _moment(returns, 2)
    if m2 == 0.0:
        return 0.0
    m4 = _moment(returns, 4)
    return m4 / (m2 ** 2) - 3.0


def cornish_fisher_sharpe(
    daily_returns: np.ndarray | pd.Series,
    alpha: float = 0.05,
    annualization: float = ANNUALIZATION,
) -> float:
    """Cornish-Fisher modified Sharpe (Favre & Galeano 2002).

    Penalizes negative skew + positive excess kurtosis. For Gaussian returns
    CF-Sharpe == Sharpe; for negative-skew returns CF-Sharpe < Sharpe.
    """
    if isinstance(daily_returns, pd.Series):
        daily_returns = daily_returns.dropna().to_numpy()
    daily_returns = np.asarray(daily_returns, dtype=float)
    if daily_returns.size < 4:
        return float("nan")
    mu = float(np.mean(daily_returns))
    sd = float(np.std(daily_returns, ddof=1))
    if sd == 0.0 or not np.isfinite(sd):
        return 0.0
    s = sample_skewness(daily_returns)
    k = sample_excess_kurtosis(daily_returns)
    if alpha == 0.05:
        z = -1.6448536269514722
    elif alpha == 0.01:
        z = -2.3263478740408408
    else:
        raise ValueError(
            "cornish_fisher_sharpe: only alpha=0.05 and alpha=0.01 supported"
        )
    z_cf = (z
            + (z ** 2 - 1) * s / 6.0
            + (z ** 3 - 3 * z) * k / 24.0
            - (2 * z ** 3 - 5 * z) * (s ** 2) / 36.0)
    if z == 0.0:
        adjustment = 1.0
    else:
        adjustment = z_cf / z
    base_sharpe = mu / sd * math.sqrt(annualization)
    if adjustment == 0.0:
        return float("inf") if base_sharpe > 0 else (
               float("-inf") if base_sharpe < 0 else 0.0)
    return float(base_sharpe / abs(adjustment))


def sign_agreement(
    returns_oos_a: np.ndarray | pd.Series,
    returns_oos_b: np.ndarray | pd.Series,
) -> bool:
    """Both OOS windows must have strictly positive Sharpe."""
    s_a = annualized_sharpe(returns_oos_a)
    s_b = annualized_sharpe(returns_oos_b)
    if not (np.isfinite(s_a) and np.isfinite(s_b)):
        return False
    return s_a > 0 and s_b > 0
