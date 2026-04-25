"""
Abstract factor interface.

Every factor implements this interface so the backtest engine, scanner,
and MARL system can consume them uniformly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict

import numpy as np

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

from data.synthetic import PriceSeries, safe_div, sanitize_number, mean, stddev


class BaseFactor(ABC):
    """Abstract base for all alpha factors.

    Subclasses must implement:
        name             — human-readable factor name
        lookback_required — minimum days of history needed
        compute()        — single-ticker score (plan formula)
        compute_js()     — single-ticker score (JS-parity formula)
    """

    name: str = ""
    lookback_required: int = 0

    @abstractmethod
    def compute(self, prices: np.ndarray, volumes: np.ndarray,
                returns: np.ndarray, lookback: int) -> float:
        """Compute raw factor score using the plan's enhanced formula."""
        ...

    @abstractmethod
    def compute_js(self, prices: np.ndarray, volumes: np.ndarray,
                   returns: np.ndarray, lookback: int) -> float:
        """Compute raw factor score matching JS frontend output exactly."""
        ...

    def compute_universe(
        self, dataset: Dict[str, PriceSeries], lookback: int, use_js: bool = True
    ) -> Dict[str, float]:
        """Compute raw scores across all tickers in a dataset."""
        scores = {}
        fn = self.compute_js if use_js else self.compute
        for ticker, d in dataset.items():
            scores[ticker] = fn(d.prices, d.volumes, d.returns, lookback)
        return scores

    def score_universe(
        self, dataset: Dict[str, PriceSeries], lookback: int, use_js: bool = True
    ) -> Dict[str, float]:
        """Cross-sectional z-scores matching JS zScore() output."""
        raw = self.compute_universe(dataset, lookback, use_js=use_js)
        tickers = list(raw.keys())
        if not tickers:
            return {}
        values = [raw[t] for t in tickers]
        mu = mean(values)
        sigma = max(1e-8, stddev(values))
        return {
            t: sanitize_number(safe_div(raw[t] - mu, sigma, 0.0), 0.0)
            for t in tickers
        }
