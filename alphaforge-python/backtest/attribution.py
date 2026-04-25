"""
Factor return attribution — OLS decomposition of portfolio returns onto factors.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

import numpy as np

from data.synthetic import PriceSeries, safe_div


@dataclass
class AttributionResult:
    """Result of factor return attribution."""
    factor_exposures: Dict[str, float]   # beta to each factor
    factor_returns: Dict[str, float]     # return attributable to each factor
    residual_return: float               # alpha (unexplained return)
    r_squared: float                     # % of variance explained


def attribute_returns(
    portfolio_returns: np.ndarray,
    factor_return_series: Dict[str, np.ndarray],
) -> AttributionResult:
    """OLS regression of portfolio returns onto factor return series.

    portfolio_returns: (T,) array of daily portfolio returns
    factor_return_series: dict of factor_name -> (T,) array of factor returns

    Returns AttributionResult with exposures, attributions, and R².
    """
    T = len(portfolio_returns)
    factor_names = list(factor_return_series.keys())
    n_factors = len(factor_names)

    if T < n_factors + 2 or n_factors == 0:
        return AttributionResult(
            factor_exposures={f: 0.0 for f in factor_names},
            factor_returns={f: 0.0 for f in factor_names},
            residual_return=float(np.mean(portfolio_returns)) if T > 0 else 0.0,
            r_squared=0.0,
        )

    # Build factor matrix X (T × n_factors+1 for intercept)
    X = np.ones((T, n_factors + 1), dtype=np.float64)
    for j, fname in enumerate(factor_names):
        fret = factor_return_series[fname]
        X[:, j + 1] = fret[:T]

    y = portfolio_returns[:T].astype(np.float64)

    # OLS: beta = (X'X)^{-1} X'y
    try:
        XtX = X.T @ X
        Xty = X.T @ y
        beta = np.linalg.solve(XtX, Xty)
    except np.linalg.LinAlgError:
        return AttributionResult(
            factor_exposures={f: 0.0 for f in factor_names},
            factor_returns={f: 0.0 for f in factor_names},
            residual_return=float(np.mean(y)),
            r_squared=0.0,
        )

    # Factor exposures (betas) and attributions
    alpha = float(beta[0])
    exposures = {}
    factor_rets = {}
    for j, fname in enumerate(factor_names):
        b = float(beta[j + 1])
        exposures[fname] = b
        factor_rets[fname] = b * float(np.mean(factor_return_series[fname][:T]))

    # R²
    y_hat = X @ beta
    ss_res = float(np.sum((y - y_hat) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r_sq = 1.0 - safe_div(ss_res, ss_tot, 1.0) if ss_tot > 1e-12 else 0.0

    return AttributionResult(
        factor_exposures=exposures,
        factor_returns=factor_rets,
        residual_return=alpha,
        r_squared=max(0.0, min(1.0, r_sq)),
    )
