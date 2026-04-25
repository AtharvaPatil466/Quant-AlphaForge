"""Cross-sectional factor scoring — the JS-parity z-score pipeline.

Extracted from `backtest.engine` so factor scoring is reusable without
pulling in the backtest engine module. Behavior is bit-identical to the
prior `_compute_factor_scores_js` location.
"""

from __future__ import annotations

from typing import Dict

import numpy as np

from data.synthetic import (
    PriceSeries,
    clamp,
    mean,
    safe_div,
    sanitize_number,
    stddev,
)
from factors.registry import JS_FACTOR_NAMES, load_factor


def compute_factor_scores_js(
    dataset: Dict[str, PriceSeries], lookback: int
) -> Dict[str, Dict[str, float]]:
    """Compute z-scored factor values using the JS-parity path.

    Returns ticker -> {factor_name: z_score, '_composite': float, '_signal': str}.
    """
    tickers = list(dataset.keys())
    if not tickers:
        return {}

    raw_scores: Dict[str, Dict[str, float]] = {}
    for ticker in tickers:
        d = dataset[ticker]
        raw_scores[ticker] = {}
        for fname in JS_FACTOR_NAMES:
            factor = load_factor(fname)
            raw_scores[ticker][fname] = factor.compute_js(
                d.prices, d.volumes, d.returns, lookback
            )

    z_scored: Dict[str, Dict[str, float]] = {t: {} for t in tickers}
    for fname in JS_FACTOR_NAMES:
        raw_vals = np.array([raw_scores[t][fname] for t in tickers])
        mu = mean(raw_vals)
        sigma = max(1e-8, stddev(raw_vals))
        for ticker in tickers:
            z = safe_div(raw_scores[ticker][fname] - mu, sigma, 0.0)
            z_scored[ticker][fname] = sanitize_number(z, 0.0)

    for ticker in tickers:
        fv = [z_scored[ticker][f] for f in JS_FACTOR_NAMES]
        composite = mean(fv) * 40
        z_scored[ticker]["_composite"] = clamp(sanitize_number(composite, 0.0), -100, 100)
        if composite > 40:
            z_scored[ticker]["_signal"] = "LONG"
        elif composite < -40:
            z_scored[ticker]["_signal"] = "SHORT"
        else:
            z_scored[ticker]["_signal"] = "NEUTRAL"

    return z_scored
