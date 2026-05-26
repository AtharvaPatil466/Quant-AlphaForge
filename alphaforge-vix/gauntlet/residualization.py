"""Four-factor short-vol residualization — VIX_DESIGN.md §7.

Time-series OLS of daily strategy returns on:
  • Factor 1 — SPY return (equity beta)
  • Factor 2 — ΔVIX (spot VIX log change)
  • Factor 3 — ST-Reversal (Kenneth French daily ST-Rev factor)
  • Factor 4 — Carry (proxy: FRED DGS3MO daily change)

HC0 (White 1980) heteroskedasticity-consistent standard errors. The pre-
commit gate is **alpha intercept t-stat > 1.96 (two-sided p < 0.05)**.

Falloff per §7: if a factor is unavailable for a window, the regression
runs on the available factors and the verdict is flagged provisional.

Pure numpy/pandas — no scipy / statsmodels dependency.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd


ALPHA_T_STAT_THRESHOLD: float = 1.96     # two-sided 5%


@dataclass(frozen=True)
class FactorAvailability:
    spy: bool
    delta_vix: bool
    st_reversal: bool
    carry: bool

    @property
    def n_factors(self) -> int:
        return sum([self.spy, self.delta_vix, self.st_reversal, self.carry])

    @property
    def missing(self) -> list[str]:
        out = []
        if not self.spy: out.append("SPY")
        if not self.delta_vix: out.append("DeltaVIX")
        if not self.st_reversal: out.append("ST_Reversal")
        if not self.carry: out.append("Carry")
        return out


@dataclass(frozen=True)
class ResidualizationResult:
    alpha: float                # intercept (daily-return units)
    alpha_se_hc0: float         # HC0 standard error of the intercept
    alpha_t_stat: float
    alpha_passes_gate: bool
    n_obs: int
    coefficients: dict[str, float]  # per-factor slope coefficients
    factor_availability: FactorAvailability
    provisional: bool           # True if any of the 4 factors were missing
    note: str

    def to_dict(self) -> dict:
        return {
            "alpha": self.alpha,
            "alpha_se_hc0": self.alpha_se_hc0,
            "alpha_t_stat": self.alpha_t_stat,
            "alpha_passes_gate": self.alpha_passes_gate,
            "n_obs": self.n_obs,
            "coefficients": self.coefficients,
            "factor_availability": {
                "spy": self.factor_availability.spy,
                "delta_vix": self.factor_availability.delta_vix,
                "st_reversal": self.factor_availability.st_reversal,
                "carry": self.factor_availability.carry,
                "n_factors": self.factor_availability.n_factors,
                "missing": self.factor_availability.missing,
            },
            "provisional": self.provisional,
            "note": self.note,
        }


def _hc0_se(X: np.ndarray, residuals: np.ndarray) -> np.ndarray:
    """White HC0 standard errors for OLS coefficients.

    SE_HC0(β) = √diag( (X'X)^-1 · X' diag(e²) X · (X'X)^-1 )
    """
    n, k = X.shape
    XtX_inv = np.linalg.inv(X.T @ X)
    # Meat: Σ e_i² · x_i x_i'  ==  X' diag(e²) X
    e_sq = residuals ** 2
    meat = X.T @ (e_sq[:, None] * X)
    cov = XtX_inv @ meat @ XtX_inv
    return np.sqrt(np.diag(cov))


def build_factor_panel(
    spy_returns: pd.Series | None = None,
    delta_vix: pd.Series | None = None,
    st_reversal: pd.Series | None = None,
    carry_change: pd.Series | None = None,
) -> pd.DataFrame:
    """Build the daily 4-factor panel. Each input is optional; missing
    factors are simply absent from the output. Caller can pass `None` for
    factors that aren't available in the substrate window.
    """
    cols: dict[str, pd.Series] = {}
    if spy_returns is not None:
        cols["SPY"] = spy_returns
    if delta_vix is not None:
        cols["DeltaVIX"] = delta_vix
    if st_reversal is not None:
        cols["ST_Reversal"] = st_reversal
    if carry_change is not None:
        cols["Carry"] = carry_change
    if not cols:
        return pd.DataFrame()
    return pd.DataFrame(cols).sort_index()


def residualize(
    strategy_returns: pd.Series,
    factor_panel: pd.DataFrame,
) -> ResidualizationResult:
    """Run the §7 OLS with HC0 SEs.

    Returns a `ResidualizationResult` with the alpha intercept, its HC0
    SE, and the pass/fail flag against the 1.96 t-stat threshold.

    Factors that are absent from `factor_panel` are dropped from the
    regression; the result is flagged `provisional=True` per §7.
    """
    # Align on the strategy-return index intersection with every factor.
    aligned = pd.concat(
        [strategy_returns.rename("y"), factor_panel],
        axis=1,
        sort=True,
    ).dropna()
    if aligned.empty or len(aligned) < 30:
        return ResidualizationResult(
            alpha=float("nan"),
            alpha_se_hc0=float("nan"),
            alpha_t_stat=float("nan"),
            alpha_passes_gate=False,
            n_obs=int(len(aligned)),
            coefficients={},
            factor_availability=FactorAvailability(
                spy="SPY" in factor_panel.columns,
                delta_vix="DeltaVIX" in factor_panel.columns,
                st_reversal="ST_Reversal" in factor_panel.columns,
                carry="Carry" in factor_panel.columns,
            ),
            provisional=True,
            note="insufficient overlapping observations (<30)",
        )
    y = aligned["y"].to_numpy()
    X_cols = [c for c in aligned.columns if c != "y"]
    X = aligned[X_cols].to_numpy()
    # Prepend constant column for the intercept (alpha).
    X = np.hstack([np.ones((X.shape[0], 1)), X])
    XtX_inv = np.linalg.inv(X.T @ X)
    beta = XtX_inv @ X.T @ y
    residuals = y - X @ beta
    se = _hc0_se(X, residuals)
    alpha = float(beta[0])
    alpha_se = float(se[0])
    if alpha_se == 0.0 or not np.isfinite(alpha_se):
        t_stat = float("nan")
        passes = False
    else:
        t_stat = alpha / alpha_se
        passes = abs(t_stat) > ALPHA_T_STAT_THRESHOLD and alpha > 0
    coefficients = {col: float(beta[i + 1]) for i, col in enumerate(X_cols)}
    factor_avail = FactorAvailability(
        spy="SPY" in X_cols,
        delta_vix="DeltaVIX" in X_cols,
        st_reversal="ST_Reversal" in X_cols,
        carry="Carry" in X_cols,
    )
    provisional = factor_avail.n_factors < 4
    note = (f"{factor_avail.n_factors}/4 factors present; "
            f"missing = {factor_avail.missing}"
            if provisional else "all 4 factors present")
    return ResidualizationResult(
        alpha=alpha,
        alpha_se_hc0=alpha_se,
        alpha_t_stat=t_stat,
        alpha_passes_gate=bool(passes),
        n_obs=int(len(aligned)),
        coefficients=coefficients,
        factor_availability=factor_avail,
        provisional=provisional,
        note=note,
    )
