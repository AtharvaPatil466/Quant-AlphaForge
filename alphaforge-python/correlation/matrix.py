"""Pairwise Pearson correlation between factor z-score series."""

from __future__ import annotations

from typing import Dict, List

from data.synthetic import PriceSeries, sanitize_number, correlation
from factors.scoring import compute_factor_scores_js
from factors.registry import JS_FACTOR_NAMES


def compute_correlation_matrix(
    dataset: Dict[str, PriceSeries],
    lookback_days: int,
) -> List[List[float]]:
    """Port of JS computeCorrelationMatrix.

    Pearson correlation between factor z-scores across tickers.
    Returns (n_factors × n_factors) matrix.
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
