"""
Cross-sectional z-score normalization and signal classification.

Ports the JS computeFactorScores z-score logic and composite scoring.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np

from .data import (
    PriceSeries,
    safe_div,
    sanitize_number,
    clamp,
    mean,
    stddev,
    generate_dataset,
    get_tickers,
    FACTOR_NAMES,
)
from .factors import get_factor, JS_FACTOR_NAMES, ALL_FACTOR_NAMES


@dataclass
class TickerScore:
    ticker: str
    name: str
    raw_score: float
    score: float  # z-scored and scaled
    signal: str   # 'LONG', 'SHORT', or 'NEUTRAL'


@dataclass
class ScanResult:
    ticker: str
    name: str
    composite: float
    signal: str
    ret5d: float
    volume: float
    price: float
    factor_scores: Dict[str, float]


def z_score(values: np.ndarray) -> np.ndarray:
    """Cross-sectional z-score normalization matching JS logic.

    JS: mu = mean(rawValues), sigma = max(1e-8, stddev(rawValues))
        z[i] = sanitizeNumber((raw[i] - mu) / sigma, 0)
    """
    if len(values) == 0:
        return np.array([], dtype=np.float64)

    finite_mask = np.isfinite(values)
    if not np.any(finite_mask):
        return np.zeros(len(values), dtype=np.float64)

    finite_vals = values[finite_mask]
    mu = float(np.mean(finite_vals))
    sigma = max(1e-8, float(np.std(finite_vals, ddof=1)) if len(finite_vals) > 1 else 0.0)

    result = np.zeros(len(values), dtype=np.float64)
    for i in range(len(values)):
        if np.isfinite(values[i]):
            z = (values[i] - mu) / sigma
            result[i] = sanitize_number(z, 0.0)
        else:
            result[i] = 0.0
    return result


def compute_factor_scores_js(
    dataset: Dict[str, PriceSeries],
    lookback_days: int,
) -> Dict[str, Dict[str, float]]:
    """Port of JS computeFactorScores — computes z-scored factor values and composite.

    Returns dict of ticker -> {factor_name: z_score, ..., '_composite': float, '_signal': str}
    Uses only the 5 JS factors for composite scoring (matches JS behavior).
    """
    tickers = list(dataset.keys())
    if not tickers:
        return {}

    # Compute raw scores for all JS factors
    raw_scores: Dict[str, Dict[str, float]] = {}
    for ticker in tickers:
        d = dataset[ticker]
        raw_scores[ticker] = {}
        for factor_name in JS_FACTOR_NAMES:
            fn = get_factor(factor_name)
            raw_scores[ticker][factor_name] = fn(
                d.prices, d.volumes, d.returns, lookback_days
            )

    # Cross-sectional z-score normalization (per factor)
    z_scored: Dict[str, Dict[str, float]] = {t: {} for t in tickers}
    for factor_name in JS_FACTOR_NAMES:
        raw_vals = np.array([raw_scores[t][factor_name] for t in tickers])
        mu = mean(raw_vals)
        sigma = max(1e-8, stddev(raw_vals))
        for i, ticker in enumerate(tickers):
            z = safe_div(raw_scores[ticker][factor_name] - mu, sigma, 0.0)
            z_scored[ticker][factor_name] = sanitize_number(z, 0.0)

    # Composite score (equal-weighted, scaled to [-100, 100])
    for ticker in tickers:
        factor_values = [z_scored[ticker][f] for f in JS_FACTOR_NAMES]
        composite = mean(factor_values) * 40  # JS scaling
        z_scored[ticker]["_composite"] = clamp(sanitize_number(composite, 0.0), -100, 100)
        if composite > 40:
            z_scored[ticker]["_signal"] = "LONG"
        elif composite < -40:
            z_scored[ticker]["_signal"] = "SHORT"
        else:
            z_scored[ticker]["_signal"] = "NEUTRAL"

    return z_scored


def compute_factor_scores(
    sector: str,
    lookback: int,
    factor_name: str,
    base_seed: int = 42,
) -> List[TickerScore]:
    """Compute z-scored factor scores for a single factor across a sector."""
    dataset = generate_dataset(sector, lookback, base_seed)
    tickers = list(dataset.keys())
    if not tickers:
        return []

    fn = get_factor(factor_name)

    raw_vals = []
    for ticker in tickers:
        d = dataset[ticker]
        raw = fn(d.prices, d.volumes, d.returns, lookback)
        raw_vals.append(raw)

    raw_arr = np.array(raw_vals)
    z_vals = z_score(raw_arr)

    results = []
    for i, ticker in enumerate(tickers):
        d = dataset[ticker]
        score = z_vals[i] * 50  # scale to ±100 range
        if z_vals[i] > 0.8:
            signal = "LONG"
        elif z_vals[i] < -0.8:
            signal = "SHORT"
        else:
            signal = "NEUTRAL"
        results.append(TickerScore(
            ticker=ticker,
            name=d.name,
            raw_score=raw_vals[i],
            score=score,
            signal=signal,
        ))
    return results


def scan_universe(
    sector: str, lookback: int, base_seed: int = 42
) -> List[ScanResult]:
    """Full universe scan — all factors, all tickers, with composite scoring."""
    dataset = generate_dataset(sector, lookback, base_seed)
    scores = compute_factor_scores_js(dataset, lookback)

    results = []
    for ticker, d in dataset.items():
        s = scores.get(ticker, {})
        n = len(d.prices)
        ret5d = safe_div(
            d.prices[n - 1] - d.prices[max(0, n - 6)],
            d.prices[max(0, n - 6)],
            0.0,
        )
        results.append(ScanResult(
            ticker=ticker,
            name=d.name,
            composite=s.get("_composite", 0.0),
            signal=s.get("_signal", "NEUTRAL"),
            ret5d=ret5d,
            volume=float(d.volumes[n - 1]),
            price=float(d.prices[n - 1]),
            factor_scores={f: s.get(f, 0.0) for f in JS_FACTOR_NAMES},
        ))
    return results
