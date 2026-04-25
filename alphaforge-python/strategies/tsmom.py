"""Time-Series Momentum (TSMOM) — Moskowitz, Ooi & Pedersen (2012).

Fundamentally different from cross-sectional momentum:

  - Cross-sectional: rank tickers against each other, long the top,
    short the bottom. Beta-positive; sector-tilted.
  - Time-series: each ticker tested against its *own* history. Long
    if the trailing-K return is positive, short if negative.

Position sizing uses equal risk contribution: each leg is scaled to a
target annualized volatility. This is the structural reason TSMOM tends
to survive transaction costs better than cross-sectional momentum — it
rebalances against its own vol rather than the market's dispersion.

    sign_i = sign(r_i(lookback))
    weight_i = sign_i * (vol_target / sigma_i) / N

where sigma_i is the trailing K-day realized volatility (annualized) and
N scales the aggregate leverage to avoid unbounded gross exposure.

Monthly rebalanced, positions carried between rebalances. Optional
exponential smoothing on the realized vol.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict

import numpy as np
import pandas as pd


@dataclass
class TSMOMConfig:
    lookback_days: int = 252          # 12-month signal window
    vol_window_days: int = 63          # 3-month realized-vol window
    vol_target_annual: float = 0.10    # per-leg volatility target
    max_leg_leverage: float = 1.0      # cap per-ticker |weight|
    max_gross_leverage: float = 2.0    # cap sum(|weight|)
    holding_period_days: int = 21      # monthly rebalance


def _ann_realized_vol(log_rets: pd.DataFrame, window: int) -> pd.DataFrame:
    return log_rets.rolling(window).std() * math.sqrt(252)


def tsmom_weights(close: pd.DataFrame, cfg: TSMOMConfig) -> pd.DataFrame:
    """Return signed weights per ticker per rebalance date.

    Output is a T × K DataFrame aligned to ``close``, with weights set on
    each rebalance day and held constant in between (forward-filled until
    the next rebalance).
    """
    log_rets = np.log(close).diff()
    # Signal: sign of trailing lookback return. Use simple (not log) return.
    lookback_ret = close.pct_change(cfg.lookback_days)
    sign = np.sign(lookback_ret)
    sigma = _ann_realized_vol(log_rets, cfg.vol_window_days)
    sigma = sigma.clip(lower=1e-4)
    target_leg = cfg.vol_target_annual / sigma
    target_leg = target_leg.clip(upper=cfg.max_leg_leverage)
    raw_w = sign * target_leg

    # Cap gross leverage per rebalance day
    gross = raw_w.abs().sum(axis=1)
    scale = (cfg.max_gross_leverage / gross).clip(upper=1.0)
    w = raw_w.mul(scale, axis=0)

    # Enforce rebalance cadence: zero out non-rebalance days so forward-fill
    # carries the latest monthly weights forward.
    idx = close.index
    rebal_mask = np.zeros(len(idx), dtype=bool)
    rebal_mask[::cfg.holding_period_days] = True
    # After first valid signal
    first_valid = lookback_ret.dropna(how="all").index.min()
    start_pos = idx.get_loc(first_valid) if first_valid in idx else 0
    if isinstance(start_pos, slice):
        start_pos = start_pos.start
    rebal_mask[:start_pos] = False
    # Weights on rebal days; NaN otherwise so ffill carries forward.
    weights = pd.DataFrame(np.nan, index=idx, columns=close.columns, dtype=float)
    weights.loc[idx[rebal_mask]] = w.loc[idx[rebal_mask]]
    return weights.ffill().fillna(0.0)


def tsmom_backtest(
    close: pd.DataFrame,
    cfg: TSMOMConfig,
    tx_bps_per_turnover: float = 10.0,
) -> Dict[str, pd.Series]:
    """Run a TSMOM backtest.

    Cost model: `tx_bps_per_turnover` bps on each rebalance per unit of
    dollar turnover (|Δw|). Cheap flat model; swap in the square-root
    impact library for a real capacity study.
    """
    weights = tsmom_weights(close, cfg)
    rets = close.pct_change().fillna(0.0)
    gross = (weights.shift(1).fillna(0.0) * rets).sum(axis=1)
    turnover = weights.diff().abs().sum(axis=1).fillna(0.0)
    cost = turnover * tx_bps_per_turnover * 1e-4
    net = gross - cost
    return {
        "gross": gross,
        "net": net,
        "turnover": turnover,
        "weights": weights,
    }
