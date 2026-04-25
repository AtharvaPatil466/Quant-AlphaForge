"""Earnings Drift factor."""

from __future__ import annotations

import math

import numpy as np

from .base_factor import BaseFactor
from data.synthetic import safe_div


class EarningsDriftFactor(BaseFactor):
    name = "Earnings Drift"
    lookback_required = 63

    def compute(self, prices: np.ndarray, volumes: np.ndarray,
                returns: np.ndarray, lookback: int) -> float:
        """Plan formula: (close[t]/close[t-63] - 1) / (daily_vol × sqrt(252))

        Volatility-adjusted 3-month return. Higher vol-adjusted drift
        indicates a stronger post-earnings signal.
        """
        n = len(prices)
        if n < 64:
            return 0.0
        ret_3m = prices[n - 1] / prices[n - 64] - 1
        if n < 21:
            return 0.0
        log_rets = np.diff(np.log(np.maximum(prices[-21:], 1e-10)))
        daily_vol = float(np.std(log_rets, ddof=1))
        ann_vol = daily_vol * math.sqrt(252)
        return safe_div(ret_3m, max(ann_vol, 0.01), 0.0)

    def compute_js(self, prices: np.ndarray, volumes: np.ndarray,
                   returns: np.ndarray, lookback: int) -> float:
        """JS formula: (p[n-1] - p[ed10Start]) / p[ed10Start]

        ed10Start = max(0, n - 11)
        """
        n = len(prices)
        ed10_start = max(0, n - 11)
        return safe_div(prices[n - 1] - prices[ed10_start], prices[ed10_start], 0.0)
