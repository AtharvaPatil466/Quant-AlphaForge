"""
Correlation laboratory — factor correlation matrix, IC, and turnover.

Ports JS computeCorrelationMatrix, computeIC, and computeFactorTurnover.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

import numpy as np

from .data import (
    generate_dataset,
    safe_div,
    sanitize_number,
    mean,
    correlation,
    PriceSeries,
)
from .prng import Mulberry32, hash_string
from .scoring import compute_factor_scores_js
from .factors import JS_FACTOR_NAMES


@dataclass
class CorrelationResult:
    matrix: List[List[float]]    # len(JS_FACTOR_NAMES) x len(JS_FACTOR_NAMES)
    ic: List[float]              # one per factor
    turnover: List[float]        # one per factor (%)
    factors: List[str]


def compute_correlation_matrix(
    dataset: Dict[str, PriceSeries],
    lookback_days: int,
) -> List[List[float]]:
    """Port of JS computeCorrelationMatrix.

    Pearson correlation between factor z-scores across all tickers.
    """
    tickers = list(dataset.keys())
    scores = compute_factor_scores_js(dataset, lookback_days)
    n_factors = len(JS_FACTOR_NAMES)

    matrix = []
    for i in range(n_factors):
        row = []
        for j in range(n_factors):
            if i == j:
                row.append(1.0)
                continue
            fi = JS_FACTOR_NAMES[i]
            fj = JS_FACTOR_NAMES[j]
            xi = [scores[t][fi] for t in tickers]
            xj = [scores[t][fj] for t in tickers]
            row.append(sanitize_number(correlation(xi, xj), 0.0))
        matrix.append(row)
    return matrix


def compute_ic(
    dataset: Dict[str, PriceSeries],
    lookback_days: int,
) -> List[float]:
    """Port of JS computeIC — Information Coefficient per factor.

    IC = Pearson correlation between factor z-score and forward 5-day return.
    """
    tickers = list(dataset.keys())
    scores = compute_factor_scores_js(dataset, lookback_days)

    # Forward 5-day returns
    fwd_returns = {}
    for t in tickers:
        p = dataset[t].prices
        n = len(p)
        fwd_returns[t] = safe_div(
            p[n - 1] - p[max(0, n - 6)], p[max(0, n - 6)], 0.0
        )

    ics = []
    for factor in JS_FACTOR_NAMES:
        x = [scores[t][factor] for t in tickers]
        y = [fwd_returns[t] for t in tickers]
        ics.append(sanitize_number(correlation(x, y), 0.0))
    return ics


def compute_turnover(
    dataset: Dict[str, PriceSeries],
    lookback_days: int,
    seed: int = 42,
) -> List[float]:
    """Port of JS computeFactorTurnover — simulated turnover per factor.

    JS uses seeded random to produce a stable turnover metric (15%-70%).
    """
    turnovers = []
    for factor in JS_FACTOR_NAMES:
        rng = Mulberry32(hash_string(factor) + seed)
        val = sanitize_number(0.15 + rng() * 0.55, 0.3)
        turnovers.append(val)
    return turnovers


def compute_correlation_result(
    sector: str = "Technology",
    lookback: int = 252,
    base_seed: int = 42,
) -> CorrelationResult:
    """Full correlation analysis for the API."""
    dataset = generate_dataset(sector, lookback, base_seed)
    return CorrelationResult(
        matrix=compute_correlation_matrix(dataset, lookback),
        ic=compute_ic(dataset, lookback),
        turnover=compute_turnover(dataset, lookback, base_seed),
        factors=list(JS_FACTOR_NAMES),
    )
