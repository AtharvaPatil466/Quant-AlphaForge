"""Risk-managed momentum (Barroso & Santa-Clara 2015).

Plain cross-sectional momentum has a well-documented crash problem: it
mean-reverts violently in high-vol regimes (2009, March 2020). Barroso &
Santa-Clara (2015) show that scaling the momentum signal by the inverse
of its own recent realized volatility captures most of the premium while
cutting the crash drawdowns materially.

Per-ticker formula:

    score_i = mom12_1(i) / max(sigma63(i), floor)

where mom12_1 is the JS-parity 12-1 momentum return and sigma63 is the
63-day rolling stdev of daily returns. The floor prevents division
explosions for ultra-low-vol names.
"""

from __future__ import annotations

import math

import numpy as np

from .base_factor import BaseFactor
from data.synthetic import safe_div, sanitize_number


class RiskManagedMomentumFactor(BaseFactor):
    name = "Risk-Managed Momentum"
    lookback_required = 252
    _VOL_WINDOW = 63
    _SIGMA_FLOOR = 1e-3

    def compute(self, prices: np.ndarray, volumes: np.ndarray,
                returns: np.ndarray, lookback: int) -> float:
        n = len(prices)
        if n < 252:
            return 0.0
        t = n - 1
        ret_12m = prices[t] / prices[max(0, t - 252)] - 1.0
        ret_1m = prices[t] / prices[max(0, t - 21)] - 1.0
        mom = ret_12m - ret_1m
        recent = prices[-(self._VOL_WINDOW + 1):]
        log_rets = np.diff(np.log(np.maximum(recent, 1e-10)))
        sigma = float(np.std(log_rets, ddof=1))
        sigma = max(sigma, self._SIGMA_FLOOR)
        return sanitize_number(safe_div(mom, sigma, 0.0), 0.0)

    def compute_js(self, prices: np.ndarray, volumes: np.ndarray,
                   returns: np.ndarray, lookback: int) -> float:
        return self.compute(prices, volumes, returns, lookback)
