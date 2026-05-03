"""Portfolio-level FF5+UMD alpha computation.

The standard academic test for "is factor X alpha relative to FF5+UMD?"
is a *time-series regression* of the portfolio's daily return series on
the FF5+UMD daily factor series:

    R_p,t = α + β_MKT·MKT_t + β_SMB·SMB_t + β_HML·HML_t
            + β_RMW·RMW_t + β_CMA·CMA_t + β_UMD·UMD_t + ε_t

Statistics of interest:
- α (intercept): the daily abnormal return. Annualized for reporting.
- α-t-statistic: Newey-West-adjusted; here we use a classical OLS t-stat
  with HC0 (White) standard errors as a defensible default.
- Residual Sharpe: Sharpe ratio of α + ε (the "FF5-residual return"
  series), with a stationary-bootstrap 95% CI on the Sharpe.

This is the correct residualization layer for the Phase 4 gauntlet —
NOT residualizing per-ticker daily returns and forming portfolios on
top, which double-removes factor exposure and yields nonsense extreme
negative Sharpes (the bug Phase 4 session 2a is fixing).

Public surface:
    compute_portfolio_alpha(portfolio_returns, reference_factors,
                            bootstrap_reps=2000, bootstrap_block=21)
        -> dict with all the statistics above.
"""

from __future__ import annotations

from typing import Dict, Iterable

import numpy as np
import pandas as pd

from research.risk_model import fit_factor_model


_TRADING_DAYS_PER_YEAR = 252.0


def _stationary_bootstrap_indices(
    n: int, reps: int, mean_block: int, seed: int
) -> np.ndarray:
    """Politis & Romano (1994) stationary bootstrap with mean block length."""
    rng = np.random.default_rng(seed)
    p = 1.0 / max(1, mean_block)
    starts = rng.integers(0, n, size=(reps, n))
    keep = rng.random((reps, n)) < p
    idx = starts.copy()
    for r in range(reps):
        cur = idx[r, 0]
        for t in range(1, n):
            if keep[r, t]:
                cur = idx[r, t]
            else:
                cur = (cur + 1) % n
                idx[r, t] = cur
    return idx


def _ann_sharpe(r: np.ndarray) -> float:
    if r.size < 2:
        return 0.0
    mu = float(np.mean(r))
    sd = float(np.std(r, ddof=0))
    if sd <= 1e-12:
        return 0.0
    return mu / sd * np.sqrt(_TRADING_DAYS_PER_YEAR)


def _bootstrap_sharpe_ci(
    series: np.ndarray, reps: int, mean_block: int, seed: int
) -> Dict[str, float]:
    """Stationary-bootstrap distribution of annualized Sharpe."""
    if series.size < 2:
        return {"mean": 0.0, "ci_lo": 0.0, "ci_hi": 0.0, "p_positive": 0.0}
    idx = _stationary_bootstrap_indices(series.size, reps, mean_block, seed)
    boot_returns = series[idx]  # (reps, n)
    mu = boot_returns.mean(axis=1)
    sd = boot_returns.std(axis=1, ddof=0)
    sd = np.where(sd <= 1e-12, np.nan, sd)
    sr = mu / sd * np.sqrt(_TRADING_DAYS_PER_YEAR)
    sr = sr[np.isfinite(sr)]
    if sr.size == 0:
        return {"mean": 0.0, "ci_lo": 0.0, "ci_hi": 0.0, "p_positive": 0.0}
    return {
        "mean": float(np.mean(sr)),
        "ci_lo": float(np.quantile(sr, 0.025)),
        "ci_hi": float(np.quantile(sr, 0.975)),
        "p_positive": float(np.mean(sr > 0)),
    }


