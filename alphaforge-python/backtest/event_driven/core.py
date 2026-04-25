"""Event-driven engine: wires DataHandler + Strategy + Execution + Portfolio.

Loop semantics (the whole reason the package exists):

  for each timestamp t in [start, end]:
      1. If this is a rebalance bar:
           a. Hand the strategy a PIT view ending at t.
           b. Convert returned target weights into orders sized against
              the *current* (close-at-t) prices and the current NAV.
           c. For each order, look up the *next* bar's open and submit
              to the execution handler. Apply the resulting fill to the
              portfolio. The fill timestamp is the next bar's, never t.
      2. Mark portfolio to t's close prices.

Rebalance cadence is `rebalance_freq` bars. A value of 1 means every
bar. The first decision is always made on the first eligible bar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd

from backtest.event_driven.data_handler import DataHandler
from backtest.event_driven.events import OrderEvent, OrderSide, SignalEvent
from backtest.event_driven.execution import (
    ExecutionHandler,
    SameBarCloseExecutionHandler,
)
from backtest.event_driven.portfolio import Portfolio
from backtest.event_driven.strategy import Strategy


@dataclass
class EngineConfig:
    rebalance_freq: int = 21
    initial_cash: float = 1_000_000.0
    warmup_bars: int = 0
    min_order_notional: float = 100.0


@dataclass
class EngineRunResult:
    portfolio: Portfolio
    timestamps: pd.DatetimeIndex
    rebalance_dates: List[pd.Timestamp] = field(default_factory=list)
    skipped_orders: int = 0


class EventDrivenEngine:
    def __init__(
        self,
        data_handler: DataHandler,
        strategy: Strategy,
        execution_handler,
        portfolio: Optional[Portfolio] = None,
        config: Optional[EngineConfig] = None,
    ):
        self.data_handler = data_handler
        self.strategy = strategy
        self.execution_handler = execution_handler
        self.config = config or EngineConfig()
        self.portfolio = portfolio or Portfolio(self.config.initial_cash)
        self._same_bar_close = isinstance(
            execution_handler, SameBarCloseExecutionHandler
        )

    def _size_orders(
        self,
        signals: List[SignalEvent],
        prices_at_decision: Dict[str, float],
    ) -> List[OrderEvent]:
        nav = self.portfolio.current_nav(prices_at_decision)
        if nav <= 0:
            return []
        positions = self.portfolio.positions
        orders: List[OrderEvent] = []
        for sig in signals:
            if sig.ticker not in prices_at_decision:
                continue
            px = prices_at_decision[sig.ticker]
            if px <= 0:
                continue
            target_shares = (sig.target_weight * nav) / px
            current_shares = positions.get(sig.ticker, 0.0)
            delta = target_shares - current_shares
            if abs(delta) < 1e-9:
                continue
            notional = abs(delta) * px
            if notional < self.config.min_order_notional:
                continue
            side = OrderSide.BUY if delta > 0 else OrderSide.SELL
            orders.append(
                OrderEvent(
                    timestamp=sig.timestamp,
                    ticker=sig.ticker,
                    quantity=abs(delta),
                    side=side,
                )
            )
        return orders

    def _execute_orders(self, orders: List[OrderEvent], decision_t: pd.Timestamp) -> int:
        skipped = 0
        for order in orders:
            if self._same_bar_close:
                close_px = self.data_handler.closes_at(decision_t).get(order.ticker)
                if close_px is None or close_px <= 0:
                    skipped += 1
                    continue
                fill = self.execution_handler.execute(order, decision_t, close_px)
            else:
                nb = self.data_handler.next_bar(order.ticker, decision_t)
                if nb is None:
                    skipped += 1
                    continue
                next_ts, next_bar = nb
                open_px = float(next_bar["Open"])
                if open_px <= 0:
                    skipped += 1
                    continue
                fill = self.execution_handler.execute(order, next_ts, open_px)
            self.portfolio.apply_fill(fill)
        return skipped

    def run(
        self,
        start: Optional[pd.Timestamp] = None,
        end: Optional[pd.Timestamp] = None,
    ) -> EngineRunResult:
        timestamps = self.data_handler.timestamps
        if start is not None:
            timestamps = timestamps[timestamps >= start]
        if end is not None:
            timestamps = timestamps[timestamps <= end]
        if self.config.warmup_bars > 0:
            timestamps = timestamps[self.config.warmup_bars :]
        if len(timestamps) == 0:
            raise ValueError("EventDrivenEngine.run: empty timestamp range")

        rebal = self.config.rebalance_freq
        rebalance_dates: List[pd.Timestamp] = []
        skipped_total = 0

        for i, t in enumerate(timestamps):
            # 1. Mark FIRST with whatever positions we entered the bar with.
            #    This makes the rebalance-day return attribute to OLD weights,
            #    matching `weights.shift(1) * rets` semantics in vectorized
            #    backtests. If we rebalanced first, NEW weights would
            #    incorrectly earn this bar's close-to-close move.
            closes = self.data_handler.closes_at(t)
            held = set(self.portfolio.positions)
            missing = held - set(closes)
            if not missing:
                self.portfolio.mark_to_market(
                    t, {tk: closes[tk] for tk in held} if held else {}
                )
            # If a held ticker is missing a close on bar t, we skip the mark
            # rather than carry forward (which would mask stale-quote bugs).

            # 2. Then rebalance.
            if i % rebal == 0:
                view = self.data_handler.view_as_of(t)
                signals = self.strategy.on_bar(view)
                if signals:
                    prices = self.data_handler.closes_at(t)
                    orders = self._size_orders(signals, prices)
                    skipped_total += self._execute_orders(orders, t)
                rebalance_dates.append(t)

        return EngineRunResult(
            portfolio=self.portfolio,
            timestamps=timestamps,
            rebalance_dates=rebalance_dates,
            skipped_orders=skipped_total,
        )
