"""Honest cost model for the crypto carry study.

The equity gauntlet treated costs as a small post-hoc deduction and that was a
contributor to its failure. For the crypto carry study, costs are the central
determinant of whether the strategy survives. This module makes every cost
explicit, configurable, and auditable.

Cost components modeled:
- per-leg taker fee (perp side and spot side, separately)
- per-leg flat slippage (will be upgraded to sqrt-impact when L2 data lands)
- funding cash flows (paid by longs, received by shorts) — booked at each
  funding timestamp, not amortized into slippage
- spot short borrow cost (annualized; applies to the long-perp / short-spot leg)
- no leverage cost in v0 (no margin borrowing modeled)

The model intentionally does NOT track liquidation buffers or maintenance
margin. v0 strategies are dollar-neutral with no leverage, so this is a known
limitation but not an immediate exposure. Documented in CLAUDE.md.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CryptoCostConfig:
    """Per-leg cost assumptions. Reference: Binance VIP-0 retail tier as of 2026.

    All bps are basis points (1 bp = 0.01%). Borrow rate is annualized.
    """

    perp_taker_bps: float = 4.0
    spot_taker_bps: float = 10.0
    flat_slippage_bps_per_leg: float = 2.0
    spot_short_borrow_annual_bps: float = 30.0
    funding_periods_per_year: int = 365 * 3   # 3 events/day

    def round_trip_perp_bps(self) -> float:
        """Total cost (fee + slippage) for entering and exiting a perp position."""
        return 2 * (self.perp_taker_bps + self.flat_slippage_bps_per_leg)

    def round_trip_spot_bps(self) -> float:
        """Total cost (fee + slippage) for entering and exiting a spot position."""
        return 2 * (self.spot_taker_bps + self.flat_slippage_bps_per_leg)

    def round_trip_combined_bps(self) -> float:
        """A long-spot + short-perp (or vice versa) round-trip costs the sum."""
        return self.round_trip_perp_bps() + self.round_trip_spot_bps()


def funding_pnl_bps(
    funding_rate: float,
    *,
    perp_side: str,
) -> float:
    """Return funding PnL in bps for a given perp side at one funding event.

    Convention: funding rate `f` is what longs pay shorts. So:
    - perp_side == 'short' ⇒ receives `f` (pnl = +f)
    - perp_side == 'long'  ⇒ pays `f`     (pnl = -f)
    """
    if perp_side == "short":
        return funding_rate * 1e4
    if perp_side == "long":
        return -funding_rate * 1e4
    raise ValueError(f"perp_side must be 'long' or 'short', got {perp_side!r}")


def borrow_cost_bps_for_period(
    annual_bps: float,
    period_seconds: float,
) -> float:
    """Convert an annualized borrow rate to a per-period cost in bps.

    Applied to the spot-short leg only. Per-period because in the carry
    study the leg is held for one funding period (8h) before being rebalanced.
    """
    seconds_per_year = 365.25 * 24 * 3600
    return annual_bps * (period_seconds / seconds_per_year)


@dataclass
class TradeLegCost:
    """Cost ledger for a single trade leg."""

    fee_bps: float
    slippage_bps: float

    @property
    def total_bps(self) -> float:
        return self.fee_bps + self.slippage_bps


def make_leg_cost(market: str, config: CryptoCostConfig) -> TradeLegCost:
    """Return the entry/exit cost for one leg on a given market."""
    if market == "perp":
        return TradeLegCost(fee_bps=config.perp_taker_bps, slippage_bps=config.flat_slippage_bps_per_leg)
    if market == "spot":
        return TradeLegCost(fee_bps=config.spot_taker_bps, slippage_bps=config.flat_slippage_bps_per_leg)
    raise ValueError(f"market must be 'perp' or 'spot', got {market!r}")
