"""Strategy execution rules — operationalization of VIX_DESIGN.md §9 + §17.4.

Frozen by `research/PHASE2_STRATEGY_SPEC.md`. No parameter in this module is
search-optimized; every threshold, ratio, and boundary is a §9 pre-commit.

Three components:

1. **Position sizing** (`size_position`) — per §9.1
       max_notional = SIZING_CONSTANT * portfolio_value / VIX_level

2. **Hedge variant builder** (`build_legs`) — per §9.2 + §17.4
       Variant A: long SVXY (regime-aware exposure multiplier per §17.3).
       Variant B: long SVXY + long VXX at 10% of SVXY notional (post-2018 only).

3. **Exit-rule state machine** (`ExitDecision.evaluate`) — per §9.3
       - VIX +40% intraday hard stop (kill all open positions).
       - Signal exit when VRP < 0 (VRP trials) or VIX returns below threshold
         (mean-reversion trials).
       - 60-calendar-day time-based force-close.
       - Minimum-hold gate (§5.6 of the Phase 2 spec): signal-exit can fire
         only after `holding_period` trading days elapse from entry.

All functions are pure (no hidden state); a `Position` dataclass holds the
state that the orchestrator threads through.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum
from typing import Literal

import pandas as pd


# ---------------------------------------------------------------------------
# Frozen constants from VIX_DESIGN.md §9 + §17 + PHASE2_STRATEGY_SPEC.md
# ---------------------------------------------------------------------------

SIZING_CONSTANT: float = 0.10           # §9.1
HEDGE_NOTIONAL_RATIO: float = 0.10      # §17.4 — VXX hedge at 10% of SVXY notional
HARD_STOP_VIX_PCT: float = 0.40         # §9.3 — VIX +40% intraday kill
TIME_EXIT_CALENDAR_DAYS: int = 60       # §9.3 — force-close after 60 cal days

# §14.4 + §17.3 — SVXY exposure regimes.
SVXY_RESTRUCTURING_DATE: pd.Timestamp = pd.Timestamp("2018-02-27")
SVXY_EXPOSURE_PRE: float = -1.0         # pre-2018-02-27
SVXY_EXPOSURE_POST: float = -0.5        # post-2018-02-27
SVXY_MULT_PRE: float = 1.0              # $ short-vol per $ SVXY
SVXY_MULT_POST: float = 2.0             # need 2x SVXY $$ to get same exposure

# §17.4 — VXX hedge availability boundary.
VXX_FIRST_AVAILABLE: pd.Timestamp = pd.Timestamp("2018-01-25")

# Re-entry cooldown after a hard stop (§5.4 of Phase 2 spec).
HARD_STOP_COOLDOWN_DAYS: int = 21


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class HedgeVariant(str, Enum):
    A = "A"     # unhedged
    B = "B"     # SVXY + VXX hedge


class TradeDirection(str, Enum):
    """Strategy-level direction for the SVXY leg.

    SHORT_VOL: long SVXY (because SVXY is an inverse-VIX ETP). VRP trials.
    LONG_VOL:  short SVXY OR long VXX (depending on variant). Mean-reversion.
    """
    SHORT_VOL = "short_vol"
    LONG_VOL = "long_vol"


class ExitReason(str, Enum):
    NONE = "none"
    HARD_STOP = "hard_stop"
    SIGNAL = "signal_exit"
    TIME = "time_exit"


@dataclass
class Position:
    """Single open trade's mutable state.

    Quantities are signed: positive = long, negative = short. Notional is
    always positive (the dollar size of the short-vol exposure).
    """
    trial_name: str
    variant: HedgeVariant
    direction: TradeDirection
    entry_date: pd.Timestamp
    svxy_entry_price: float
    svxy_shares: float
    short_vol_notional: float
    vxx_entry_price: float | None = None
    vxx_shares: float = 0.0
    days_held: int = 0
    minimum_hold_days: int = 0  # from trial.holding_period


@dataclass(frozen=True)
class SizingInputs:
    portfolio_value: float
    vix_level: float
    cash_available: float


@dataclass(frozen=True)
class SizingOutput:
    max_notional: float
    short_vol_notional: float  # capped at cash
    cash_floor_binding: bool


# ---------------------------------------------------------------------------
# Position sizing (§9.1)
# ---------------------------------------------------------------------------

def size_position(inputs: SizingInputs) -> SizingOutput:
    """Substrate #7 — compute the day-`t` max short-vol notional.

    max_notional = SIZING_CONSTANT * portfolio_value / VIX_level

    Hard-capped at 99% of available cash to avoid implicit margin lending.
    Per VIX_DESIGN.md §9.1 + PHASE2_STRATEGY_SPEC.md §2.
    """
    if inputs.portfolio_value <= 0:
        return SizingOutput(0.0, 0.0, False)
    if inputs.vix_level <= 0:
        raise ValueError(f"VIX level must be positive, got {inputs.vix_level}")
    raw = SIZING_CONSTANT * inputs.portfolio_value / inputs.vix_level
    cash_cap = 0.99 * max(0.0, inputs.cash_available)
    capped = min(raw, cash_cap)
    return SizingOutput(
        max_notional=raw,
        short_vol_notional=capped,
        cash_floor_binding=(capped < raw),
    )


# Substrate-#8 baseline (long-run VIX mean). Frozen by SUBSTRATE8_DESIGN.md §2.
VIX_BASELINE_S8: float = 20.0


def size_position_baseline_vix(
    inputs: SizingInputs,
    baseline_vix: float = VIX_BASELINE_S8,
) -> SizingOutput:
    """Substrate #8 — VIX-baseline-anchored sizing per SUBSTRATE8_DESIGN.md §2.

    max_notional = SIZING_CONSTANT × portfolio_value × (baseline_vix / VIX_level)

    Preserves the substrate #7 inverse-VIX auto-deleverage shape but anchored
    to the long-run VIX mean so absolute exposure is meaningfully larger.
    At VIX=baseline, max_notional = SIZING_CONSTANT × pv (10% NAV by default).
    """
    if baseline_vix <= 0:
        raise ValueError(f"baseline_vix must be positive, got {baseline_vix}")
    if inputs.portfolio_value <= 0:
        return SizingOutput(0.0, 0.0, False)
    if inputs.vix_level <= 0:
        raise ValueError(f"VIX level must be positive, got {inputs.vix_level}")
    raw = SIZING_CONSTANT * inputs.portfolio_value * (baseline_vix / inputs.vix_level)
    cash_cap = 0.99 * max(0.0, inputs.cash_available)
    capped = min(raw, cash_cap)
    return SizingOutput(
        max_notional=raw,
        short_vol_notional=capped,
        cash_floor_binding=(capped < raw),
    )


# ---------------------------------------------------------------------------
# SVXY exposure multiplier (§17.3)
# ---------------------------------------------------------------------------

def svxy_exposure_multiplier(trade_date: pd.Timestamp) -> float:
    """Return $-of-SVXY-needed-per-$-short-vol on a given date.

    Pre-2018-02-27: 1.0  (SVXY is -1×, so $1 SVXY = $1 short-vol)
    Post-restructuring: 2.0  (SVXY is -0.5×, so $2 SVXY = $1 short-vol)
    """
    if trade_date < SVXY_RESTRUCTURING_DATE:
        return SVXY_MULT_PRE
    return SVXY_MULT_POST


def svxy_effective_exposure(trade_date: pd.Timestamp) -> float:
    """Underlying SVXY's exposure to VIX futures on a given date."""
    if trade_date < SVXY_RESTRUCTURING_DATE:
        return SVXY_EXPOSURE_PRE
    return SVXY_EXPOSURE_POST


