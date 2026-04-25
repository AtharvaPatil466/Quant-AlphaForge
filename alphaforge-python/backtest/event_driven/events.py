"""Event types for the event-driven backtest engine.

Events flow: MarketEvent -> Strategy emits SignalEvent -> Portfolio sizes
into OrderEvent -> ExecutionHandler fills it into FillEvent -> Portfolio
applies the fill. Each event carries a strict timestamp; the engine
processes events in non-decreasing timestamp order.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pandas as pd


class EventType(str, Enum):
    MARKET = "MARKET"
    SIGNAL = "SIGNAL"
    ORDER = "ORDER"
    FILL = "FILL"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True)
class MarketEvent:
    timestamp: pd.Timestamp
    type: EventType = EventType.MARKET


@dataclass(frozen=True)
class SignalEvent:
    timestamp: pd.Timestamp
    ticker: str
    target_weight: float
    strategy_id: str = "default"
    type: EventType = EventType.SIGNAL


@dataclass(frozen=True)
class OrderEvent:
    timestamp: pd.Timestamp
    ticker: str
    quantity: float
    side: OrderSide
    type: EventType = EventType.ORDER

    def __post_init__(self):
        if self.quantity <= 0:
            raise ValueError(f"OrderEvent.quantity must be positive, got {self.quantity}")


@dataclass(frozen=True)
class FillEvent:
    timestamp: pd.Timestamp
    ticker: str
    quantity: float
    side: OrderSide
    fill_price: float
    commission: float
    slippage_cost: float
    type: EventType = EventType.FILL

    @property
    def signed_quantity(self) -> float:
        return self.quantity if self.side is OrderSide.BUY else -self.quantity

    @property
    def cash_delta(self) -> float:
        gross = self.fill_price * self.signed_quantity
        return -gross - self.commission
