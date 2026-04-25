"""
Alpha factors — all six factor computations.

The first five factors match the JS frontend's computeFactorScores logic.
The sixth (Low Volatility) is a new addition for the MARL engine.

Each factor function takes (prices, volumes, returns, day) and returns a raw score.
"""

from __future__ import annotations

import math
from typing import Callable, Dict

import numpy as np

from .data import safe_div, sanitize_number, clamp, mean


def compute_rsi(prices) -> float:
    """Port of JS computeRSI — 14-period RSI from a price slice.

    JS reference:
        function computeRSI(prices) {
            if (prices.length < 2) return 50;
            let gains = 0, losses = 0;
            for (let i = 1; i < prices.length; i++) {
                const change = prices[i] - prices[i - 1];
                if (change > 0) gains += change;
                else losses -= change;
            }
            const periods = prices.length - 1;
            const avgGain = safeDiv(gains, periods, 0);
            const avgLoss = safeDiv(losses, periods, 0);
            const rs = safeDiv(avgGain, avgLoss, 1);
            return sanitizeNumber(100 - safeDiv(100, 1 + rs, 50), 50);
        }
    """
    if len(prices) < 2:
        return 50.0
    gains = 0.0
    losses = 0.0
    for i in range(1, len(prices)):
        change = prices[i] - prices[i - 1]
        if change > 0:
            gains += change
        else:
            losses -= change  # losses is positive
    periods = len(prices) - 1
    avg_gain = safe_div(gains, periods, 0.0)
    avg_loss = safe_div(losses, periods, 0.0)
    rs = safe_div(avg_gain, avg_loss, 1.0)
    return sanitize_number(100.0 - safe_div(100.0, 1.0 + rs, 50.0), 50.0)


# ── Individual Factor Functions ──────────────────────────────────────────────

def momentum_12_1(
    prices: np.ndarray,
    volumes: np.ndarray,
    returns: np.ndarray,
    lookback: int,
) -> float:
    """Momentum (12-1): return from ~252 days ago to ~21 days ago.

    JS: momStart = max(0, n - min(252, lookback))
        momEnd   = max(momStart+1, n - 21)
        score    = (p[momEnd] - p[momStart]) / p[momStart]
    """
    n = len(prices)
    mom_start = max(0, n - min(252, lookback))
    mom_end = max(mom_start + 1, n - 21)
    return safe_div(prices[mom_end] - prices[mom_start], prices[mom_start], 0.0)


def mean_reversion_5d(
    prices: np.ndarray,
    volumes: np.ndarray,
    returns: np.ndarray,
    lookback: int,
) -> float:
    """Mean Reversion (5d): negative of last 5-day return.

    JS: mr5Start = max(0, n - 6)
        score    = -(p[n-1] - p[mr5Start]) / p[mr5Start]
    """
    n = len(prices)
    mr5_start = max(0, n - 6)
    return -safe_div(prices[n - 1] - prices[mr5_start], prices[mr5_start], 0.0)


def volume_surge(
    prices: np.ndarray,
    volumes: np.ndarray,
    returns: np.ndarray,
    lookback: int,
) -> float:
    """Volume Surge: ratio of 5d avg volume to 20d avg volume, minus 1.

    JS: vol5  = mean(v.slice(-5))
        vol20 = mean(v.slice(-20))
        score = (vol5 - vol20) / vol20
    """
    vol5 = mean(volumes[-5:])
    vol20 = mean(volumes[-20:])
    return safe_div(vol5 - vol20, vol20, 0.0)


def rsi_divergence(
    prices: np.ndarray,
    volumes: np.ndarray,
    returns: np.ndarray,
    lookback: int,
) -> float:
    """RSI Divergence: normalized RSI signal.

    JS: rsi   = computeRSI(p.slice(-15))
        score = (rsi - 50) / 50
    """
    rsi = compute_rsi(prices[-15:])
    return (rsi - 50.0) / 50.0


def earnings_drift(
    prices: np.ndarray,
    volumes: np.ndarray,
    returns: np.ndarray,
    lookback: int,
) -> float:
    """Earnings Drift: recent 10-day return as proxy for post-earnings drift.

    JS: ed10Start = max(0, n - 11)
        score     = (p[n-1] - p[ed10Start]) / p[ed10Start]
    """
    n = len(prices)
    ed10_start = max(0, n - 11)
    return safe_div(prices[n - 1] - prices[ed10_start], prices[ed10_start], 0.0)


def low_volatility(
    prices: np.ndarray,
    volumes: np.ndarray,
    returns: np.ndarray,
    lookback: int,
) -> float:
    """Low Volatility: negative annualized vol of last 60 daily log returns.

    Not in JS frontend — added for MARL engine. Lower vol = higher score.
    """
    n = len(prices)
    if n < 61:
        return 0.0
    log_rets = np.log(prices[-60:] / prices[-61:-1])
    daily_std = float(np.std(log_rets, ddof=1))
    return -daily_std * math.sqrt(252)


# ── Factor Registry ──────────────────────────────────────────────────────────

_FACTOR_FUNCTIONS: Dict[str, Callable] = {
    "Momentum (12-1)": momentum_12_1,
    "Mean Reversion (5d)": mean_reversion_5d,
    "Volume Surge": volume_surge,
    "RSI Divergence": rsi_divergence,
    "Earnings Drift": earnings_drift,
    "Low Volatility": low_volatility,
}

# The first 5 match JS FACTOR_NAMES; the 6th is Python-only.
JS_FACTOR_NAMES = [
    "Momentum (12-1)",
    "Mean Reversion (5d)",
    "Volume Surge",
    "RSI Divergence",
    "Earnings Drift",
]

ALL_FACTOR_NAMES = list(_FACTOR_FUNCTIONS.keys())


def get_factor(name: str) -> Callable:
    """Return a factor function by name."""
    if name not in _FACTOR_FUNCTIONS:
        raise ValueError(
            f"Unknown factor '{name}'. Available: {list(_FACTOR_FUNCTIONS.keys())}"
        )
    return _FACTOR_FUNCTIONS[name]