# ---------------------------------------------------------------------------
# Hedge variant — leg construction (§9.2 + §17.4)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LegOrder:
    instrument: Literal["SVXY", "VXX"]
    shares: float        # signed: positive = long, negative = short
    notional: float      # signed dollar amount
    direction: Literal["long", "short"]


@dataclass(frozen=True)
class LegSpec:
    legs: tuple[LegOrder, ...]
    variant: HedgeVariant
    direction: TradeDirection
    short_vol_notional: float
    hedge_active: bool


class HedgeUnavailableError(RuntimeError):
    """Raised when Variant B is requested before VXX is available."""


def build_legs(
    short_vol_notional: float,
    direction: TradeDirection,
    variant: HedgeVariant,
    svxy_price: float,
    vxx_price: float | None,
    trade_date: pd.Timestamp,
) -> LegSpec:
    """Construct the leg orders for a single (variant, direction) trade.

    Per §9.2 + §17.4 + PHASE2_STRATEGY_SPEC.md §3-4. Quantities are signed.

    For SHORT_VOL:
        Variant A: long SVXY (sized to give `short_vol_notional` of effective
                   short-vol exposure, accounting for the §17.3 multiplier).
        Variant B: long SVXY + long VXX at 10% of SVXY notional.

    For LONG_VOL (mean-reversion trials):
        Variant A: long VXX (no hedge; pre-2018 not implementable —
                   raises HedgeUnavailableError).
        Variant B: long VXX + long SVXY at 10% as a partial counter-hedge.

    SVXY for SHORT_VOL: long. SVXY for LONG_VOL Variant B: long (sized at 10%
    of VXX). The Variant B counter-hedge holds in BOTH directions per the
    spec's "10% notional ratio, frozen — no search" clause.
    """
    if svxy_price <= 0:
        raise ValueError(f"SVXY price must be positive, got {svxy_price}")
    if short_vol_notional < 0:
        raise ValueError("short_vol_notional must be non-negative")

    if variant is HedgeVariant.B and trade_date < VXX_FIRST_AVAILABLE:
        raise HedgeUnavailableError(
            f"Variant B requires VXX (first available {VXX_FIRST_AVAILABLE.date()}); "
            f"trade date {trade_date.date()} is before that."
        )

    svxy_mult = svxy_exposure_multiplier(trade_date)
    legs: list[LegOrder] = []
    hedge_active = False

    if direction is TradeDirection.SHORT_VOL:
        # Long SVXY: $svxy_notional / svxy_price shares.
        svxy_notional = short_vol_notional * svxy_mult
        svxy_shares = svxy_notional / svxy_price
        legs.append(LegOrder(
            instrument="SVXY",
            shares=svxy_shares,
            notional=svxy_notional,
            direction="long",
        ))
        if variant is HedgeVariant.B:
            if vxx_price is None or vxx_price <= 0:
                raise ValueError("Variant B requires positive VXX price")
            hedge_notional = HEDGE_NOTIONAL_RATIO * svxy_notional
            vxx_shares = hedge_notional / vxx_price
            legs.append(LegOrder(
                instrument="VXX",
                shares=vxx_shares,
                notional=hedge_notional,
                direction="long",
            ))
            hedge_active = True

    elif direction is TradeDirection.LONG_VOL:
        # Mean-reversion entry: position is *long volatility*. SVXY = inverse
        # VIX, so going long-vol via SVXY means going SHORT SVXY (potentially
        # leveraged-short which is dangerous) — Phase 2 spec uses long VXX
        # instead, since VXX is available post-2018.
        if trade_date < VXX_FIRST_AVAILABLE:
            # Mean-reversion long-vol pre-2018 cannot be executed with the
            # spec's instrument set. Errors-count-as-fails per §15 rule 1.
            raise HedgeUnavailableError(
                f"LONG_VOL leg via VXX requires VXX (first available "
                f"{VXX_FIRST_AVAILABLE.date()}); trade date {trade_date.date()} "
                "is before that. Trial will record an error-fail."
            )
        if vxx_price is None or vxx_price <= 0:
            raise ValueError("LONG_VOL leg requires positive VXX price")
        # Use VXX for the primary long-vol exposure; size it to give
        # `short_vol_notional` of dollar exposure to VIX (1:1, since VXX is
        # roughly +1× near-month VIX-futures).
        vxx_notional = short_vol_notional
        vxx_shares = vxx_notional / vxx_price
        legs.append(LegOrder(
            instrument="VXX",
            shares=vxx_shares,
            notional=vxx_notional,
            direction="long",
        ))
        if variant is HedgeVariant.B:
            # Counter-hedge with long SVXY at 10% of VXX notional.
            hedge_notional = HEDGE_NOTIONAL_RATIO * vxx_notional
            svxy_hedge_shares = hedge_notional / svxy_price
            legs.append(LegOrder(
                instrument="SVXY",
                shares=svxy_hedge_shares,
                notional=hedge_notional,
                direction="long",
            ))
            hedge_active = True

    return LegSpec(
        legs=tuple(legs),
        variant=variant,
        direction=direction,
        short_vol_notional=short_vol_notional,
        hedge_active=hedge_active,
    )


