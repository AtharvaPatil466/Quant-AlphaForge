"""Mean Reversion (5-day) factor."""

from __future__ import annotations

import numpy as np

from .base_factor import BaseFactor
from data.synthetic import safe_div


class MeanReversionFactor(BaseFactor):
    name = "Mean Reversion (5d)"
    lookback_required = 5

    def compute(self, prices: np.ndarray, volumes: np.ndarray,
                returns: np.ndarray, lookback: int) -> float:
        """Plan formula: -(close[t] / close[t-5] - 1)"""
        n = len(prices)
        if n < 6:
            return 0.0
        return -(prices[n - 1] / prices[n - 6] - 1)

    def compute_js(self, prices: np.ndarray, volumes: np.ndarray,
                   returns: np.ndarray, lookback: int) -> float:
        """JS formula: -(p[n-1] - p[mr5Start]) / p[mr5Start]

        mr5Start = max(0, n - 6)
        """
        n = len(prices)
        mr5_start = max(0, n - 6)
        return -safe_div(prices[n - 1] - prices[mr5_start], prices[mr5_start], 0.0)
