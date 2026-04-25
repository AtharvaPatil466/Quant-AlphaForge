"""Long-horizon reversal (De Bondt & Thaler 1985).

Academic documentation of the "loser" effect: stocks with the worst
cumulative returns over a long look-back window (3-5 years) tend to
outperform the prior winners over the following 12-36 months. This is
the OHLCV-only proxy for value in the absence of fundamentals data.

Formula:

    score_i = -(price_{t-21} / price_{t - 21 - W}) + 1

skipping the most recent month (21 trading days) to avoid overlap with
short-horizon reversal and momentum-crash dynamics. Default W = 48 × 21
trading days (~4 years). The sign is negated: worst performers over the
window get the highest score.
"""

from __future__ import annotations

import numpy as np

from .base_factor import BaseFactor
from data.synthetic import safe_div, sanitize_number


class LongHorizonReversalFactor(BaseFactor):
    name = "Long-Horizon Reversal"
    _SKIP_DAYS = 21           # skip most recent month
    _WINDOW_DAYS = 48 * 21    # 48 months
    lookback_required = _SKIP_DAYS + _WINDOW_DAYS

    def compute(self, prices: np.ndarray, volumes: np.ndarray,
                returns: np.ndarray, lookback: int) -> float:
        n = len(prices)
        if n < self.lookback_required:
            return 0.0
        t = n - 1
        anchor_idx = t - self._SKIP_DAYS
        start_idx = anchor_idx - self._WINDOW_DAYS
        if start_idx < 0:
            return 0.0
        past_ret = safe_div(prices[anchor_idx] - prices[start_idx],
                            prices[start_idx], 0.0)
        return sanitize_number(-past_ret, 0.0)

    def compute_js(self, prices: np.ndarray, volumes: np.ndarray,
                   returns: np.ndarray, lookback: int) -> float:
        return self.compute(prices, volumes, returns, lookback)
