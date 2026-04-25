"""Execution: turns OrderEvents into FillEvents at the next bar's open.

Strict rule: an order generated on bar `t` fills at bar `t+1`'s open
price, plus slippage and commission. The execution handler is the only
place that can advance "decision time" to "fill time" — all callers must
respect this asymmetry to avoid look-ahead.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from backtest.event_driven.events import FillEvent, OrderEvent, OrderSide


@dataclass
class FlatSlippageModel:
    """Flat per-fill slippage in basis points. Replace with a square-root
    impact model once participation can be estimated.
    """

    slippage_bps: float = 5.0
    commission_bps: float = 1.0

    def fill(
        self, order: OrderEvent, next_bar_open: float, next_bar_timestamp: pd.Timestamp
    ) -> FillEvent:
        if next_bar_open <= 0:
            raise ValueError(
                f"fill: next_bar_open must be positive, got {next_bar_open} "
                f"for {order.ticker} at {next_bar_timestamp}"
            )
        slip_frac = self.slippage_bps / 10_000.0
        comm_frac = self.commission_bps / 10_000.0
        # Slippage moves price against you.
        if order.side is OrderSide.BUY:
            fill_price = next_bar_open * (1.0 + slip_frac)
        else:
            fill_price = next_bar_open * (1.0 - slip_frac)
        notional = fill_price * order.quantity
        commission = notional * comm_frac
        slippage_cost = abs(fill_price - next_bar_open) * order.quantity
        return FillEvent(
            timestamp=next_bar_timestamp,
            ticker=order.ticker,
            quantity=order.quantity,
            side=order.side,
            fill_price=fill_price,
            commission=commission,
            slippage_cost=slippage_cost,
        )


class ExecutionHandler:
    """Wraps a slippage model with the next-bar-open invariant.

    Callers pass an OrderEvent whose timestamp is the *decision* time;
    execute() looks up the *next* bar's open price and produces a
    FillEvent stamped with the next bar's timestamp.
    """

    def __init__(self, slippage_model: Optional[FlatSlippageModel] = None):
        self._model = slippage_model or FlatSlippageModel()

    def execute(
        self,
        order: OrderEvent,
        next_bar_timestamp: pd.Timestamp,
        next_bar_open: float,
    ) -> FillEvent:
        if next_bar_timestamp <= order.timestamp:
            raise ValueError(
                f"execute: next bar timestamp {next_bar_timestamp} must be "
                f"strictly after order timestamp {order.timestamp} — "
                f"this is the no-look-ahead invariant"
            )
        return self._model.fill(order, next_bar_open, next_bar_timestamp)


class SameBarCloseExecutionHandler:
    """Reconciliation-only execution handler: fills at the decision bar's
    close instead of the next bar's open.

    Used to reconcile against legacy vectorized backtests that compute
    `weights.shift(1) * returns` — semantically, "decide at close of day
    t, hold from close of day t to close of day t+1." When this handler
    is paired with an engine that marks NAV at the same bar's close, the
    engine reproduces those results to floating-point.

    NOT for production research. The next-bar-open contract in
    `ExecutionHandler` is the honest one — same-bar-close hides the
    close-to-open slippage that real execution actually pays.
    """

    def __init__(self, slippage_model: Optional[FlatSlippageModel] = None):
        self._model = slippage_model or FlatSlippageModel(
            slippage_bps=0.0, commission_bps=0.0
        )

    def execute(
        self,
        order: OrderEvent,
        decision_bar_timestamp: pd.Timestamp,
        decision_bar_close: float,
    ) -> FillEvent:
        if decision_bar_timestamp != order.timestamp:
            raise ValueError(
                "SameBarCloseExecutionHandler.execute: decision_bar_timestamp "
                f"{decision_bar_timestamp} must equal order.timestamp "
                f"{order.timestamp}"
            )
        return self._model.fill(order, decision_bar_close, decision_bar_timestamp)
