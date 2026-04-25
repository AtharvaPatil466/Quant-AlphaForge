"""Honest transaction-cost model.

Three components, all billed in basis points on the dollar traded:

    cost_bps = spread_half_bps + commission_bps + impact_bps + borrow_bps_per_day

Impact follows the square-root form widely documented in the market-impact
literature (Almgren et al. 2005; Kissell 2014; BARRA):

    impact_bps = k * sqrt(participation)
    participation = |trade_$| / ADV_$

where k is a per-√-participation coefficient (~10–20 bps for liquid US
equities). This dominates flat-bps models at non-trivial AUM and is the
single biggest driver of the capacity ceiling.

Bid-ask spread is estimated from High/Low via Corwin-Schultz (2012), which
gives an ADV-free, O(1) per-day spread proxy. The estimator can emit
negative values in quiet periods; we clip at zero.

Borrow cost is annualized and billed only on the *short* leg per calendar
day. The default table assumes general-collateral mega-cap short supply
(25 bp/yr) with an override table for known hard-to-borrow names.

All computations are vectorized where possible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional

import numpy as np
import pandas as pd


# ─── impact ──────────────────────────────────────────────────────────────

@dataclass
class SquareRootImpactModel:
    """Square-root market-impact model.

    cost_bps_on_trade = k_bps * sqrt(|trade_$| / adv_$)

    k_bps defaults to 15 bps per √(1.0 participation), consistent with
    the Almgren/Kissell calibrations for US large-caps. Set floor to 0.5
    bps to model unavoidable price concession even for tiny orders.
    """
    k_bps: float = 15.0
    floor_bps: float = 0.5
    ceil_bps: float = 500.0  # sanity clip: above this, we're market-moving

    def cost_bps(self, trade_dollar: np.ndarray, adv_dollar: np.ndarray) -> np.ndarray:
        """Returns per-trade impact in bps. Arrays must broadcast."""
        adv_safe = np.maximum(adv_dollar, 1.0)
        trade_safe = np.abs(trade_dollar)
        participation = trade_safe / adv_safe
        impact = self.k_bps * np.sqrt(participation)
        return np.clip(impact, self.floor_bps, self.ceil_bps)

    def cost_dollar(self, trade_dollar: np.ndarray, adv_dollar: np.ndarray) -> np.ndarray:
        """Returns dollar cost of impact on each trade."""
        return np.abs(trade_dollar) * self.cost_bps(trade_dollar, adv_dollar) * 1e-4


# ─── spread (Corwin-Schultz 2012) ────────────────────────────────────────

def corwin_schultz_spread(high: pd.DataFrame, low: pd.DataFrame,
                          window: int = 21) -> pd.DataFrame:
    """Corwin-Schultz (2012) rolling bid-ask spread estimator.

    For consecutive 2-day windows:
      beta  = mean_over_window( sum( (ln(H_t / L_t))^2, t, t+1 ) )
      gamma = mean_over_window( (ln(H_{t,t+1} / L_{t,t+1}))^2 )
      alpha = (sqrt(2*beta) - sqrt(beta)) / (3 - 2*sqrt(2)) - sqrt(gamma / (3 - 2*sqrt(2)))
      spread = 2*(exp(alpha) - 1) / (1 + exp(alpha))

    Returned as a *half*-spread in bps (divide by 2 after obtaining the
    proportional spread, then × 10000). NaN where window is incomplete.
    """
    if high.shape != low.shape:
        raise ValueError("high and low must have the same shape")

    hl = np.log(high / low)
    hl_sq = hl ** 2
    beta = (hl_sq + hl_sq.shift(1)).rolling(window).mean()

    h2 = pd.concat([high, high.shift(1)]).groupby(level=0).max() if False else \
         pd.DataFrame(np.maximum(high.values, high.shift(1).values),
                      index=high.index, columns=high.columns)
    l2 = pd.DataFrame(np.minimum(low.values, low.shift(1).values),
                      index=low.index, columns=low.columns)
    gamma = (np.log(h2 / l2) ** 2).rolling(window).mean()

    k1 = 3.0 - 2.0 * np.sqrt(2.0)
    alpha = (np.sqrt(2.0 * beta) - np.sqrt(beta)) / k1 - np.sqrt(gamma / k1)
    spread_prop = 2.0 * (np.exp(alpha) - 1.0) / (1.0 + np.exp(alpha))
    # Corwin-Schultz can emit tiny negatives; clip at a small positive floor
    half_spread_bps = np.maximum(spread_prop, 0.0) * 0.5 * 1e4
    return half_spread_bps.fillna(0.0)


# ─── borrow cost ─────────────────────────────────────────────────────────

@dataclass
class BorrowCostTable:
    """Annualized borrow cost in bps per name.

    Defaults assume mega-cap general-collateral (25 bp/yr). Override via
    `htb_map` for names known to be hard-to-borrow in the study window.
    """
    default_bps_per_year: float = 25.0
    htb_map: Mapping[str, float] = field(default_factory=dict)

    def bps_per_year(self, ticker: str) -> float:
        return float(self.htb_map.get(ticker.upper(), self.default_bps_per_year))

    def daily_cost(self, ticker: str, short_notional_dollar: float,
                   days: int = 1) -> float:
        """Borrow fee on a short position over `days` calendar days."""
        return abs(short_notional_dollar) * self.bps_per_year(ticker) * 1e-4 * (days / 252.0)


# ─── aggregator ──────────────────────────────────────────────────────────

@dataclass
class HonestCostModel:
    """Bundle of spread + commission + impact + borrow, applied per rebalance.

    Inputs per rebalance are per-ticker dollar trades (signed), per-ticker
    ADV in dollars, and a flag mask for short positions to accrue borrow.
    """
    impact: SquareRootImpactModel = field(default_factory=SquareRootImpactModel)
    borrow: BorrowCostTable = field(default_factory=BorrowCostTable)
    commission_bps: float = 0.5
    spread_fallback_half_bps: float = 2.0

    def rebalance_cost_dollars(
        self,
        trade_dollar: pd.Series,
        adv_dollar: pd.Series,
        spread_half_bps: Optional[pd.Series] = None,
    ) -> pd.Series:
        """Dollar cost on each ticker for a single rebalance.

        trade_dollar: signed trade amount (positive = buy)
        adv_dollar:   average daily dollar volume at trade time
        spread_half_bps: optional Corwin-Schultz half-spread per ticker
        """
        trade_arr = trade_dollar.abs().to_numpy(dtype=float)
        adv_arr = adv_dollar.reindex(trade_dollar.index).to_numpy(dtype=float)
        if spread_half_bps is None:
            spread_arr = np.full_like(trade_arr, self.spread_fallback_half_bps)
        else:
            spread_arr = spread_half_bps.reindex(trade_dollar.index).fillna(
                self.spread_fallback_half_bps
            ).to_numpy(dtype=float)

        impact_bps = self.impact.cost_bps(trade_arr, adv_arr)
        total_bps = impact_bps + spread_arr + self.commission_bps
        return pd.Series(trade_arr * total_bps * 1e-4, index=trade_dollar.index)

    def holding_borrow_cost_dollars(
        self,
        short_notional: pd.Series,
        days: int = 1,
    ) -> pd.Series:
        """Borrow fees accrued on the short book over `days` calendar days."""
        out = pd.Series(0.0, index=short_notional.index)
        for tk, notional in short_notional.items():
            if notional >= 0:
                continue  # not short
            out[tk] = self.borrow.daily_cost(tk, notional, days=days)
        return out