# ---------------------------------------------------------------------------
# Exit-rule state machine (§9.3)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ExitContext:
    """Daily market context fed into the exit-rule machine."""
    trade_date: pd.Timestamp
    vix_close: float
    vix_high: float           # for hard-stop check
    vix_close_prev: float     # for hard-stop check
    vrp: float                # current VRP value
    ma63: float | None        # for mean-reversion exit
    sigma63: float | None     # for mean-reversion exit


@dataclass(frozen=True)
class ExitDecision:
    should_exit: bool
    reason: ExitReason


def hard_stop_fired(ctx: ExitContext) -> bool:
    """Return True if VIX_high / VIX_close_{t-1} − 1 > HARD_STOP_VIX_PCT."""
    if ctx.vix_close_prev is None or ctx.vix_close_prev <= 0:
        return False
    if ctx.vix_high is None:
        return False
    move = (ctx.vix_high - ctx.vix_close_prev) / ctx.vix_close_prev
    return move > HARD_STOP_VIX_PCT


def time_exit_fired(position: Position, ctx: ExitContext) -> bool:
    days = (ctx.trade_date.normalize() - position.entry_date.normalize()).days
    return days > TIME_EXIT_CALENDAR_DAYS


def minimum_hold_satisfied(position: Position, ctx: ExitContext) -> bool:
    return position.days_held >= position.minimum_hold_days


