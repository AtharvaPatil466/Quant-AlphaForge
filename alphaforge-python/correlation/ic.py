"""Information Coefficient — Spearman rank correlation between factor scores and forward returns."""

from __future__ import annotations

from typing import Dict, List

import numpy as np

try:
    from scipy.stats import spearmanr
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

from data.synthetic import PriceSeries, safe_div, sanitize_number, correlation
from backtest.engine import _compute_factor_scores_js
from factors.registry import JS_FACTOR_NAMES


def _spearman_correlation(x: list, y: list) -> float:
    """Spearman rank correlation. Falls back to Pearson if scipy unavailable."""
    if len(x) < 3:
        return 0.0
    if HAS_SCIPY:
        rho, _ = spearmanr(x, y)
        return float(rho) if np.isfinite(rho) else 0.0
    # Fallback: Pearson on ranks
    rx = np.argsort(np.argsort(x)).astype(float)
    ry = np.argsort(np.argsort(y)).astype(float)
    return correlation(rx.tolist(), ry.tolist())


def compute_ic(
    dataset: Dict[str, PriceSeries],
    lookback_days: int,
    forward_days: int = 21,
    use_spearman: bool = True,
) -> List[float]:
    """Information Coefficient per factor.

    Default: Spearman rank IC (plan spec). Set use_spearman=False for Pearson (JS parity).
    IC = correlation(factor_score, forward_return) across tickers.
    """
    tickers = list(dataset.keys())
    scores = _compute_factor_scores_js(dataset, lookback_days)

    # Forward returns: use 5-day (JS) or configurable
    fwd_returns = {}
    for t in tickers:
        p = dataset[t].prices
        n = len(p)
        end_offset = min(forward_days + 1, n)
        fwd_returns[t] = safe_div(
            p[n - 1] - p[max(0, n - end_offset)],
            p[max(0, n - end_offset)],
            0.0,
        )

    ics = []
    corr_fn = _spearman_correlation if use_spearman else (
        lambda x, y: sanitize_number(correlation(x, y), 0.0)
    )

    for factor in JS_FACTOR_NAMES:
        x = [scores[t][factor] for t in tickers]
        y = [fwd_returns[t] for t in tickers]
        ics.append(sanitize_number(corr_fn(x, y), 0.0))

    return ics


def compute_ic_js(
    dataset: Dict[str, PriceSeries],
    lookback_days: int,
) -> List[float]:
    """JS-compatible IC: Pearson with 5-day forward returns."""
    return compute_ic(dataset, lookback_days, forward_days=5, use_spearman=False)
