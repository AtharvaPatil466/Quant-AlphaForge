"""Idiosyncratic volatility factor (Ang, Hodrick, Xing & Zhang 2006).

For each ticker, regress daily log returns on an equal-weighted market
return over a rolling window; IVOL is the annualized standard deviation of
the residuals. The "idiosyncratic vol puzzle" is that high-IVOL stocks
empirically *underperform* — so we negate the raw IVOL to yield a signal
where higher score = low IVOL = expected higher return.

The factor needs cross-sectional market context, so we override
`compute_universe` to compute the market return from the given universe
once and reuse it per ticker. Single-ticker `compute()` falls back to
a total-volatility proxy when no market series is supplied.
"""

from __future__ import annotations

import math
from typing import Dict

import numpy as np

from .base_factor import BaseFactor
from data.synthetic import PriceSeries, safe_div, sanitize_number


class IdiosyncraticVolatilityFactor(BaseFactor):
    name = "Idiosyncratic Volatility"
    lookback_required = 60
    _WINDOW = 60

    def _regress_residual_std(self, r: np.ndarray, m: np.ndarray) -> float:
        """OLS r = a + b*m + e, return std(e, ddof=2).

        Uses closed-form coefficients. Falls back to std(r) if market
        variance is degenerate.
        """
        n = len(r)
        if n < 10:
            return 0.0
        m_bar = float(m.mean())
        r_bar = float(r.mean())
        cov = float(((m - m_bar) * (r - r_bar)).sum())
        var_m = float(((m - m_bar) ** 2).sum())
        if var_m <= 1e-12:
            return float(r.std(ddof=1))
        beta = cov / var_m
        alpha = r_bar - beta * m_bar
        resid = r - (alpha + beta * m)
        dof = max(n - 2, 1)
        return float(math.sqrt((resid ** 2).sum() / dof))

    def compute(self, prices: np.ndarray, volumes: np.ndarray,
                returns: np.ndarray, lookback: int) -> float:
        """Fallback: total vol (no market available). Negated to align
        with the compute_universe sign convention (higher = better).
        """
        n = len(prices)
        if n < self._WINDOW + 1:
            return 0.0
        log_rets = np.log(np.maximum(prices[-(self._WINDOW + 1):], 1e-10))
        daily = np.diff(log_rets)
        if len(daily) < 10 or not np.all(np.isfinite(daily)):
            return 0.0
        vol = float(daily.std(ddof=1)) * math.sqrt(252)
        return sanitize_number(-vol, 0.0)

    def compute_js(self, prices: np.ndarray, volumes: np.ndarray,
                   returns: np.ndarray, lookback: int) -> float:
        return self.compute(prices, volumes, returns, lookback)

    def compute_universe(
        self, dataset: Dict[str, PriceSeries], lookback: int, use_js: bool = True
    ) -> Dict[str, float]:
        """Cross-sectional path: construct equal-weight market log return
        from the dataset, regress each ticker on it, and report −IVOL.
        """
        tickers = list(dataset.keys())
        if not tickers:
            return {}

        # Build aligned log-return matrix. Every series is the same length.
        first = dataset[tickers[0]].prices
        T = len(first)
        if T < self._WINDOW + 1:
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
        window_m = market[-self._WINDOW:]

        scores: Dict[str, float] = {}
        for i, t in enumerate(tickers):
            if not ok[i]:
                scores[t] = 0.0
                continue
            r = log_rets[i][-self._WINDOW:]
            ivol_daily = self._regress_residual_std(r, window_m)
            ivol_ann = ivol_daily * math.sqrt(252)
            scores[t] = sanitize_number(-ivol_ann, 0.0)
        return scores
