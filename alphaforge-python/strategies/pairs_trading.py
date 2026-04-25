"""Cointegration-based pairs trading (Gatev, Goetzmann, Rouwenhorst 2006;
Engle & Granger 1987).

Formation:
  1. Over a rolling formation window, find pairs (i, j) whose price ratio
     is cointegrated per an Engle-Granger ADF test on the spread residual.
  2. Rank candidate pairs by the absolute t-stat of the ADF test (or by
     residual Sharpe) and keep the top N.

Trading:
  3. Compute the spread z-score: z_t = (spread_t - mean) / std.
  4. Enter short-the-spread when z > entry_threshold (long j, short i
     in ratio β); enter long-the-spread when z < -entry_threshold.
  5. Exit when |z| < exit_threshold OR |z| > stop_threshold (stop-out).
  6. Each pair is dollar-neutral at entry — the portfolio's aggregate
     beta is (near) zero by construction.

This module deliberately uses a lightweight self-contained ADF test via
statsmodels if available; falls back to a simple AR(1) rejection check
if not. Pair-selection is the hardest part in practice; the included
default is a PRACTICAL, not optimal, ranker.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


# ─── cointegration test ──────────────────────────────────────────────────

def _ols_beta_residual(y: np.ndarray, x: np.ndarray) -> Tuple[float, float, np.ndarray]:
    """OLS y = a + b*x + e. Returns (a, b, residuals)."""
    x_bar = x.mean(); y_bar = y.mean()
    var_x = ((x - x_bar) ** 2).sum()
    if var_x <= 1e-12:
        return y_bar, 0.0, y - y_bar
    b = float(((x - x_bar) * (y - y_bar)).sum() / var_x)
    a = float(y_bar - b * x_bar)
    resid = y - (a + b * x)
    return a, b, resid


def _adf_tstat(series: np.ndarray) -> float:
    """Dickey-Fuller unit-root test statistic on the residual series.

    We fit Δy_t = ρ y_{t-1} + e_t and return the t-stat on ρ. Large
    negative values reject the unit-root null (i.e. the series is
    stationary, i.e. the pair is cointegrated).
    """
    y = np.asarray(series, dtype=float)
    y = y[np.isfinite(y)]
    n = len(y)
    if n < 20:
        return 0.0
    dy = np.diff(y)
    lag = y[:-1]
    lag_bar = lag.mean()
    var_lag = ((lag - lag_bar) ** 2).sum()
    if var_lag <= 1e-12:
        return 0.0
    rho = float(((lag - lag_bar) * (dy - dy.mean())).sum() / var_lag)
    resid = dy - rho * lag
    dof = max(n - 2, 1)
    sigma2 = float((resid ** 2).sum() / dof)
    se_rho = math.sqrt(sigma2 / var_lag) if var_lag > 0 else 1e9
    return rho / se_rho if se_rho > 0 else 0.0


# ─── formation ───────────────────────────────────────────────────────────

@dataclass
class PairSpec:
    y_ticker: str
    x_ticker: str
    beta: float
    adf_t: float
    spread_mean: float
    spread_std: float


def find_pairs(
    close: pd.DataFrame,
    adf_t_threshold: float = -2.5,
    top_n: int = 20,
) -> List[PairSpec]:
    """Scan all ordered pairs (y, x) and keep those with the most negative
    ADF t-stat on the log-spread residual.

    `adf_t_threshold` — only pairs whose ADF t is at least this negative
    are kept; `top_n` caps the count.
    """
    cols = list(close.columns)
    logp = np.log(close)
    out: List[PairSpec] = []
    for i, y in enumerate(cols):
        for j, x in enumerate(cols):
            if i == j:
                continue
            y_arr = logp[y].to_numpy(); x_arr = logp[x].to_numpy()
            mask = np.isfinite(y_arr) & np.isfinite(x_arr)
            if mask.sum() < 60:
                continue
            _, b, resid = _ols_beta_residual(y_arr[mask], x_arr[mask])
            if not np.isfinite(b) or abs(b) < 1e-6:
                continue
            t = _adf_tstat(resid)
            if t <= adf_t_threshold:
                out.append(PairSpec(y, x, b,
                                     t, float(resid.mean()),
                                     float(resid.std(ddof=1) or 1e-8)))
    out.sort(key=lambda s: s.adf_t)  # most negative first
    return out[:top_n]


# ─── trading ─────────────────────────────────────────────────────────────

@dataclass
class PairsConfig:
    formation_days: int = 252
    rebal_days: int = 63        # refit pairs quarterly
    entry_z: float = 2.0
    exit_z: float = 0.5
    stop_z: float = 4.0
    max_pairs: int = 20
    dollar_per_pair: float = 1.0  # normalized: pair weights sum to 1
    adf_threshold: float = -2.5


@dataclass
class PairState:
    spec: PairSpec
    position: int = 0  # -1 short spread, +1 long spread, 0 flat
    entry_z: float = 0.0


def pairs_backtest(
    close: pd.DataFrame,
    cfg: PairsConfig,
    tx_bps_per_turnover: float = 10.0,
) -> Dict[str, pd.Series]:
    """Cointegration pairs strategy backtest.

    Portfolio daily return is the sum over active pairs of
    sign * (log-return(y) - β * log-return(x)), equal-weighted across
    active pairs with pair_weight = 1 / max_pairs.
    """
    log_rets = np.log(close).diff().fillna(0.0)
    dates = close.index
    pair_weight = 1.0 / max(1, cfg.max_pairs)

    gross = pd.Series(0.0, index=dates)
    turnover = pd.Series(0.0, index=dates)

    active: List[PairState] = []
    last_refit: Optional[pd.Timestamp] = None

    for i, dt in enumerate(dates):
        # Refit pairs every rebal_days after the first formation window
        if i < cfg.formation_days:
            continue
        if last_refit is None or (i - dates.get_loc(last_refit)) >= cfg.rebal_days:
            window = close.iloc[i - cfg.formation_days:i]
            specs = find_pairs(window, adf_t_threshold=cfg.adf_threshold,
                               top_n=cfg.max_pairs)
            # Close any active pair not in the new spec set; open flat for new.
            prev_keys = {(p.spec.y_ticker, p.spec.x_ticker) for p in active}
            new_keys = {(s.y_ticker, s.x_ticker) for s in specs}
            drops = prev_keys - new_keys
            turnover.loc[dt] += len(drops) * pair_weight * 2.0  # close both legs
            active = [p for p in active if (p.spec.y_ticker, p.spec.x_ticker) in new_keys]
            # Refresh specs for kept pairs and add new ones as flat
            kept = {(p.spec.y_ticker, p.spec.x_ticker): p for p in active}
            active = []
            for s in specs:
                st = kept.get((s.y_ticker, s.x_ticker), PairState(spec=s))
                st.spec = s  # refresh β, mean, std
                active.append(st)
            last_refit = dt

        # Trade each active pair
        daily_pnl = 0.0
        for st in active:
            s = st.spec
            logp_y = math.log(max(close[s.y_ticker].iloc[i], 1e-10))
            logp_x = math.log(max(close[s.x_ticker].iloc[i], 1e-10))
            spread = logp_y - s.beta * logp_x
            z = (spread - s.spread_mean) / max(s.spread_std, 1e-8)

            # Entry / exit / stop
            if st.position == 0:
                if z > cfg.entry_z:
                    st.position = -1; st.entry_z = z
                    turnover.loc[dt] += pair_weight * 2.0
                elif z < -cfg.entry_z:
                    st.position = +1; st.entry_z = z
                    turnover.loc[dt] += pair_weight * 2.0
            else:
                if abs(z) < cfg.exit_z or abs(z) > cfg.stop_z:
                    st.position = 0
                    turnover.loc[dt] += pair_weight * 2.0

            if st.position != 0:
                # PnL: sign * (r_y - β r_x) per day
                pair_ret = log_rets[s.y_ticker].iloc[i] - s.beta * log_rets[s.x_ticker].iloc[i]
                daily_pnl += st.position * pair_weight * pair_ret
        gross.loc[dt] = daily_pnl

    cost = turnover * tx_bps_per_turnover * 1e-4
    net = gross - cost
    return {"gross": gross, "net": net, "turnover": turnover}
