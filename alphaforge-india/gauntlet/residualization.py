"""Four-factor residualization model for Indian equities.

Per research/INDIA_DESIGN.md §7:

    Factor 1: Market (RM-Rf)  — Nifty 500 EW return minus risk-free rate
    Factor 2: Risk-free rate  — RBI 91-day T-Bill rate (daily)
    Factor 3: Size proxy (SMB-like) — long bottom-half by free-float mcap,
              short top-half
    Factor 4: Liquidity proxy (Amihud) — long low-Amihud quintile,
              short high-Amihud quintile

    Residualization protocol:
        Post-portfolio time-series regression of strategy daily returns on
        the four-factor return vector. HC0 heteroskedasticity-consistent
        standard errors on the alpha intercept.

    Hard rule (§7):
        Alpha intercept must be t-stat > 1.96 (two-sided p < 0.05) after
        residualization for a signal to pass. A signal whose entire return
        is captured by size or liquidity exposure is not a real signal.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

log = logging.getLogger("india.gauntlet.residualization")


# ---------------------------------------------------------------------------
# Amihud illiquidity
# ---------------------------------------------------------------------------

def compute_amihud_illiquidity(
    close: pd.DataFrame,
    volume: pd.DataFrame,
    window: int = 21,
) -> pd.DataFrame:
    """Rolling Amihud illiquidity: |return| / (volume × close).

    Parameters
    ----------
    close : pd.DataFrame
        Close prices (index=dates, columns=symbols).
    volume : pd.DataFrame
        Daily trading volume (same shape as close).
    window : int
        Rolling window in trading days.

    Returns
    -------
    pd.DataFrame
        Amihud illiquidity ratio (higher = less liquid).
    """
    returns = close.pct_change().abs()
    dollar_volume = volume * close
    # Avoid division by zero
    dollar_volume = dollar_volume.replace(0, np.nan)
    daily_amihud = returns / dollar_volume
    return daily_amihud.rolling(window, min_periods=window // 2).mean()


# ---------------------------------------------------------------------------
# Factor construction
# ---------------------------------------------------------------------------

def compute_market_factor(
    close: pd.DataFrame,
    risk_free_daily: pd.Series | None = None,
) -> pd.Series:
    """Market factor: equal-weighted portfolio return minus risk-free rate.

    If risk_free_daily is None, assumes Rf=0 (excess return = raw return).
    """
    ew_returns = close.pct_change().mean(axis=1)  # equal-weighted
    if risk_free_daily is not None:
        # Align risk-free to same dates
        rf = risk_free_daily.reindex(ew_returns.index).fillna(0)
        return ew_returns - rf
    return ew_returns


def compute_smb_factor(
    close: pd.DataFrame,
    market_cap: pd.DataFrame,
) -> pd.Series:
    """Size factor (SMB-like): long bottom-half mcap, short top-half.

    Parameters
    ----------
    close : pd.DataFrame
        Close prices.
    market_cap : pd.DataFrame
        Free-float market cap (same shape as close).

    Returns
    -------
    pd.Series
        Daily SMB factor return.
    """
    returns = close.pct_change()
    smb_returns: list[float] = []
    dates = returns.index

    for i, dt in enumerate(dates):
        if i == 0:
            smb_returns.append(0.0)
            continue

        mcap = market_cap.iloc[i - 1]  # use previous day's mcap for sorting
        rets = returns.iloc[i]
        valid = mcap.dropna().index.intersection(rets.dropna().index)

        if len(valid) < 4:
            smb_returns.append(0.0)
            continue

        median_mcap = mcap[valid].median()
        small = valid[mcap[valid] <= median_mcap]
        big = valid[mcap[valid] > median_mcap]

        small_ret = float(rets[small].mean()) if len(small) > 0 else 0.0
        big_ret = float(rets[big].mean()) if len(big) > 0 else 0.0
        smb_returns.append(small_ret - big_ret)

    return pd.Series(smb_returns, index=dates, name="SMB")


def compute_liquidity_factor(
    close: pd.DataFrame,
    volume: pd.DataFrame,
    amihud_window: int = 21,
) -> pd.Series:
    """Liquidity factor: long low-Amihud quintile, short high-Amihud quintile.

    Low Amihud = liquid, High Amihud = illiquid.
    """
    amihud = compute_amihud_illiquidity(close, volume, window=amihud_window)
    returns = close.pct_change()
    liq_returns: list[float] = []
    dates = returns.index

    for i, dt in enumerate(dates):
        if i == 0:
            liq_returns.append(0.0)
            continue

        amh = amihud.iloc[i - 1]  # previous day's Amihud for sorting
        rets = returns.iloc[i]
        valid = amh.dropna().index.intersection(rets.dropna().index)

        if len(valid) < 10:
            liq_returns.append(0.0)
            continue

        q20 = amh[valid].quantile(0.2)
        q80 = amh[valid].quantile(0.8)
        liquid = valid[amh[valid] <= q20]
        illiquid = valid[amh[valid] >= q80]

        liq_ret = float(rets[liquid].mean()) if len(liquid) > 0 else 0.0
        illiq_ret = float(rets[illiquid].mean()) if len(illiquid) > 0 else 0.0
        liq_returns.append(liq_ret - illiq_ret)

    return pd.Series(liq_returns, index=dates, name="LIQ")


def build_factor_matrix(
    close: pd.DataFrame,
    volume: pd.DataFrame,
    market_cap: pd.DataFrame | None = None,
    risk_free_daily: pd.Series | None = None,
) -> pd.DataFrame:
    """Build the four-factor return matrix.

    Returns
    -------
    pd.DataFrame
        Columns: MKT, SMB, LIQ, const (intercept term).
    """
    mkt = compute_market_factor(close, risk_free_daily)
    mkt.name = "MKT"

    if market_cap is not None:
        smb = compute_smb_factor(close, market_cap)
    else:
        # Fallback: use close * volume as proxy for market cap
        log.warning("No market_cap provided; using close × volume as proxy.")
        proxy_mcap = close * volume
        smb = compute_smb_factor(close, proxy_mcap)

    liq = compute_liquidity_factor(close, volume)

    factors = pd.DataFrame({
        "MKT": mkt,
        "SMB": smb,
        "LIQ": liq,
    })
    factors["const"] = 1.0
    return factors


# ---------------------------------------------------------------------------
# Residualization
# ---------------------------------------------------------------------------

@dataclass
class ResidualizeResult:
    """Result of time-series regression of strategy returns on factors."""
    alpha: float
    alpha_se_hc0: float
    alpha_t_stat: float
    alpha_p_value: float
    betas: dict[str, float]
    r_squared: float
    n_obs: int
    passed: bool  # t-stat > 1.96 (two-sided p < 0.05)

    def summary(self) -> str:
        beta_str = ", ".join(f"{k}={v:.3f}" for k, v in self.betas.items())
        return (
            f"α={self.alpha:.6f} (t={self.alpha_t_stat:.3f}, "
            f"p={self.alpha_p_value:.4f}), "
            f"R²={self.r_squared:.4f}, n={self.n_obs}, "
            f"betas=[{beta_str}] → {'PASS' if self.passed else 'FAIL'}"
        )


def residualize(
    strategy_returns: pd.Series,
    factor_matrix: pd.DataFrame,
) -> ResidualizeResult:
    """Regress strategy returns on factor matrix with HC0 standard errors.

    Parameters
    ----------
    strategy_returns : pd.Series
        Daily strategy returns.
    factor_matrix : pd.DataFrame
        Factor returns with columns MKT, SMB, LIQ, const.

    Returns
    -------
    ResidualizeResult
        Alpha, HC0 t-stat, betas, R².
    """
    from scipy import stats as sp_stats

    # Align dates
    common = strategy_returns.dropna().index.intersection(
        factor_matrix.dropna(how="any").index
    )
    if len(common) < 10:
        return ResidualizeResult(
            alpha=0.0, alpha_se_hc0=0.0, alpha_t_stat=0.0,
            alpha_p_value=1.0, betas={}, r_squared=0.0,
            n_obs=len(common), passed=False,
        )

    y = strategy_returns.loc[common].values
    X = factor_matrix.loc[common].values
    n, k = X.shape

    # OLS: β = (X'X)^{-1} X'y
    try:
        XtX_inv = np.linalg.inv(X.T @ X)
    except np.linalg.LinAlgError:
        XtX_inv = np.linalg.pinv(X.T @ X)

    beta = XtX_inv @ (X.T @ y)
    residuals = y - X @ beta

    # R²
    ss_res = float(np.sum(residuals**2))
    ss_tot = float(np.sum((y - np.mean(y))**2))
    r_sq = 1.0 - ss_res / max(ss_tot, 1e-12)

    # HC0 standard errors (White 1980)
    # Var(β) = (X'X)^{-1} X' diag(e²) X (X'X)^{-1}
    e2 = residuals**2
    meat = X.T @ np.diag(e2) @ X
    var_beta = XtX_inv @ meat @ XtX_inv
    se = np.sqrt(np.maximum(np.diag(var_beta), 0))

    # Alpha is the coefficient on const (last column)
    const_idx = list(factor_matrix.columns).index("const")
    alpha = float(beta[const_idx])
    alpha_se = float(se[const_idx])
    if alpha_se > 0:
        alpha_t = alpha / alpha_se
        alpha_p = float(2 * (1 - sp_stats.norm.cdf(abs(alpha_t))))
    else:
        alpha_t = 0.0
        alpha_p = 1.0

    # Betas for factor columns (exclude const)
    factor_names = [c for c in factor_matrix.columns if c != "const"]
    betas_dict = {}
    for fname in factor_names:
        idx = list(factor_matrix.columns).index(fname)
        betas_dict[fname] = float(beta[idx])

    return ResidualizeResult(
        alpha=alpha,
        alpha_se_hc0=alpha_se,
        alpha_t_stat=alpha_t,
        alpha_p_value=alpha_p,
        betas=betas_dict,
        r_squared=r_sq,
        n_obs=len(common),
        passed=abs(alpha_t) > 1.96,
    )
