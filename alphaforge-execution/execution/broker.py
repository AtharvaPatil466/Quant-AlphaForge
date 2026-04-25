"""Abstract broker interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


@dataclass
class Order:
    ticker: str
    side: str           # "BUY" or "SELL"
    quantity: float
    order_type: str = "MARKET"
    order_id: str = ""
    status: str = "PENDING"  # PENDING, FILLED, REJECTED
    fill_price: float = 0.0
    fill_quantity: float = 0.0
    submitted_at: str = ""
    filled_at: str = ""
    slippage_bps: float = 0.0
    tx_cost: float = 0.0


@dataclass
class Position:
    ticker: str
    quantity: float
    avg_cost: float
    current_price: float = 0.0

    @property
    def market_value(self) -> float:
        return self.quantity * self.current_price

    @property
    def pnl(self) -> float:
        return self.quantity * (self.current_price - self.avg_cost)


@dataclass
class AccountState:
    nav: float
    cash: float
    positions: Dict[str, Position] = field(default_factory=dict)

    @property
    def equity(self) -> float:
        return self.cash + sum(p.market_value for p in self.positions.values())

    @property
    def gross_exposure(self) -> float:
        return sum(abs(p.market_value) for p in self.positions.values())


class Broker(ABC):
    @abstractmethod
    def submit_order(self, order: Order) -> Order:
        ...

    @abstractmethod
    def get_account(self) -> AccountState:
        ...

    @abstractmethod
    def get_positions(self) -> Dict[str, Position]:
        ...

    @abstractmethod
    def update_prices(self, prices: Dict[str, float]) -> None:
        """Update current prices for all held positions."""
        ...
