"""Mean-Variance Portfolio Optimizer.

Implements Markowitz mean-variance optimization using factor scores as
expected return proxies and historical returns for covariance estimation.
Solves the constrained quadratic program via scipy.

Supports:
- Long-only, long-short, and market-neutral modes
- Position-level weight bounds
- Gross leverage constraint
- Maximum number of holdings
- Optional factor exposure bounds
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy.optimize import minimize

from data.synthetic import (
    PriceSeries,
    generate_dataset,
    mean,
    safe_div,
    sanitize_number,
    stddev,
)
from backtest.synthetic_demo import BacktestConfig
from factors.scoring import compute_factor_scores_js
from backtest import metrics as bm


@dataclass
class OptimizeConfig:
    """Configuration for mean-variance optimization."""
    sector: str = "Technology"
    lookback: int = 252
    base_seed: int = 42

    # Objective
    risk_aversion: float = 1.0          # lambda: higher = more risk-averse
    target_return: Optional[float] = None  # if set, find min-vol for this return

    # Constraints
    mode: str = "long_short"            # "long_only", "long_short", "market_neutral"
    max_weight: float = 0.20            # max absolute weight per ticker
    min_weight: float = -0.20           # min weight (ignored in long_only mode)
    max_gross_leverage: float = 2.0     # sum(|w|) <= this
    max_positions: int = 0              # 0 = no limit

    # Return estimation
    shrinkage_alpha: float = 0.5        # blend factor scores with historical returns
    cov_shrinkage: float = 0.1          # Ledoit-Wolf style shrinkage toward diagonal


@dataclass
class OptimizeResult:
    """Output of the portfolio optimization."""
    weights: Dict[str, float]           # ticker -> optimal weight
    expected_return: float              # portfolio expected return (annualized)
    expected_vol: float                 # portfolio expected volatility (annualized)
    expected_sharpe: float              # expected Sharpe ratio
    n_long: int
    n_short: int
    gross_leverage: float               # sum(|w|)
    net_exposure: float                 # sum(w)
    factor_exposures: Dict[str, float]  # weighted factor z-scores
    covariance_matrix: List[List[float]]
    tickers: List[str]
    error: Optional[str] = None


def _estimate_expected_returns(
    dataset: Dict[str, PriceSeries],
    factor_scores: Dict[str, Dict[str, float]],
    tickers: List[str],
    shrinkage: float = 0.5,
) -> np.ndarray:
    """Estimate expected returns by blending historical returns with factor scores.

    Expected return = shrinkage * (normalized composite score) +
                      (1 - shrinkage) * (annualized historical mean return)
    """
    n = len(tickers)
    mu = np.zeros(n)

    for i, ticker in enumerate(tickers):
        # Historical mean daily return → annualized
        rets = dataset[ticker].returns[1:]  # skip first (=0)
        hist_mean = float(np.mean(rets)) * 252 if len(rets) > 0 else 0.0

        # Factor composite score (already in [-100, 100]), scale to return-like range
        composite = factor_scores.get(ticker, {}).get("_composite", 0.0)
        factor_return = composite / 100.0 * 0.30  # scale: 100 → 30% ann. return

        mu[i] = shrinkage * factor_return + (1 - shrinkage) * hist_mean

    return mu


def _estimate_covariance(
    dataset: Dict[str, PriceSeries],
    tickers: List[str],
    shrinkage: float = 0.1,
) -> np.ndarray:
    """Estimate covariance matrix with Ledoit-Wolf style shrinkage.

    Sigma_shrunk = (1 - alpha) * Sigma_sample + alpha * diag(variances)
    """
    n = len(tickers)

    # Build return matrix: (T, n)
    min_len = min(len(dataset[t].returns) for t in tickers)
    returns = np.zeros((min_len - 1, n))
    for i, ticker in enumerate(tickers):
        returns[:, i] = dataset[ticker].returns[1:min_len]

    # Sample covariance
    if returns.shape[0] < 2:
        return np.eye(n) * 0.04 / 252  # fallback: 20% vol

    cov_sample = np.cov(returns, rowvar=False)

    # Shrinkage target: diagonal (uncorrelated)
    diag = np.diag(np.diag(cov_sample))

    cov_shrunk = (1 - shrinkage) * cov_sample + shrinkage * diag

    # Ensure positive semi-definite
    eigenvalues = np.linalg.eigvalsh(cov_shrunk)
    if np.any(eigenvalues < -1e-10):
        cov_shrunk += np.eye(n) * (abs(eigenvalues.min()) + 1e-8)

    return cov_shrunk


def _optimize_weights(
    mu: np.ndarray,
    cov: np.ndarray,
    config: OptimizeConfig,
) -> np.ndarray:
    """Solve the mean-variance optimization problem.

    Maximize: w'mu - (lambda/2) * w'Cov*w
    Subject to: weight bounds, leverage constraint, mode constraints
    """
    n = len(mu)

    # Weight bounds
    if config.mode == "long_only":
        bounds = [(0.0, config.max_weight)] * n
    else:
        bounds = [(config.min_weight, config.max_weight)] * n

    # Initial guess: equal weight
    if config.mode == "long_only":
        w0 = np.ones(n) / n * 0.5
    else:
        w0 = np.zeros(n)

    lam = config.risk_aversion

    def objective(w):
        port_return = w @ mu
        port_var = w @ cov @ w
        # Minimize negative utility
        return -(port_return - (lam / 2) * port_var)

    def objective_jac(w):
        return -(mu - lam * cov @ w)

    constraints = []

    # Gross leverage constraint: sum(|w|) <= max_gross_leverage
    constraints.append({
        "type": "ineq",
        "fun": lambda w: config.max_gross_leverage - np.sum(np.abs(w)),
    })

    # Market neutral: sum(w) = 0
    if config.mode == "market_neutral":
        constraints.append({
            "type": "eq",
            "fun": lambda w: np.sum(w),
        })

    # Target return constraint
    if config.target_return is not None:
        daily_target = config.target_return / 252
        constraints.append({
            "type": "eq",
            "fun": lambda w: w @ mu - daily_target,
        })

    result = minimize(
        objective,
        w0,
        jac=objective_jac,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"maxiter": 500, "ftol": 1e-12},
    )

    weights = result.x

    # Clean up near-zero weights
    weights[np.abs(weights) < 1e-4] = 0.0

    # Enforce max_positions if set
    if config.max_positions > 0 and np.sum(weights != 0) > config.max_positions:
        abs_w = np.abs(weights)
        # Keep only the top max_positions by absolute weight
        sorted_indices = np.argsort(abs_w)[::-1]
        keep = set(sorted_indices[:config.max_positions].tolist())
        for i in range(len(weights)):
            if i not in keep:
                weights[i] = 0.0

    return weights


def optimize_portfolio(config: OptimizeConfig) -> OptimizeResult:
    """Run the full mean-variance optimization pipeline.

    1. Generate synthetic data
    2. Compute factor scores (z-scored)
    3. Estimate expected returns (factor + historical blend)
    4. Estimate covariance matrix (with shrinkage)
    5. Solve QP for optimal weights
    6. Compute portfolio statistics
    """
    dataset = generate_dataset(config.sector, config.lookback, config.base_seed)
    tickers = list(dataset.keys())

    if not tickers:
        return OptimizeResult(
            weights={}, expected_return=0, expected_vol=0, expected_sharpe=0,
            n_long=0, n_short=0, gross_leverage=0, net_exposure=0,
            factor_exposures={}, covariance_matrix=[], tickers=[],
            error="No tickers in selected universe.",
        )

    # Factor scores
    scores = compute_factor_scores_js(dataset, config.lookback)

    # Expected returns
    mu = _estimate_expected_returns(
        dataset, scores, tickers, shrinkage=config.shrinkage_alpha
    )

    # Covariance matrix
    cov = _estimate_covariance(
        dataset, tickers, shrinkage=config.cov_shrinkage
    )

    # Optimize
    weights_arr = _optimize_weights(mu, cov, config)

    # Build result
    weights = {t: round(float(w), 6) for t, w in zip(tickers, weights_arr) if abs(w) > 1e-6}
    w_vec = weights_arr

    # Portfolio expected return and vol (annualized)
    port_return_daily = float(w_vec @ mu)
    port_var_daily = float(w_vec @ cov @ w_vec)
    port_vol_daily = math.sqrt(max(0, port_var_daily))

    exp_return = port_return_daily * 252
    exp_vol = port_vol_daily * math.sqrt(252)
    exp_sharpe = safe_div(exp_return, exp_vol, 0.0)

    n_long = int(np.sum(w_vec > 1e-6))
    n_short = int(np.sum(w_vec < -1e-6))
    gross = float(np.sum(np.abs(w_vec)))
    net = float(np.sum(w_vec))

    # Factor exposures: weighted average of z-scored factor values
    from factors.registry import JS_FACTOR_NAMES
    factor_exp = {}
    for fname in JS_FACTOR_NAMES:
        exposure = sum(
            weights.get(t, 0) * scores.get(t, {}).get(fname, 0)
            for t in tickers
        )
        factor_exp[fname] = round(sanitize_number(exposure, 0.0), 4)

    return OptimizeResult(
        weights=weights,
        expected_return=round(sanitize_number(exp_return, 0.0), 6),
        expected_vol=round(sanitize_number(exp_vol, 0.0), 6),
        expected_sharpe=round(sanitize_number(exp_sharpe, 0.0), 4),
        n_long=n_long,
        n_short=n_short,
        gross_leverage=round(gross, 4),
        net_exposure=round(net, 4),
        factor_exposures=factor_exp,
        covariance_matrix=cov.tolist(),
        tickers=tickers,
    )
