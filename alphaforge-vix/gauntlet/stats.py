"""Statistical hygiene for the VIX gauntlet — DSR + bootstrap CI + Cornish-Fisher.

All functions are pure numpy/python — no scipy dependency. Deterministic via
explicit `seed` arguments. Wired to the six-gate framework:

  • Gate 1 — `deflated_sharpe_ratio` (Bailey & López de Prado 2014).
  • Gate 2 — `stationary_bootstrap_sharpe_ci` (Politis & Romano 1994).
  • Gate 6 — `cornish_fisher_sharpe` (Favre & Galeano 2002).

The annualization convention follows the equity stack: 252 trading days/year.
Sharpe is computed against zero (no risk-free subtraction at this layer —
margin carry is handled in the backtest's NAV calculation per §6 / §14.7).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

ANNUALIZATION = 252.0


# ---------------------------------------------------------------------------
# Sharpe
# ---------------------------------------------------------------------------

_ZERO_STD_TOL = 1e-12


def annualized_sharpe(daily_returns: np.ndarray | pd.Series,
                      annualization: float = ANNUALIZATION) -> float:
    """Vanilla annualized Sharpe: mean / std × √252. Zero if std is at or
    near machine zero (FP-tolerant)."""
    if isinstance(daily_returns, pd.Series):
        daily_returns = daily_returns.dropna().to_numpy()
    if daily_returns.size < 2:
        return float("nan")
    mu = float(np.mean(daily_returns))
    sd = float(np.std(daily_returns, ddof=1))
    if sd < _ZERO_STD_TOL or not np.isfinite(sd):
        return 0.0
    return mu / sd * math.sqrt(annualization)


# ---------------------------------------------------------------------------
# Cornish-Fisher modified Sharpe
# ---------------------------------------------------------------------------

def _moment(x: np.ndarray, k: int) -> float:
    """k-th sample central moment."""
    mu = np.mean(x)
    return float(np.mean((x - mu) ** k))


def sample_skewness(returns: np.ndarray) -> float:
    """Population skewness g_1 = m3 / m2^(3/2). No bias correction (matches
    numpy default convention)."""
    m2 = _moment(returns, 2)
    if m2 == 0.0:
        return 0.0
    m3 = _moment(returns, 3)
    return m3 / (m2 ** 1.5)


def sample_excess_kurtosis(returns: np.ndarray) -> float:
    """Population excess kurtosis g_2 = m4 / m2^2 − 3."""
    m2 = _moment(returns, 2)
    if m2 == 0.0:
        return 0.0
    m4 = _moment(returns, 4)
    return m4 / (m2 ** 2) - 3.0


def cornish_fisher_sharpe(
    daily_returns: np.ndarray | pd.Series,
    alpha: float = 0.05,
    annualization: float = ANNUALIZATION,
) -> float:
    """Cornish-Fisher modified Sharpe ratio (Favre & Galeano 2002).

    Adjusts the Sharpe denominator by a CF correction factor that penalizes
    negative skewness and positive excess kurtosis. At `alpha = 0.05`, the
    normal critical value is z = -1.6449.

    Returns the daily CF-Sharpe multiplied by √annualization.
    """
    if isinstance(daily_returns, pd.Series):
        daily_returns = daily_returns.dropna().to_numpy()
    if daily_returns.size < 4:
        return float("nan")
    mu = float(np.mean(daily_returns))
    sd = float(np.std(daily_returns, ddof=1))
    if sd == 0.0 or not np.isfinite(sd):
        return 0.0
    s = sample_skewness(daily_returns)
    k = sample_excess_kurtosis(daily_returns)
    # Standard normal lower α-quantile.
    if alpha == 0.05:
        z = -1.6448536269514722
    elif alpha == 0.01:
        z = -2.3263478740408408
    else:
        # Crude approximation: only the two alphas above are exact in this
        # module; other values use a coarse polynomial via numpy.
        # (Avoids scipy import; gauntlet uses alpha=0.05 only per §5.6.)
        raise ValueError(
            "cornish_fisher_sharpe: only alpha=0.05 and alpha=0.01 supported"
        )
    # Cornish-Fisher z adjustment.
    z_cf = (z
            + (z ** 2 - 1) * s / 6.0
            + (z ** 3 - 3 * z) * k / 24.0
            - (2 * z ** 3 - 5 * z) * (s ** 2) / 36.0)
    # Per VIX_DESIGN.md §5.6: CF-Sharpe = Sharpe / (CF VaR-adjustment factor).
    # Adjustment factor = z_CF / z. For normal returns z_CF == z → factor = 1
    # → CF-Sharpe == Sharpe. For negative-skew returns |z_CF| > |z| →
    # factor > 1 → CF-Sharpe < Sharpe (the penalty).
    if z == 0.0:
        adjustment = 1.0
    else:
        adjustment = z_cf / z
    base_sharpe = mu / sd * math.sqrt(annualization)
    if adjustment == 0.0:
        return float("inf") if base_sharpe > 0 else (
               float("-inf") if base_sharpe < 0 else 0.0)
    # Per design, the adjustment can flip sign in extreme tails — we use
    # |adjustment| so the penalty is always a magnitude.
    return float(base_sharpe / abs(adjustment))


# ---------------------------------------------------------------------------
# Deflated Sharpe Ratio (Bailey & López de Prado 2014)
# ---------------------------------------------------------------------------

# Standard-normal CDF via erf — no scipy required.
def _norm_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def deflated_sharpe_ratio(
    sharpe_observed: float,
    n_trials: int,
    n_obs: int,
    skewness: float = 0.0,
    excess_kurtosis: float = 0.0,
    annualization: float = ANNUALIZATION,
) -> float:
    """DSR per Bailey & López de Prado (2014).

    Inputs:
        sharpe_observed   — annualized Sharpe of the strategy being tested.
        n_trials          — total number of strategies in the multiple-testing
                            family (deflation denominator; §4 = 28).
        n_obs             — number of return observations (e.g., trading days).
        skewness          — sample skewness of the daily returns.
        excess_kurtosis   — sample excess kurtosis of the daily returns.

    Returns:
        DSR ∈ [0, 1] — probability that the observed Sharpe exceeds what
        would be expected under the null after deflation for multiple
        testing and non-Gaussian higher moments. Pass criterion (per §5.1):
        DSR > 0.95.

    Implementation follows Bailey-LdP 2014 equations (6)-(7):

        sharpe_expected_max = √2 · √(γ + (1−γ)·log(2π·(1−exp(−γ²/2))))
            where γ ≈ Euler-Mascheroni ≈ 0.5772156649

        Actually the standard form is:

        E[max Sharpe] ≈ ((1 − γ) · z_{1−1/n_trials} + γ · z_{1−1/(n_trials·e)})
            where z is the standard-normal quantile.

        DSR = Φ((sharpe_observed - E[max Sharpe]) ·
                 √((n_obs − 1) / (1 − skew·SR + (kurt−1)/4 · SR²)))

    where SR is in *daily* units. We convert annualized Sharpe → daily by
    dividing by √annualization.
    """
    if n_trials < 1:
        raise ValueError(f"n_trials must be >= 1, got {n_trials}")
    if n_obs < 5:
        return float("nan")
    sr_daily = sharpe_observed / math.sqrt(annualization)

    # E[max Sharpe] under the null — daily units.
    gamma_em = 0.5772156649015329
    # Standard-normal quantile via inverse erf (Beasley-Springer-Moro approx).
    def _norm_inv(p: float) -> float:
        # Acklam-style approximation; sufficient for our gauntlet use.
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

    # Bailey-LdP variance of Sharpe under the null (eq. 9), in daily units.
    var_term = (1 - skewness * sr_daily
                + ((excess_kurtosis - 1) / 4.0) * sr_daily ** 2) / (n_obs - 1)
    if var_term <= 0:
        return 0.0
    sigma_sr = math.sqrt(var_term)

    # E[SR_max] under the null in daily-Sharpe units (Bailey-LdP eq. 6):
    #     E[SR_max] = σ̂(SR) · ((1-γ)·z₁ + γ·z₂)
    n = n_trials
    if n == 1:
        e_max = 0.0
    else:
        z1 = _norm_inv(1.0 - 1.0 / n)
        z2 = _norm_inv(1.0 - 1.0 / (n * math.e))
        e_max = sigma_sr * ((1 - gamma_em) * z1 + gamma_em * z2)

    if sigma_sr == 0.0:
        return float("nan")
    z_stat = (sr_daily - e_max) / sigma_sr
    return _norm_cdf(z_stat)


# ---------------------------------------------------------------------------
# Stationary bootstrap CI (Politis & Romano 1994)
# ---------------------------------------------------------------------------

def stationary_bootstrap_indices(
    n: int,
    expected_block_size: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Generate one bootstrap sample of indices using the Politis-Romano
    stationary bootstrap with geometric block lengths.

    `expected_block_size` is the mean block length (mean 21 days per §5.2).
    """
    if n <= 0:
        return np.array([], dtype=int)
    if expected_block_size < 1:
        raise ValueError("expected_block_size must be >= 1")
    p = 1.0 / expected_block_size
    out = np.empty(n, dtype=int)
    idx = int(rng.integers(0, n))
    out[0] = idx
    for t in range(1, n):
        if rng.random() < p:
            idx = int(rng.integers(0, n))
        else:
            idx = (idx + 1) % n
        out[t] = idx
    return out


