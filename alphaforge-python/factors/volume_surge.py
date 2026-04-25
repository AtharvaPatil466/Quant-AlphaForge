"""Volume Surge factor."""

from __future__ import annotations

import numpy as np

from .base_factor import BaseFactor
from data.synthetic import safe_div, mean


class VolumeSurgeFactor(BaseFactor):
    name = "Volume Surge"
    lookback_required = 20

    def compute(self, prices: np.ndarray, volumes: np.ndarray,
                returns: np.ndarray, lookback: int) -> float:
        """Plan formula: (vol[t] / mean(vol[t-20:t])) × (close[t]/close[t-1] - 1)

        Volume-confirmed directional signal: high volume + positive return = strong buy.
        """
        n = len(prices)
        if n < 21 or len(volumes) < 21:
            return 0.0
        avg_vol = float(np.mean(volumes[-20:]))
        vol_ratio = volumes[-1] / max(avg_vol, 1e-10)
        ret_1d = prices[-1] / prices[-2] - 1
        return float(vol_ratio * ret_1d)

    def compute_js(self, prices: np.ndarray, volumes: np.ndarray,
                   returns: np.ndarray, lookback: int) -> float:
        """JS formula: (vol5 - vol20) / vol20

        vol5  = mean(v.slice(-5))
        vol20 = mean(v.slice(-20))
        """
        vol5 = mean(volumes[-5:])
        vol20 = mean(volumes[-20:])
        return safe_div(vol5 - vol20, vol20, 0.0)
