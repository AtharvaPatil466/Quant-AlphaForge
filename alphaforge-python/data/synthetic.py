"""
Synthetic market data generator — exact port of JS generatePrices / generateDataset.

Generates deterministic price and volume series from seeded PRNG so that
outputs match the JS frontend given the same seed and ticker.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

import numpy as np

from .prng import Mulberry32, hash_string, normal_random


# ── Defensive Utilities (match JS safeDiv / sanitizeNumber / clamp) ──────────

def safe_div(a: float, b: float, fallback: float = 0.0) -> float:
    if b == 0 or not np.isfinite(b):
        return fallback
    result = a / b
    return result if np.isfinite(result) else fallback


def sanitize_number(x: float, fallback: float = 0.0) -> float:
    if not isinstance(x, (int, float, np.integer, np.floating)) or not np.isfinite(float(x)):
        return fallback
    return float(x)


def clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def validate_series(arr: np.ndarray) -> bool:
    return bool(np.all(np.isfinite(arr)))


# ── Price Series Container ───────────────────────────────────────────────────

@dataclass
class PriceSeries:
    """Container for a single ticker's synthetic price/volume data."""
    ticker: str
    name: str
    prices: np.ndarray   # shape (days+1,)
    volumes: np.ndarray  # shape (days+1,)
    returns: np.ndarray  # shape (days+1,)  — returns[0] = 0


# ── Price Generation (exact port of JS generatePrices) ───────────────────────

def generate_prices(ticker: str, days: int, seed: int = 42) -> tuple:
    """Port of JS generatePrices(ticker, days, seed).

    Returns (prices, volumes) as numpy arrays matching JS output exactly.
    Seed derivation: hash_string(ticker) + seed (matches JS).
    """
    rng = Mulberry32(hash_string(ticker) + seed)

    base_price = 50 + rng() * 450
    annual_drift = (rng() - 0.4) * 0.3
    daily_drift = annual_drift / 252
    daily_vol = 0.01 + rng() * 0.03

    prices = [max(0.01, base_price)]
    volumes: List[int] = []

    for i in range(1, days + 1):
        noise = normal_random(rng)
        vol_multiplier = 2.0 if rng() < 0.05 else 1.0
        ret = daily_drift + daily_vol * vol_multiplier * noise
        new_price = prices[i - 1] * (1 + clamp(ret, -0.15, 0.15))
        new_price = max(0.01, sanitize_number(new_price, prices[i - 1]))
        prices.append(new_price)
        volumes.append(max(100000, int((1 + rng() * 5) * 1000000)))

    # JS: volumes.unshift(Math.floor((1 + rng() * 5) * 1000000))
    first_vol = int((1 + rng() * 5) * 1000000)
    volumes.insert(0, first_vol)

    return np.array(prices, dtype=np.float64), np.array(volumes, dtype=np.float64)


def compute_returns(prices: np.ndarray) -> np.ndarray:
    """Port of JS computeReturns — returns[0] = 0, rest are simple returns."""
    returns = np.zeros(len(prices), dtype=np.float64)
    for i in range(1, len(prices)):
        returns[i] = safe_div(prices[i] - prices[i - 1], prices[i - 1], 0.0)
    return returns


def generate_dataset(
    sector: str, lookback_days: int, seed: int = 42
) -> Dict[str, PriceSeries]:
    """Port of JS generateDataset — returns dict of ticker -> PriceSeries."""
    from .universe import get_tickers
    tickers = get_tickers(sector)
    dataset: Dict[str, PriceSeries] = {}
    for t in tickers:
        prices, volumes = generate_prices(t.ticker, lookback_days, seed)
        dataset[t.ticker] = PriceSeries(
            ticker=t.ticker,
            name=t.name,
            prices=prices,
            volumes=volumes,
            returns=compute_returns(prices),
        )
    return dataset


# ── Statistical Helpers (match JS mean / stddev / correlation) ───────────────

def mean(arr) -> float:
    """Port of JS mean — sanitizes each element."""
    if arr is None or len(arr) == 0:
        return 0.0
    total = sum(sanitize_number(float(x), 0.0) for x in arr)
    return total / len(arr)


def stddev(arr) -> float:
    """Port of JS stddev — sample standard deviation."""
    if arr is None or len(arr) < 2:
        return 0.0
    m = mean(arr)
    sum_sq = sum((sanitize_number(float(x), 0.0) - m) ** 2 for x in arr)
    return (sum_sq / (len(arr) - 1)) ** 0.5


def correlation(x, y) -> float:
    """Port of JS correlation — Pearson r with sanitization."""
    if x is None or y is None or len(x) != len(y) or len(x) < 2:
        return 0.0
    mx, my = mean(x), mean(y)
    num = dx = dy = 0.0
    for i in range(len(x)):
        xi = sanitize_number(float(x[i]), 0.0) - mx
        yi = sanitize_number(float(y[i]), 0.0) - my
        num += xi * yi
        dx += xi * xi
        dy += yi * yi
    denom = (dx * dy) ** 0.5
    return sanitize_number(safe_div(num, denom, 0.0), 0.0)


# ── Benchmark Index Generation ───────────────────────────────────────────────

def generate_benchmark_index(days: int, seed: int = 99) -> np.ndarray:
    """Port of JS generateBenchmarkIndex."""
    rng = Mulberry32(seed)
    prices = [1000.0]
    for i in range(1, days + 1):
        ret = 0.0003 + 0.012 * normal_random(rng)
        new_price = prices[i - 1] * (1 + clamp(ret, -0.08, 0.08))
        prices.append(max(0.01, new_price))
    return np.array(prices, dtype=np.float64)