@dataclass(frozen=True)
class SharpeBootstrapCI:
    sharpe: float
    lower: float
    upper: float
    n_replications: int
    expected_block_size: int
    seed: int


def stationary_bootstrap_sharpe_ci(
    daily_returns: np.ndarray | pd.Series,
    n_replications: int = 4000,
    expected_block_size: int = 21,
    confidence: float = 0.95,
    seed: int = 0,
    annualization: float = ANNUALIZATION,
) -> SharpeBootstrapCI:
    """Stationary-bootstrap 95% CI for annualized Sharpe.

    Per Politis-Romano 1994 with geometric block lengths.

    Returns the (lower, upper) annualized-Sharpe quantiles and the
    point-estimate Sharpe on the original series.
    """
    if isinstance(daily_returns, pd.Series):
        daily_returns = daily_returns.dropna().to_numpy()
    if daily_returns.size < expected_block_size + 1:
        return SharpeBootstrapCI(
            sharpe=annualized_sharpe(daily_returns, annualization),
            lower=float("nan"), upper=float("nan"),
            n_replications=0,
            expected_block_size=expected_block_size, seed=seed,
        )
    rng = np.random.default_rng(seed)
    base_sharpe = annualized_sharpe(daily_returns, annualization)
    boots = np.empty(n_replications, dtype=float)
    n = daily_returns.size
    for k in range(n_replications):
        idx = stationary_bootstrap_indices(n, expected_block_size, rng)
        sample = daily_returns[idx]
        boots[k] = annualized_sharpe(sample, annualization)
    boots = boots[np.isfinite(boots)]
    alpha = 1.0 - confidence
    lower = float(np.quantile(boots, alpha / 2.0))
    upper = float(np.quantile(boots, 1.0 - alpha / 2.0))
    return SharpeBootstrapCI(
        sharpe=base_sharpe,
        lower=lower,
        upper=upper,
        n_replications=int(boots.size),
        expected_block_size=expected_block_size,
        seed=seed,
    )


# ---------------------------------------------------------------------------
# Sign agreement helper (Gate 3)
# ---------------------------------------------------------------------------

def sign_agreement(
    returns_oos_a: np.ndarray | pd.Series,
    returns_oos_b: np.ndarray | pd.Series,
) -> bool:
    """Both OOS windows must have positive Sharpe (per §5.3)."""
    s_a = annualized_sharpe(returns_oos_a)
    s_b = annualized_sharpe(returns_oos_b)
    if not (np.isfinite(s_a) and np.isfinite(s_b)):
        return False
    return s_a > 0 and s_b > 0
