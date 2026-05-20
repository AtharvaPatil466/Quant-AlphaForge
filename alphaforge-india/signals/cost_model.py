"""Indian equity cost model — full NSE regulatory stack.

Implements the per-side cost stack for NSE equity *delivery* trades as
defined in ``INDIA_DESIGN.md`` §6.

Per-side breakdown (in basis points on notional):

    +-----------------------------------------+-------+-------+
    | Component                               |  Buy  | Sell  |
    +-----------------------------------------+-------+-------+
    | Brokerage (NSE standard retail)         | 10.0  | 10.0  |
    | GST on brokerage (18 % of brokerage)    |  1.8  |  1.8  |
    | Exchange transaction charges            |  0.3  |  0.3  |
    | SEBI charges                            |  0.1  |  0.1  |
    | Stamp duty (state-level, buy-only)      |  1.5  |  0.0  |
    | STT (Securities Transaction Tax, sell)  |  0.0  | 10.0  |
    +-----------------------------------------+-------+-------+
    | Per-side total                          | 13.7  | 22.2  |
    +-----------------------------------------+-------+-------+

Round-trip parametric cost: 13.7 + 22.2 = 35.9 bp before market impact.
Market impact: linear, 10 bp per unit of turnover.
Gate 4 stress: doubled to 71.8 bp round-trip + 20 bp per unit impact.

Also provides the Corwin & Schultz (2012) High/Low bid-ask spread
estimator used as the §6 calibration check against the 5 bp half-spread
assumed in the parametric model.

References
----------
- Corwin, S. A., & Schultz, P. (2012). A Simple Way to Estimate Bid-Ask
  Spreads from Daily High and Low Prices. *Journal of Finance*, 67(2),
  719–760.
- INDIA_DESIGN.md §6.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

log = logging.getLogger("india.cost_model")

# ─── component constants (bps) ───────────────────────────────────────────

#: Brokerage charged on both sides.
BROKERAGE_BPS: float = 10.0

#: GST rate on brokerage (18 %).
GST_RATE: float = 0.18

#: GST charged as ``BROKERAGE_BPS * GST_RATE``.
GST_ON_BROKERAGE_BPS: float = BROKERAGE_BPS * GST_RATE  # 1.8

#: NSE exchange transaction charges.
EXCHANGE_TXN_BPS: float = 0.3

#: SEBI regulatory charges.
SEBI_CHARGES_BPS: float = 0.1

#: Stamp duty — charged on buy side only (state-level standard).
STAMP_DUTY_BPS: float = 1.5

#: Securities Transaction Tax — charged on sell side only.
STT_BPS: float = 10.0

#: Aggregate buy-side cost (no STT, includes stamp duty).
BUY_SIDE_BPS: float = (
    BROKERAGE_BPS
    + GST_ON_BROKERAGE_BPS
    + EXCHANGE_TXN_BPS
    + SEBI_CHARGES_BPS
    + STAMP_DUTY_BPS
)  # 13.7

#: Aggregate sell-side cost (includes STT, no stamp duty).
SELL_SIDE_BPS: float = (
    BROKERAGE_BPS
    + GST_ON_BROKERAGE_BPS
    + EXCHANGE_TXN_BPS
    + SEBI_CHARGES_BPS
    + STT_BPS
)  # 22.2

#: Round-trip regulatory cost (buy + sell, before impact).
ROUND_TRIP_BPS: float = BUY_SIDE_BPS + SELL_SIDE_BPS  # 35.9

#: Linear market-impact coefficient (bps per unit turnover).
IMPACT_BPS_PER_UNIT: float = 10.0

#: Gate 4 stress multiplier.
STRESS_MULTIPLIER: float = 2.0


# ─── IndianCostModel ─────────────────────────────────────────────────────


@dataclass
class IndianCostModel:
    """Full Indian regulatory cost stack for NSE equity delivery trades.

    All costs are in basis points (1 bp = 0.01 %).

    Parameters
    ----------
    brokerage_bps : float
        Per-side brokerage (buy + sell both pay this).
    gst_rate : float
        GST rate applied on brokerage.
    exchange_txn_bps : float
        NSE exchange transaction charges.
    sebi_charges_bps : float
        SEBI regulatory charges.
    stamp_duty_bps : float
        Stamp duty charged on buy side only.
    stt_bps : float
        Securities Transaction Tax charged on sell side only.
    impact_bps_per_unit : float
        Linear market-impact coefficient (bps per unit turnover).
    stress_multiplier : float
        Multiplier applied to the full stack + impact for Gate 4.
    """

    brokerage_bps: float = BROKERAGE_BPS
    gst_rate: float = GST_RATE
    exchange_txn_bps: float = EXCHANGE_TXN_BPS
    sebi_charges_bps: float = SEBI_CHARGES_BPS
    stamp_duty_bps: float = STAMP_DUTY_BPS
    stt_bps: float = STT_BPS
    impact_bps_per_unit: float = IMPACT_BPS_PER_UNIT
    stress_multiplier: float = STRESS_MULTIPLIER

    # ── derived helpers ──────────────────────────────────────────────

    @property
    def gst_on_brokerage_bps(self) -> float:
        """GST charged on brokerage (18 % of brokerage by default)."""
        return self.brokerage_bps * self.gst_rate

    @property
    def _common_bps(self) -> float:
        """Sum of components common to both buy and sell sides."""
        return (
            self.brokerage_bps
            + self.gst_on_brokerage_bps
            + self.exchange_txn_bps
            + self.sebi_charges_bps
        )

    # ── public API ───────────────────────────────────────────────────

    def buy_cost_bps(self, notional: float = 1.0) -> float:
        """Total buy-side cost in bps.

        The *notional* parameter is accepted for interface symmetry
        but is currently unused (all components are flat bps on
        notional, not tiered).

        Parameters
        ----------
        notional : float
            Trade notional in local currency.  Reserved for future
            tiered-brokerage extensions.

        Returns
        -------
        float
            Buy-side cost in basis points.
        """
        return self._common_bps + self.stamp_duty_bps

    def sell_cost_bps(self, notional: float = 1.0) -> float:
        """Total sell-side cost in bps.

        Parameters
        ----------
        notional : float
            Trade notional in local currency.  Reserved for future
            tiered-brokerage extensions.

        Returns
        -------
        float
            Sell-side cost in basis points.
        """
        return self._common_bps + self.stt_bps

    def round_trip_cost_bps(self, turnover: float = 1.0) -> float:
        """Total round-trip cost including linear market impact.

        Parameters
        ----------
        turnover : float
            Portfolio turnover expressed as a fraction of NAV.
            ``1.0`` means the entire portfolio is turned over
            (baseline assumption in §6).

        Returns
        -------
        float
            Round-trip cost in basis points.
        """
        regulatory = self.buy_cost_bps() + self.sell_cost_bps()
        impact = self.impact_bps_per_unit * max(turnover, 0.0)
        return regulatory + impact

    def stressed_round_trip_cost_bps(self, turnover: float = 1.0) -> float:
        """Gate 4 doubled round-trip cost.

        Applies :pyattr:`stress_multiplier` (default 2×) to both
        the regulatory stack **and** the impact coefficient, per
        ``INDIA_DESIGN.md`` §5.4.

        Parameters
        ----------
        turnover : float
            Portfolio turnover expressed as a fraction of NAV.

        Returns
        -------
        float
            Stressed round-trip cost in basis points.
        """
        regulatory = self.buy_cost_bps() + self.sell_cost_bps()
        impact = self.impact_bps_per_unit * max(turnover, 0.0)
        return self.stress_multiplier * (regulatory + impact)

    # ── convenience ──────────────────────────────────────────────────

    def cost_breakdown(self) -> dict[str, float]:
        """Return a dict of every component for audit / reporting.

        Returns
        -------
        dict[str, float]
            Mapping of component name → bps value.
        """
        return {
            "brokerage_bps": self.brokerage_bps,
            "gst_on_brokerage_bps": self.gst_on_brokerage_bps,
            "exchange_txn_bps": self.exchange_txn_bps,
            "sebi_charges_bps": self.sebi_charges_bps,
            "stamp_duty_bps": self.stamp_duty_bps,
            "stt_bps": self.stt_bps,
            "buy_side_total_bps": self.buy_cost_bps(),
            "sell_side_total_bps": self.sell_cost_bps(),
            "round_trip_bps_at_1x": self.round_trip_cost_bps(turnover=1.0),
            "stressed_round_trip_bps_at_1x": self.stressed_round_trip_cost_bps(
                turnover=1.0
            ),
            "impact_bps_per_unit": self.impact_bps_per_unit,
            "stress_multiplier": self.stress_multiplier,
        }

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"IndianCostModel(buy={self.buy_cost_bps():.1f}bp, "
            f"sell={self.sell_cost_bps():.1f}bp, "
            f"rt@1x={self.round_trip_cost_bps():.1f}bp, "
            f"stressed_rt@1x={self.stressed_round_trip_cost_bps():.1f}bp)"
        )


# ─── Corwin-Schultz (2012) half-spread estimator ─────────────────────────


def corwin_schultz_spread(
    high: pd.DataFrame | pd.Series,
    low: pd.DataFrame | pd.Series,
    close: pd.DataFrame | pd.Series | None = None,
    window: int = 21,
) -> pd.DataFrame | pd.Series:
    """Corwin & Schultz (2012) rolling High/Low bid-ask spread estimator.

    For consecutive 2-day windows the estimator computes:

    .. math::

        \\beta  = E[ (\\ln H_t/L_t)^2 + (\\ln H_{t-1}/L_{t-1})^2 ]
        \\gamma = (\\ln H_{t,t-1} / L_{t,t-1})^2
        \\alpha = (\\sqrt{2\\beta} - \\sqrt{\\beta})
                  / (3 - 2\\sqrt{2})
                  - \\sqrt{\\gamma / (3 - 2\\sqrt{2})}
        S      = 2(e^{\\alpha} - 1) / (1 + e^{\\alpha})

    The returned value is the **half-spread** in basis points
    (``S / 2 * 10 000``), clipped at zero (the estimator can emit
    negative values in quiet periods).

    Parameters
    ----------
    high : DataFrame or Series
        Daily high prices.
    low : DataFrame or Series
        Daily low prices.
    close : DataFrame, Series, or None
        Daily close prices.  Currently unused but accepted for API
        consistency with the parent project's ``corwin_schultz_spread``.
    window : int
        Rolling window for the β / γ averaging (default 21 trading
        days, approximately one Indian calendar month).

    Returns
    -------
    DataFrame or Series
        Rolling half-spread estimates in basis points (same shape as
        inputs).  NaN where the rolling window is incomplete.

    Raises
    ------
    ValueError
        If *high* and *low* shapes differ.

    Notes
    -----
    The ``close`` parameter is accepted for interface compatibility
    with the parent project but is not used by the estimator.  The
    Corwin-Schultz estimator depends only on High and Low prices.
    """
    if high.shape != low.shape:
        raise ValueError(
            f"high and low must have the same shape, "
            f"got {high.shape} vs {low.shape}"
        )
    if window < 2:
        raise ValueError(f"window must be >= 2, got {window}")

    is_series = isinstance(high, pd.Series)

    # Defensive: ensure no zero or negative prices leak through.
    h = high.clip(lower=1e-12)
    l_ = low.clip(lower=1e-12)

    # (ln H_t / L_t)^2
    hl_sq = np.log(h / l_) ** 2

    # β = rolling mean of (hl²_t + hl²_{t-1})
    beta = (hl_sq + hl_sq.shift(1)).rolling(window, min_periods=window).mean()

    # 2-day high and low (max / min across t, t-1)
    if is_series:
        h2 = pd.Series(
            np.maximum(h.values, h.shift(1).values),
            index=h.index,
        )
        l2 = pd.Series(
            np.minimum(l_.values, l_.shift(1).values),
            index=l_.index,
        )
    else:
        h2 = pd.DataFrame(
            np.maximum(h.values, h.shift(1).values),
            index=h.index,
            columns=h.columns,
        )
        l2 = pd.DataFrame(
            np.minimum(l_.values, l_.shift(1).values),
            index=l_.index,
            columns=l_.columns,
        )

    # γ = rolling mean of (ln H_{t,t-1} / L_{t,t-1})^2
    gamma = (np.log(h2 / l2) ** 2).rolling(window, min_periods=window).mean()

    # k = 3 - 2√2  (≈ 0.17157)
    k = 3.0 - 2.0 * np.sqrt(2.0)

    # α
    alpha = (np.sqrt(2.0 * beta) - np.sqrt(beta)) / k - np.sqrt(gamma / k)

    # S = 2(e^α − 1) / (1 + e^α)
    spread_prop = 2.0 * (np.exp(alpha) - 1.0) / (1.0 + np.exp(alpha))

    # Half-spread in bps, clipped at zero.
    half_spread_bps = np.maximum(spread_prop, 0.0) * 0.5 * 1e4

    return half_spread_bps
