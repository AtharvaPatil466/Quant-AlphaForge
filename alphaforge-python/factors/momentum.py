"""Momentum (12-1 month) factor."""

from __future__ import annotations

import numpy as np

from .base_factor import BaseFactor
from data.synthetic import safe_div


class MomentumFactor(BaseFactor):
    name = "Momentum (12-1)"
    lookback_required = 252

    def compute(self, prices: np.ndarray, volumes: np.ndarray,
                returns: np.ndarray, lookback: int) -> float:
        """Plan formula: ret_12m - ret_1m.

        (close[t]/close[t-252] - 1) - (close[t]/close[t-21] - 1)
        """
        n = len(prices)
        if n < 252:
            return 0.0
        t = n - 1
        ret_12m = prices[t] / prices[max(0, t - 252)] - 1
        ret_1m = prices[t] / prices[max(0, t - 21)] - 1
        return ret_12m - ret_1m

    def compute_js(self, prices: np.ndarray, volumes: np.ndarray,
                   returns: np.ndarray, lookback: int) -> float:
        """JS formula: (p[momEnd] - p[momStart]) / p[momStart]

        momStart = max(0, n - min(252, lookback))
        momEnd   = max(momStart+1, n - 21)
        """
        n = len(prices)
        mom_start = max(0, n - min(252, lookback))
        mom_end = max(mom_start + 1, n - 21)
        return safe_div(prices[mom_end] - prices[mom_start], prices[mom_start], 0.0)