def compute_portfolio_alpha(
    portfolio_returns: pd.Series,
    reference_factors: pd.DataFrame,
    *,
    bootstrap_reps: int = 2000,
    bootstrap_block: int = 21,
    bootstrap_seed: int = 0,
) -> Dict[str, object]:
    """Time-series FF5+UMD alpha test on a single portfolio's daily returns.

    Returns a dict with:
      alpha_daily, alpha_annual, alpha_t (HC0), alpha_p_two_sided
      betas (dict), r_squared, n_obs
      residual_sharpe (= Sharpe of α + ε), residual_sharpe_ci, residual_p_positive

    The "residual" series is the portfolio's return after stripping the
    fitted FF5+UMD-explained component, but KEEPING the alpha intercept
    — i.e., it's the abnormal-return series whose mean is α. This is
    the series whose Sharpe is the FF5-residual headline.
    """
    fit = fit_factor_model(portfolio_returns, reference_factors)

    if fit.n_obs < len(reference_factors.columns) + 2:
        return {
            "alpha_daily": 0.0,
            "alpha_annual": 0.0,
            "alpha_t": 0.0,
            "alpha_p_two_sided": 1.0,
            "betas": fit.betas,
            "r_squared": 0.0,
            "n_obs": int(fit.n_obs),
            "residual_sharpe": 0.0,
            "residual_sharpe_ci_lo": 0.0,
            "residual_sharpe_ci_hi": 0.0,
            "residual_p_positive": 0.0,
            "skipped": "insufficient overlap",
        }

    # HC0 (White) heteroskedasticity-consistent SE on the alpha intercept.
    # We re-derive from the fit residuals because risk_model.fit_factor_model
    # only exposes the headline coefficients, not the SE matrix.
    joined = pd.concat(
        [portfolio_returns.rename("asset"), reference_factors],
        axis=1, join="inner",
    ).dropna()
    y = joined["asset"].to_numpy(dtype=np.float64)
    X_f = joined[list(reference_factors.columns)].to_numpy(dtype=np.float64)
    X = np.column_stack([np.ones(len(joined), dtype=np.float64), X_f])
    n = len(joined)
    k = X.shape[1]

    try:
        XtX_inv = np.linalg.inv(X.T @ X)
    except np.linalg.LinAlgError:
        XtX_inv = None

    residuals = fit.residuals.to_numpy(dtype=np.float64)
    if XtX_inv is not None and len(residuals) == n:
        # HC0 sandwich
        meat = (X * residuals[:, None]).T @ (X * residuals[:, None])
        cov_hc0 = XtX_inv @ meat @ XtX_inv
        se_alpha = float(np.sqrt(max(0.0, cov_hc0[0, 0])))
    else:
        # Fallback: classical OLS SE
        sigma2 = float(np.sum(residuals ** 2) / max(1, n - k))
        se_alpha = float(np.sqrt(max(0.0, sigma2 * (XtX_inv[0, 0] if XtX_inv is not None else 1.0))))

    alpha_daily = float(fit.alpha)
    alpha_t = alpha_daily / se_alpha if se_alpha > 1e-15 else 0.0
    # Two-sided p-value via normal approximation (n is large; t→z).
    alpha_p = float(2.0 * (1.0 - _normal_cdf(abs(alpha_t))))

    # FF5-residual return series = α + ε (i.e., the asset-return component
    # NOT explained by the factors). This is what we Sharpe-ify.
    resid_plus_alpha = (residuals + alpha_daily).astype(np.float64)
    res_sharpe = _ann_sharpe(resid_plus_alpha)
    boot = _bootstrap_sharpe_ci(
        resid_plus_alpha, reps=bootstrap_reps,
        mean_block=bootstrap_block, seed=bootstrap_seed,
    )

    return {
        "alpha_daily": alpha_daily,
        "alpha_annual": float(alpha_daily * _TRADING_DAYS_PER_YEAR),
        "alpha_t": float(alpha_t),
        "alpha_p_two_sided": alpha_p,
        "betas": fit.betas,
        "r_squared": float(fit.r_squared),
        "n_obs": int(fit.n_obs),
        "residual_sharpe": res_sharpe,
        "residual_sharpe_ci_lo": boot["ci_lo"],
        "residual_sharpe_ci_hi": boot["ci_hi"],
        "residual_p_positive": boot["p_positive"],
    }


def _normal_cdf(x: float) -> float:
    """Standard normal CDF — kept here to avoid pulling scipy into this
    module's import surface for one function call."""
    from math import erf, sqrt
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def slice_portfolio_alpha_per_window(
    portfolio_returns: pd.Series,
    reference_factors: pd.DataFrame,
    windows: Iterable[tuple[str, str, str]],
    *,
    bootstrap_reps: int = 2000,
    bootstrap_block: int = 21,
) -> Dict[str, dict]:
    """Run `compute_portfolio_alpha` on each (name, start, end) window slice."""
    out: Dict[str, dict] = {}
    for win_name, win_start, win_end in windows:
        sub_p = portfolio_returns.loc[win_start:win_end]
        if len(sub_p) < 21:
            out[win_name] = {"skipped": "too few observations", "n_obs": int(len(sub_p))}
            continue
        sub_f = reference_factors.loc[win_start:win_end]
        result = compute_portfolio_alpha(
            sub_p, sub_f,
            bootstrap_reps=bootstrap_reps,
            bootstrap_block=bootstrap_block,
        )
        result["start"] = win_start
        result["end"] = win_end
        out[win_name] = result
    return out
