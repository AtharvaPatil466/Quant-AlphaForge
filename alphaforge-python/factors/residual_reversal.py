"""Residual reversal factor (Da, Liu & Schaumburg 2014).

Short-horizon cross-sectional reversal is a well-known return anomaly, but
raw 5-day reversal is contaminated by systematic (market-beta) moves. The
residual version first strips out the market component via a rolling
regression, then reverses the residual over the last 5 days.

    r_{i,t} = a_i + b_i * r_{m,t} + e_{i,t}      (60-day regression)
    score_i = -sum_{t in last 5 days}(e_{i,t})

Higher score means the residual has been negative recently → expect reversion up.

Like IVOL this needs a market return series, so `compute_universe` is
overridden. Single-ticker `compute()` falls back to raw 5-day reversal.
"""

from __future__ import annotations

from typing import Dict

import numpy as np

from .base_factor import BaseFactor
from data.synthetic import PriceSeries, safe_div, sanitize_number


class ResidualReversalFactor(BaseFactor):
    name = "Residual Reversal (5d)"
    lookback_required = 60
    _REG_WINDOW = 60
    _REV_WINDOW = 5

    def compute(self, prices: np.ndarray, volumes: np.ndarray,
                returns: np.ndarray, lookback: int) -> float:
        """Fallback with no market: raw 5-day reversal."""
        n = len(prices)
        if n < self._REV_WINDOW + 1:
            return 0.0
        return -safe_div(prices[-1] - prices[-1 - self._REV_WINDOW],
                         prices[-1 - self._REV_WINDOW], 0.0)

    def compute_js(self, prices: np.ndarray, volumes: np.ndarray,
                   returns: np.ndarray, lookback: int) -> float:
        return self.compute(prices, volumes, returns, lookback)

    def _fit_beta(self, r: np.ndarray, m: np.ndarray) -> tuple[float, float]:
        n = len(r)
        if n < 10:
            return 0.0, 0.0
        m_bar = float(m.mean()); r_bar = float(r.mean())
        var_m = float(((m - m_bar) ** 2).sum())
        if var_m <= 1e-12:
            return r_bar, 0.0
        beta = float(((m - m_bar) * (r - r_bar)).sum()) / var_m
        alpha = r_bar - beta * m_bar
        return alpha, beta

    def compute_universe(
        self, dataset: Dict[str, PriceSeries], lookback: int, use_js: bool = True
    ) -> Dict[str, float]:
        tickers = list(dataset.keys())
        if not tickers:
            return {}

        first = dataset[tickers[0]].prices
        T = len(first)
        if T < self._REG_WINDOW + 1:
            return {t: 0.0 for t in tickers}

        log_rets = np.zeros((len(tickers), T - 1))
        ok = np.ones(len(tickers), dtype=bool)
        for i, t in enumerate(tickers):
            p = dataset[t].prices
            if len(p) != T or not np.all(np.isfinite(p)) or np.any(p <= 0):
                ok[i] = False
                continue
            log_rets[i] = np.diff(np.log(p))

        if ok.sum() < 2:
            return {t: 0.0 for t in tickers}

        market = log_rets[ok].mean(axis=0)
        reg_m = market[-self._REG_WINDOW:]

        scores: Dict[str, float] = {}
        for i, t in enumerate(tickers):
            if not ok[i]:
                scores[t] = 0.0
                continue
            r = log_rets[i]
            reg_r = r[-self._REG_WINDOW:]
            alpha, beta = self._fit_beta(reg_r, reg_m)
            # Residual over the last REV_WINDOW days
            recent_r = r[-self._REV_WINDOW:]
            recent_m = market[-self._REV_WINDOW:]
            resid = recent_r - (alpha + beta * recent_m)
            scores[t] = sanitize_number(-float(resid.sum()), 0.0)
        return scores
