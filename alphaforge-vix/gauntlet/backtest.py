"""Single-instrument event-driven backtest kernel for the VIX gauntlet.

Specialized to the VIX universe (SVXY + optional VXX) per `VIX_DESIGN.md` §10
and `PHASE2_STRATEGY_SPEC.md` §7. Preserves the equity event-driven engine's
three architectural guarantees:

  1. **No look-ahead.** Day-t decisions use day-t close data and earlier;
     fills execute at day-(t+1) open.
  2. **No same-bar fills.** Order generated at end of day t fills at the
     OPEN of day t+1, never on the same bar.
  3. **Per-fill cash costs.** `CostModel.apply()` is called on every fill;
     dollar cost is debited from cash, not deducted as a post-hoc bps drag.

A `Backtest` owns one trial × one hedge variant. The orchestrator runs 28
of them in Phase 3. Output:

  • `daily_nav` — pd.Series indexed by date, NAV in dollars.
  • `daily_returns` — pd.Series of daily simple returns of NAV.
  • `trades` — list of dicts with entry/exit/pnl per round-trip.
  • `metadata` — summary stats (count of trades, fraction in market, etc.).

The backtest is signal-class-aware: VRP trials use `VrpEntrySignal`,
mean-reversion trials use `MeanReversionEntrySignal`. Both implement
`should_enter(date, market_state) -> bool`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

from . import costs as costs_mod
from . import strategy as strat

# A sizing function takes a SizingInputs and returns a SizingOutput.
SizingFn = Callable[[strat.SizingInputs], strat.SizingOutput]


# ---------------------------------------------------------------------------
# Market data container
# ---------------------------------------------------------------------------

@dataclass
class MarketData:
    """Aligned daily market frame indexed by date.

    Required columns:
        vix_close, vix_high  — from CBOE
        svxy_open, svxy_close — from yfinance ETP loader
        realized_vol_L       — for the trial's lookback (e.g. realized_vol_21)

    Optional columns:
        vxx_open, vxx_close  — required for Variant B and LONG_VOL trials
        ma63, sigma63        — required for mean-reversion trials
    """
    df: pd.DataFrame

    def __post_init__(self):
        required = {"vix_close", "vix_high", "svxy_open", "svxy_close"}
        missing = required - set(self.df.columns)
        if missing:
            raise ValueError(f"MarketData missing required cols: {missing}")
        if not isinstance(self.df.index, pd.DatetimeIndex):
            raise ValueError("MarketData.df must have a DatetimeIndex")
        if not self.df.index.is_monotonic_increasing:
            raise ValueError("MarketData.df index must be monotonic increasing")


# ---------------------------------------------------------------------------
# Trial spec
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TrialSpec:
    """Frozen per-trial × per-variant backtest configuration.

    `name` is the trial name (e.g. `vrp_L63_thr4_hold5`).
    `variant` is A (unhedged) or B (hedged).
    `direction` is SHORT_VOL for VRP, LONG_VOL for mean-reversion.
    """
    name: str
    variant: strat.HedgeVariant
    direction: strat.TradeDirection
    realized_vol_lookback: int        # L (10, 21, 63) — for VRP trials
    vrp_threshold: float              # for VRP trials
    holding_period: int               # minimum-hold days
    # Mean-reversion-only:
    spike_k: float = 0.0              # 1.5 or 2.0 (·σ63)
    exit_threshold_k: float = 0.0     # 1.0 (return-to-MA+1σ) or 0.0 (return-to-MA)
    # Signal class tag — used by the engine to switch entry-rule logic.
    signal_class: str = "vrp"         # "vrp" | "mean_reversion"


# ---------------------------------------------------------------------------
# Entry-signal predicates
# ---------------------------------------------------------------------------

def vrp_entry_signal(
    trial: TrialSpec, today_row: pd.Series,
) -> bool:
    """Per §5.1 of Phase 2 spec — VRP_t >= trial.vrp_threshold."""
    rv_col = f"realized_vol_{trial.realized_vol_lookback}"
    if rv_col not in today_row.index or pd.isna(today_row[rv_col]):
        return False
    if pd.isna(today_row["vix_close"]):
        return False
    vrp = today_row["vix_close"] - today_row[rv_col]
    return vrp >= trial.vrp_threshold


def mean_reversion_entry_signal(
    trial: TrialSpec, today_row: pd.Series,
) -> bool:
    """Per §5.2 of Phase 2 spec — VIX_t > MA63_t + k·σ63_t."""
    if pd.isna(today_row.get("ma63", float("nan"))) or \
       pd.isna(today_row.get("sigma63", float("nan"))):
        return False
    threshold = today_row["ma63"] + trial.spike_k * today_row["sigma63"]
    return today_row["vix_close"] > threshold


# ---------------------------------------------------------------------------
# The backtest
# ---------------------------------------------------------------------------

@dataclass
class TradeRecord:
    trial_name: str
    variant: str
    direction: str
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    entry_svxy_price: float
    exit_svxy_price: float
    svxy_shares: float
    short_vol_notional: float
    gross_pnl: float
    net_pnl: float
    cost_dollars: float
    exit_reason: str
    days_held: int

    def to_dict(self) -> dict:
        return {
            "trial_name": self.trial_name,
            "variant": self.variant,
            "direction": self.direction,
            "entry_date": str(self.entry_date.date()),
            "exit_date": str(self.exit_date.date()),
            "entry_svxy_price": self.entry_svxy_price,
            "exit_svxy_price": self.exit_svxy_price,
            "svxy_shares": self.svxy_shares,
            "short_vol_notional": self.short_vol_notional,
            "gross_pnl": self.gross_pnl,
            "net_pnl": self.net_pnl,
            "cost_dollars": self.cost_dollars,
            "exit_reason": self.exit_reason,
            "days_held": self.days_held,
        }


@dataclass
class BacktestResult:
    trial: TrialSpec
    daily_nav: pd.Series
    daily_returns: pd.Series
    trades: list[TradeRecord] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @property
    def total_return(self) -> float:
        if self.daily_nav.empty:
            return float("nan")
        return float(self.daily_nav.iloc[-1] / self.daily_nav.iloc[0] - 1.0)

    @property
    def n_trades(self) -> int:
        return len(self.trades)


class Backtest:
    """One trial × one variant on one date window.

    Caller supplies a frozen-aligned MarketData, a TrialSpec, a CostModel,
    and an optional CarryTable. The backtest iterates days strictly forward;
    decisions at day t use only day-t close data and earlier; fills happen
    at day t+1 open.
    """

    def __init__(
        self,
        market: MarketData,
        trial: TrialSpec,
        cost_model: costs_mod.CostModel,
        initial_capital: float = 1_000_000.0,
        carry_table: costs_mod.CarryTable | None = None,
        sizing_fn: SizingFn | None = None,
    ):
        self.market = market
        self.trial = trial
        self.cost_model = cost_model
        self.initial_capital = initial_capital
        self.carry_table = carry_table or costs_mod.CarryTable()
        # Default to substrate #7 sizing (VIX_DESIGN.md §9.1). Substrate #8
        # injects `strat.size_position_baseline_vix`.
        self.sizing_fn: SizingFn = sizing_fn or strat.size_position

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _entry_signal(self, today_row: pd.Series) -> bool:
        if self.trial.signal_class == "vrp":
            return vrp_entry_signal(self.trial, today_row)
        elif self.trial.signal_class == "mean_reversion":
            return mean_reversion_entry_signal(self.trial, today_row)
        else:
            raise ValueError(f"unknown signal_class {self.trial.signal_class!r}")

    def _mr_exit_threshold(self, today_row: pd.Series) -> float | None:
        if self.trial.signal_class != "mean_reversion":
            return None
        ma = today_row.get("ma63", float("nan"))
        sigma = today_row.get("sigma63", float("nan"))
        if pd.isna(ma) or pd.isna(sigma):
            return None
        return ma + self.trial.exit_threshold_k * sigma

    def _make_exit_context(
        self, date: pd.Timestamp, today_row: pd.Series,
        prev_vix_close: float | None,
    ) -> strat.ExitContext:
        rv_col = f"realized_vol_{self.trial.realized_vol_lookback}"
        rv = today_row.get(rv_col, float("nan"))
        vrp = (today_row["vix_close"] - rv) if not pd.isna(rv) else 0.0
        return strat.ExitContext(
            trade_date=date,
            vix_close=float(today_row["vix_close"]),
            vix_high=float(today_row.get("vix_high",
                                          today_row["vix_close"])),
            vix_close_prev=(float(prev_vix_close)
                            if prev_vix_close is not None else 0.0),
            vrp=float(vrp),
            ma63=float(today_row["ma63"]) if "ma63" in today_row
                 and not pd.isna(today_row.get("ma63")) else None,
            sigma63=float(today_row["sigma63"]) if "sigma63" in today_row
                    and not pd.isna(today_row.get("sigma63")) else None,
        )

    def _position_mtm(
        self, position: strat.Position, row: pd.Series,
        vxx_close: float | None,
    ) -> float:
        """Mark-to-market $ value of a position at the day's close prices."""
        svxy_pnl = position.svxy_shares * (
            row["svxy_close"] - position.svxy_entry_price
        )
        vxx_pnl = 0.0
        if position.vxx_shares != 0.0 and position.vxx_entry_price is not None \
                and vxx_close is not None and not pd.isna(vxx_close):
            vxx_pnl = position.vxx_shares * (vxx_close - position.vxx_entry_price)
        # Position value: invested notional + unrealized PnL.
        invested = position.svxy_shares * position.svxy_entry_price
        if position.vxx_shares != 0.0 and position.vxx_entry_price is not None:
            invested += position.vxx_shares * position.vxx_entry_price
        return invested + svxy_pnl + vxx_pnl

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(
        self,
        start: pd.Timestamp | None = None,
        end: pd.Timestamp | None = None,
    ) -> BacktestResult:
        df = self.market.df
        if start is not None:
            df = df.loc[start:]
        if end is not None:
            df = df.loc[:end]
        if df.empty:
            return BacktestResult(
                trial=self.trial,
                daily_nav=pd.Series(dtype=float),
                daily_returns=pd.Series(dtype=float),
                metadata={"reason": "empty_window"},
            )

        cash = float(self.initial_capital)
        position: strat.Position | None = None
        trades: list[TradeRecord] = []
        nav_records: list[tuple[pd.Timestamp, float]] = []

        # State for end-of-day → next-open execution.
        pending_entry: bool = False
        pending_exit_reason: strat.ExitReason | None = None
        cooldown_until: pd.Timestamp | None = None
        prev_vix_close: float | None = None
        prev_date: pd.Timestamp | None = None

        dates = df.index
        n_in_market = 0

        for i, date in enumerate(dates):
            row = df.iloc[i]

            # ----- 1. EXECUTE pending orders at TODAY's open -----
            if pending_entry and position is None:
                pending_entry = False
                svxy_open = float(row["svxy_open"])
                vxx_open = (float(row["vxx_open"])
                            if "vxx_open" in row.index
                            and not pd.isna(row.get("vxx_open")) else None)
                # Compute notional from prior-close NAV.
                # NAV proxy at open: cash (no position open yet).
                sizing = self.sizing_fn(strat.SizingInputs(
                    portfolio_value=cash,
                    vix_level=float(row["vix_close"]),  # use today's VIX close
                    cash_available=cash,
                ))
                if sizing.short_vol_notional > 0 and svxy_open > 0:
                    try:
                        legs = strat.build_legs(
                            short_vol_notional=sizing.short_vol_notional,
                            direction=self.trial.direction,
                            variant=self.trial.variant,
                            svxy_price=svxy_open,
                            vxx_price=vxx_open,
                            trade_date=date,
                        )
                    except strat.HedgeUnavailableError:
                        # Per §15 hard rule 1: errors count as fails. Skip.
                        legs = None

                    if legs is not None and legs.legs:
                        # Cash spent on long legs (sign-aware).
                        svxy_leg = next(
                            (l for l in legs.legs if l.instrument == "SVXY"), None)
                        vxx_leg = next(
                            (l for l in legs.legs if l.instrument == "VXX"), None)
                        # Direction handling: SHORT_VOL goes long SVXY (cash debit);
                        # LONG_VOL goes long VXX (cash debit). Variant B adds another
                        # long leg (cash debit).
                        gross_cash_out = sum(l.notional for l in legs.legs)
                        # Fill costs.
                        total_cost_dollars = 0.0
                        for l in legs.legs:
                            fc = self.cost_model.apply(l.notional, date)
                            total_cost_dollars += fc.total_dollars
                        if gross_cash_out + total_cost_dollars <= cash:
                            cash -= gross_cash_out + total_cost_dollars
                            position = strat.Position(
                                trial_name=self.trial.name,
                                variant=self.trial.variant,
                                direction=self.trial.direction,
                                entry_date=date,
                                svxy_entry_price=(svxy_leg.notional / svxy_leg.shares
                                                  if svxy_leg else 0.0),
                                svxy_shares=(svxy_leg.shares if svxy_leg else 0.0),
                                short_vol_notional=sizing.short_vol_notional,
                                vxx_entry_price=(vxx_leg.notional / vxx_leg.shares
                                                 if vxx_leg else None),
                                vxx_shares=(vxx_leg.shares if vxx_leg else 0.0),
                                days_held=0,
                                minimum_hold_days=self.trial.holding_period,
                            )
                            # Stash cost for the round-trip.
                            position_entry_cost = total_cost_dollars
                            position_entry_cost_attr = position_entry_cost
                            # Store as attribute on the (frozen-not) Position
                            object.__setattr__(position, "_entry_cost",
                                               position_entry_cost)

            elif pending_exit_reason is not None and position is not None:
                reason = pending_exit_reason
                pending_exit_reason = None
                svxy_open = float(row["svxy_open"])
                vxx_open = (float(row["vxx_open"])
                            if "vxx_open" in row.index
                            and not pd.isna(row.get("vxx_open")) else None)
                # Close all legs at open.
                svxy_proceeds = position.svxy_shares * svxy_open
                vxx_proceeds = 0.0
                if position.vxx_shares != 0.0 and vxx_open is not None:
                    vxx_proceeds = position.vxx_shares * vxx_open
                gross_in = svxy_proceeds + vxx_proceeds
                # Exit-fill costs.
                exit_cost = 0.0
                exit_cost += self.cost_model.apply(
                    abs(svxy_proceeds), date).total_dollars
                if position.vxx_shares != 0.0:
                    exit_cost += self.cost_model.apply(
                        abs(vxx_proceeds), date).total_dollars
                cash += gross_in - exit_cost
                entry_cost = getattr(position, "_entry_cost", 0.0)
                gross_pnl = (svxy_proceeds
                             - position.svxy_shares * position.svxy_entry_price)
                if position.vxx_shares != 0.0 and position.vxx_entry_price is not None:
                    gross_pnl += (vxx_proceeds
                                  - position.vxx_shares * position.vxx_entry_price)
                net_pnl = gross_pnl - entry_cost - exit_cost
                trades.append(TradeRecord(
                    trial_name=self.trial.name,
                    variant=self.trial.variant.value,
                    direction=self.trial.direction.value,
                    entry_date=position.entry_date,
                    exit_date=date,
                    entry_svxy_price=position.svxy_entry_price,
                    exit_svxy_price=svxy_open,
                    svxy_shares=position.svxy_shares,
                    short_vol_notional=position.short_vol_notional,
                    gross_pnl=gross_pnl,
                    net_pnl=net_pnl,
                    cost_dollars=entry_cost + exit_cost,
                    exit_reason=reason.value,
                    days_held=position.days_held,
                ))
                if reason is strat.ExitReason.HARD_STOP:
                    cooldown_until = date + pd.Timedelta(
                        days=strat.HARD_STOP_COOLDOWN_DAYS
                    )
                position = None

            # ----- 2. END-OF-DAY MTM + carry -----
            vxx_close = (float(row["vxx_close"])
                         if "vxx_close" in row.index
                         and not pd.isna(row.get("vxx_close")) else None)
            position_value = 0.0
            if position is not None:
                position_value = self._position_mtm(position, row, vxx_close)
                position.days_held += 1
                n_in_market += 1
            # Daily carry credit on cash.
            if prev_date is not None:
                days_elapsed = (date - prev_date).days
                if days_elapsed > 0:
                    carry = self.carry_table.daily_carry_dollars(
                        cash, date, days=days_elapsed
                    )
                    cash += carry
            nav = cash + position_value
            nav_records.append((date, nav))

            # ----- 3. END-OF-DAY DECISION (using today's close data) -----
            if position is not None:
                exit_ctx = self._make_exit_context(date, row, prev_vix_close)
                decision = strat.evaluate_exit(
                    position, exit_ctx,
                    mean_reversion_exit_threshold=self._mr_exit_threshold(row),
                )
                if decision.should_exit:
                    pending_exit_reason = decision.reason
            elif (cooldown_until is None or date > cooldown_until) and not pending_entry:
                if self._entry_signal(row):
                    pending_entry = True

            prev_vix_close = float(row["vix_close"]) if not pd.isna(row["vix_close"]) else prev_vix_close
            prev_date = date

        nav_series = pd.Series(
            data=[v for _, v in nav_records],
            index=pd.DatetimeIndex([d for d, _ in nav_records], name="date"),
            name="nav",
        )
        returns = nav_series.pct_change().dropna()
        returns.name = "ret"

        metadata = {
            "initial_capital": self.initial_capital,
            "final_nav": float(nav_series.iloc[-1]) if not nav_series.empty else 0.0,
            "n_trades": len(trades),
            "n_days": len(nav_series),
            "fraction_in_market": (n_in_market / len(nav_series)
                                    if len(nav_series) else 0.0),
            "start_date": str(nav_series.index.min().date()) if not nav_series.empty else None,
            "end_date": str(nav_series.index.max().date()) if not nav_series.empty else None,
        }
        return BacktestResult(
            trial=self.trial,
            daily_nav=nav_series,
            daily_returns=returns,
            trades=trades,
            metadata=metadata,
        )
