"""
Position management, stop-loss, and transaction cost handling.

Tracks individual positions and portfolio-level state for the backtest engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

from data.synthetic import safe_div, sanitize_number, clamp


@dataclass
class Position:
    """A single position in one ticker."""
    ticker: str
    direction: float  # +1.0 for long, -1.0 for short
    entry_price: float
    entry_day: int
    size: float = 1.0  # fraction of capital allocated

    def pnl(self, current_price: float) -> float:
        """Unrealized P&L as a return fraction."""
        ret = safe_div(current_price - self.entry_price, self.entry_price, 0.0)
        return self.direction * ret * self.size

    def is_stopped_out(self, current_price: float, stop_loss: float) -> bool:
        """True if the position has hit the stop-loss threshold."""
        return self.pnl(current_price) < -stop_loss


@dataclass
class Portfolio:
    """Portfolio state for the backtest simulation."""
    nav: float = 100.0
    peak_nav: float = 100.0
    positions: List[Position] = field(default_factory=list)
    cash: float = 100.0
    tx_cost_bps: int = 5

    @property
    def tx_cost(self) -> float:
        return self.tx_cost_bps / 10000

    def open_position(
        self, ticker: str, direction: float, price: float, day: int, size: float = 1.0
    ) -> None:
        """Open a new position, deducting transaction cost."""
        self.positions.append(Position(
            ticker=ticker, direction=direction,
            entry_price=price, entry_day=day, size=size,
        ))
        self.cash -= self.tx_cost * size  # deduct entry cost

    def close_position(self, position: Position, current_price: float) -> float:
        """Close a position and return the realized P&L."""
        pnl = position.pnl(current_price)
        self.cash -= self.tx_cost * position.size  # deduct exit cost
        if position in self.positions:
            self.positions.remove(position)
        return pnl

    def close_all(self, prices: Dict[str, float]) -> float:
        """Close all positions. Returns total realized P&L."""
        total_pnl = 0.0
        for pos in list(self.positions):
            price = prices.get(pos.ticker, pos.entry_price)
            total_pnl += self.close_position(pos, price)
        return total_pnl

    def check_stop_losses(
        self, prices: Dict[str, float], stop_loss: float
    ) -> List[Position]:
        """Check and close any positions that hit stop-loss. Returns closed positions."""
        closed = []
        for pos in list(self.positions):
            price = prices.get(pos.ticker, pos.entry_price)
            if pos.is_stopped_out(price, stop_loss):
                self.close_position(pos, price)
                closed.append(pos)
        return closed

    def daily_pnl(self, prices: Dict[str, float]) -> float:
        """Compute total unrealized + cash return for the day."""
        total = 0.0
        for pos in self.positions:
            price = prices.get(pos.ticker, pos.entry_price)
            total += pos.pnl(price)
        return total

    def update_nav(self, daily_return: float) -> None:
        """Update NAV from daily portfolio return."""
        self.nav = max(0.01, self.nav * (1 + clamp(daily_return, -0.20, 0.20)))
        if self.nav > self.peak_nav:
            self.peak_nav = self.nav

    def current_drawdown(self) -> float:
        """Current drawdown from peak."""
        return safe_div(self.peak_nav - self.nav, self.peak_nav, 0.0)