def signal_exit_fired(
    position: Position,
    ctx: ExitContext,
    *,
    mean_reversion_exit_threshold: float | None = None,
) -> bool:
    """Per §5.3 of the Phase 2 spec — directional, trial-specific.

    `mean_reversion_exit_threshold` is the exit-VIX level for mean-reversion
    trials (e.g., `MA63 + 1.0·σ63` or `MA63`). Ignored for VRP trials.
    """
    if position.direction is TradeDirection.SHORT_VOL:
        return ctx.vrp < 0.0
    elif position.direction is TradeDirection.LONG_VOL:
        if mean_reversion_exit_threshold is None:
            return False
        return ctx.vix_close <= mean_reversion_exit_threshold
    return False


def evaluate_exit(
    position: Position,
    ctx: ExitContext,
    *,
    mean_reversion_exit_threshold: float | None = None,
) -> ExitDecision:
    """Run all three exit rules in priority order.

    Priority:
        1. Hard stop (regardless of minimum-hold).
        2. Time-based exit (regardless of minimum-hold).
        3. Signal exit (only after minimum-hold satisfied).
    """
    if hard_stop_fired(ctx):
        return ExitDecision(True, ExitReason.HARD_STOP)
    if time_exit_fired(position, ctx):
        return ExitDecision(True, ExitReason.TIME)
    if minimum_hold_satisfied(position, ctx) and signal_exit_fired(
        position, ctx,
        mean_reversion_exit_threshold=mean_reversion_exit_threshold,
    ):
        return ExitDecision(True, ExitReason.SIGNAL)
    return ExitDecision(False, ExitReason.NONE)
