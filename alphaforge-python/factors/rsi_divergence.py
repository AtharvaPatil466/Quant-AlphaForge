"""RSI Divergence factor."""

from __future__ import annotations

import numpy as np

from .base_factor import BaseFactor
from data.synthetic import safe_div, sanitize_number


def _compute_rsi_js(prices) -> float:
    """Port of JS computeRSI — matches JS behavior exactly.

    When avgLoss == 0, JS safeDiv(avgGain, 0, 1) returns fallback=1,
    giving RS=1 and RSI=50.
    """
    if len(prices) < 2:
        return 50.0
    gains = 0.0
    losses = 0.0
    for i in range(1, len(prices)):
        change = prices[i] - prices[i - 1]
        if change > 0:
            gains += change
        else:
            losses -= change
    periods = len(prices) - 1
    avg_gain = safe_div(gains, periods, 0.0)
    avg_loss = safe_div(losses, periods, 0.0)
    rs = safe_div(avg_gain, avg_loss, 1.0)
    return sanitize_number(100.0 - safe_div(100.0, 1.0 + rs, 50.0), 50.0)


class RSIDivergenceFactor(BaseFactor):
    name = "RSI Divergence"
    lookback_required = 14

    def compute(self, prices: np.ndarray, volumes: np.ndarray,
                returns: np.ndarray, lookback: int) -> float:
        """Plan formula: conditional based on RSI thresholds.

        if RSI < 30: (30-RSI)/30  (oversold → expect reversion up)
        if RSI > 70: (70-RSI)/30  (overbought → expect reversion down)
        else: 0
        """
        if len(prices) < 15:
            return 0.0
        rsi_val = _compute_rsi_js(prices[-15:])
        if rsi_val < 30:
            return (30 - rsi_val) / 30
        if rsi_val > 70:
            return (70 - rsi_val) / 30
        return 0.0

    def compute_js(self, prices: np.ndarray, volumes: np.ndarray,
                   returns: np.ndarray, lookback: int) -> float:
        """JS formula: (rsi - 50) / 50

        rsi = computeRSI(p.slice(-15))
        """
        rsi_val = _compute_rsi_js(prices[-15:])
        return (rsi_val - 50.0) / 50.0
