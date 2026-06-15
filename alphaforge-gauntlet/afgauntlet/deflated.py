"""Deflated Sharpe Ratio (Bailey & López de Prado 2014) — canonical.

Consolidated verbatim from ``alphaforge-vix/gauntlet/stats.py``. The
``expected_max_sharpe`` helper is factored out (per-unit-σ expectation of the
max Sharpe under the null) but the DSR arithmetic is bit-identical to the VIX
implementation so reconciliation passes to float equality.

Pass criterion across substrates: DSR > 0.95.
"""
from __future__ import annotations

import math

import numpy as np

ANNUALIZATION = 252.0
_EULER_MASCHERONI = 0.5772156649015329


def _norm_cdf(z: float) -> float:
    """Standard-normal CDF via erf — no scipy required."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _norm_inv(p: float) -> float:
    """Standard-normal quantile (Acklam approximation). Sufficient for the
    gauntlet's E[max Sharpe] term."""
    if p <= 0.0 or p >= 1.0:
        raise ValueError("p must be in (0, 1)")
    a = [-3.969683028665376e+01, 2.209460984245205e+02,
         -2.759285104469687e+02, 1.383577518672690e+02,
         -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02,
         -1.556989798598866e+02, 6.680131188771972e+01,
         -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01,
         -2.400758277161838e+00, -2.549732539343734e+00,
         4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01,
         2.445134137142996e+00, 3.754408661907416e+00]
    p_low = 0.02425
    p_high = 1 - p_low
    if p < p_low:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    elif p <= p_high:
        q = p - 0.5
        r = q*q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
               (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    else:
        q = math.sqrt(-2 * math.log(1-p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)


def expected_max_sharpe(n_trials: int) -> float:
    """Per-unit-σ expectation of the maximum of ``n_trials`` independent
    standard Sharpe estimates under the null (Bailey-LdP eq. 6):

        E[SR_max] / σ̂(SR) = (1-γ)·z_{1−1/N} + γ·z_{1−1/(N·e)}

    Returns 0.0 for a single trial (no deflation)."""
    if n_trials < 1:
        raise ValueError(f"n_trials must be >= 1, got {n_trials}")
    if n_trials == 1:
        return 0.0
    z1 = _norm_inv(1.0 - 1.0 / n_trials)
    z2 = _norm_inv(1.0 - 1.0 / (n_trials * math.e))
    return (1 - _EULER_MASCHERONI) * z1 + _EULER_MASCHERONI * z2


def deflated_sharpe_ratio(
    sharpe_observed: float,
    n_trials: int,
    n_obs: int,
    skewness: float = 0.0,
    excess_kurtosis: float = 0.0,
    annualization: float = ANNUALIZATION,
) -> float:
    """DSR per Bailey & López de Prado (2014).

    Args:
        sharpe_observed:  annualized Sharpe of the strategy under test.
        n_trials:         size of the multiple-testing family (deflation denom).
        n_obs:            number of return observations (trading days).
        skewness:         sample skewness of the daily returns.
        excess_kurtosis:  sample EXCESS kurtosis (full kurtosis − 3).

    Returns DSR ∈ [0, 1]: the probability the observed Sharpe exceeds what the
    null would produce after deflating for multiple testing and non-Gaussian
    higher moments.
    """
    if n_trials < 1:
        raise ValueError(f"n_trials must be >= 1, got {n_trials}")
    if n_obs < 5:
        return float("nan")
    sr_daily = sharpe_observed / math.sqrt(annualization)

    var_term = (1 - skewness * sr_daily
                + ((excess_kurtosis + 2.0) / 4.0) * sr_daily ** 2) / (n_obs - 1)
    if var_term <= 0:
        return 0.0
    sigma_sr = math.sqrt(var_term)

    e_max = sigma_sr * expected_max_sharpe(n_trials)

    if sigma_sr == 0.0:
        return float("nan")
    z_stat = (sr_daily - e_max) / sigma_sr
    return _norm_cdf(z_stat)


def deflated_sharpe_ratio_from_trials(
    sharpe_observed: float,
    n_obs: int,
    trial_sharpes,
    skewness: float = 0.0,
    excess_kurtosis: float = 0.0,
    annualization: float = ANNUALIZATION,
) -> float:
    """DSR using the *empirical cross-trial* Sharpe variance as σ̂(SR).

    This is the original Bailey-LdP (2014) form (and the one the PEAD substrate
    used): instead of estimating σ̂(SR) from the analytic Lo (2002) formula, it
    estimates it from the dispersion of the observed family of trial Sharpes.
    Prefer this when you have the full set of trial Sharpes; prefer
    :func:`deflated_sharpe_ratio` when you only have the trial *count*.

    Args:
        sharpe_observed: annualized Sharpe of the strategy under test.
        n_obs:           number of return observations.
        trial_sharpes:   annualized Sharpes of every trial in the family
                         (length is the deflation N).
        skewness, excess_kurtosis: higher moments of the tested strategy's
                         daily returns (default Gaussian).

    Returns DSR ∈ [0, 1], or NaN if fewer than 2 trials / n_obs < 50.
    """
    sr_arr = np.asarray(list(trial_sharpes), dtype=float)
    if sr_arr.size < 2 or n_obs < 50:
        return float("nan")
    sr_daily_arr = sr_arr / math.sqrt(annualization)
    var_sr = float(sr_daily_arr.var(ddof=1))
    if var_sr <= 0:
        return float("nan")
    n_trials = sr_arr.size
    sr0_daily = math.sqrt(var_sr) * expected_max_sharpe(n_trials)
    sr_obs_daily = sharpe_observed / math.sqrt(annualization)
    denom_inner = (1 - skewness * sr_obs_daily
                   + ((excess_kurtosis + 2.0) / 4.0) * sr_obs_daily ** 2) / (n_obs - 1)
    if denom_inner <= 0:
        return float("nan")
    return _norm_cdf((sr_obs_daily - sr0_daily) / math.sqrt(denom_inner))
