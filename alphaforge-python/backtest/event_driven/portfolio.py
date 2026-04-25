"""Portfolio: position book, cash, NAV history, fill bookkeeping.

Portfolio is the source of truth for: how many shares of each ticker we
hold, how much cash, what the NAV is at any marked timestamp, and the
audit log of every fill applied. It does NOT decide what to trade — that
is the Strategy's job — and it does NOT execute orders — that is the
ExecutionHandler's job.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import pandas as pd

from backtest.event_driven.events import FillEvent


@dataclass
class NavMark:
    timestamp: pd.Timestamp
    nav: float
    cash: float
    gross_exposure: float
    net_exposure: float


class Portfolio:
    """Tracks positions, cash, and NAV through a sequence of fills + marks.

    Sign convention: positions[ticker] is signed share quantity. Positive
    is long, negative is short. cash is in account currency.
    """

    def __init__(self, initial_cash: float = 1_000_000.0):
        if initial_cash <= 0:
            raise ValueError("initial_cash must be positive")
        self._initial_cash = float(initial_cash)
        self._cash: float = float(initial_cash)
        self._positions: Dict[str, float] = {}
        self._fills: List[FillEvent] = []
        self._nav_history: List[NavMark] = []

    @property
    def cash(self) -> float:
        return self._cash

    @property
    def positions(self) -> Dict[str, float]:
        return dict(self._positions)

    @property
    def fills(self) -> List[FillEvent]:
        return list(self._fills)

    @property
    def nav_history(self) -> List[NavMark]:
        return list(self._nav_history)

    @property
    def initial_cash(self) -> float:
        return self._initial_cash

    def apply_fill(self, fill: FillEvent) -> None:
        """Apply a fill: update cash, update position, log fill."""
        self._cash += fill.cash_delta
        new_qty = self._positions.get(fill.ticker, 0.0) + fill.signed_quantity
        if abs(new_qty) < 1e-9:
            self._positions.pop(fill.ticker, None)
        else:
            self._positions[fill.ticker] = new_qty
        self._fills.append(fill)

    def mark_to_market(
        self, timestamp: pd.Timestamp, prices: Dict[str, float]
    ) -> NavMark:
        """Mark portfolio to current prices and append to NAV history.

        prices must contain a price for every ticker held. Missing prices
        raise — silent zeroing would hide stale-quote bugs.
        """
        long_value = 0.0
        short_value = 0.0
        for ticker, qty in self._positions.items():
            if ticker not in prices:
                raise KeyError(
                    f"mark_to_market: no price for held ticker {ticker!r} "
                    f"at {timestamp}"
                )
            mv = qty * prices[ticker]
            if qty > 0:
                long_value += mv
            else:
                short_value += mv
        nav = self._cash + long_value + short_value
        mark = NavMark(
            timestamp=timestamp,
            nav=nav,
            cash=self._cash,
            gross_exposure=long_value - short_value,
            net_exposure=long_value + short_value,
        )
        self._nav_history.append(mark)
        return mark

    def current_nav(self, prices: Dict[str, float]) -> float:
        """Compute NAV without recording it. Useful for sizing."""
        equity = sum(qty * prices[t] for t, qty in self._positions.items())
        return self._cash + equity

    def current_weights(self, prices: Dict[str, float]) -> Dict[str, float]:
        """Return ticker -> signed weight (fraction of NAV)."""
        nav = self.current_nav(prices)
        if nav <= 0:
            return {t: 0.0 for t in self._positions}
        return {
            t: (qty * prices[t]) / nav for t, qty in self._positions.items()
        }

    def nav_series(self) -> pd.Series:
        if not self._nav_history:
            return pd.Series(dtype=float, name="nav")
        return pd.Series(
            data=[m.nav for m in self._nav_history],
            index=pd.DatetimeIndex([m.timestamp for m in self._nav_history]),
            name="nav",
        )
