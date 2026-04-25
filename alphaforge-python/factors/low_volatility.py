"""Low Volatility factor."""

from __future__ import annotations

import math

import numpy as np

from .base_factor import BaseFactor


class LowVolatilityFactor(BaseFactor):
    name = "Low Volatility"
    lookback_required = 60

    def compute(self, prices: np.ndarray, volumes: np.ndarray,
                returns: np.ndarray, lookback: int) -> float:
        """Plan formula: -sqrt(var(returns[t-59:t]) × 252)

        Negative annualized vol: lower vol = higher score.
        """
        n = len(prices)
        if n < 61:
            return 0.0
        log_rets = np.log(prices[-60:] / prices[-61:-1])
        daily_std = float(np.std(log_rets, ddof=1))
        return -daily_std * math.sqrt(252)

    def compute_js(self, prices: np.ndarray, volumes: np.ndarray,
                   returns: np.ndarray, lookback: int) -> float:
        """Not in JS frontend — returns same as compute()."""
        return self.compute(prices, volumes, returns, lookback)
