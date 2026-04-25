"""Amihud (2002) illiquidity factor.

ILLIQ_i = mean_{t in window} |r_{i,t}| / ($volume_{i,t})

Higher ILLIQ means the stock moves more per dollar traded, i.e. less liquid.
Amihud documented a cross-sectional illiquidity premium: illiquid names earn
higher future returns as compensation.

On a 50-name mega-cap universe this premium is expected to be weak
(the universe is uniformly liquid). We include it as a credibility check
rather than as a high-prior candidate.
"""

from __future__ import annotations

import numpy as np

from .base_factor import BaseFactor
from data.synthetic import safe_div, sanitize_number


class AmihudIlliquidityFactor(BaseFactor):
    name = "Amihud Illiquidity"
    lookback_required = 21  # 20-day window + 1 for return computation

    _WINDOW = 20
    _SCALE = 1e6  # standard rescaling so values land in a readable range

    def compute(self, prices: np.ndarray, volumes: np.ndarray,
                returns: np.ndarray, lookback: int) -> float:
        n = len(prices)
        if n < self._WINDOW + 1:
            return 0.0
        p = prices[-(self._WINDOW + 1):]
        v = volumes[-self._WINDOW:]
        daily_ret = p[1:] / np.maximum(p[:-1], 1e-10) - 1.0
        dollar_vol = np.maximum(p[1:] * v, 1e-6)
        illiq = np.abs(daily_ret) / dollar_vol
        mask = np.isfinite(illiq)
        if mask.sum() < self._WINDOW // 2:
            return 0.0
        return sanitize_number(float(np.mean(illiq[mask]) * self._SCALE), 0.0)

    def compute_js(self, prices: np.ndarray, volumes: np.ndarray,
                   returns: np.ndarray, lookback: int) -> float:
        """Not in JS frontend — returns same as compute()."""
        return self.compute(prices, volumes, returns, lookback)
