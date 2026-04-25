"""Event-driven backtest engine.

Architectural rules enforced by this package:
1. No look-ahead: data accessors and the engine refuse to expose any row
   whose timestamp is strictly after the current decision time.
2. No same-bar fills: orders generated on bar t fill at bar t+1's open.
3. Costs are charged per fill in cash, not as a flat post-hoc bps deduction.
4. Portfolio is the only authority on positions, cash, and NAV.
"""

from backtest.event_driven.core import EngineConfig, EngineRunResult, EventDrivenEngine
from backtest.event_driven.data_handler import BarHistory, DataHandler
from backtest.event_driven.events import (
    EventType,
    FillEvent,
    MarketEvent,
    OrderEvent,
    OrderSide,
    SignalEvent,
)
from backtest.event_driven.execution import (
    ExecutionHandler,
    FlatSlippageModel,
    SameBarCloseExecutionHandler,
)
from backtest.event_driven.portfolio import NavMark, Portfolio
from backtest.event_driven.strategy import MomentumLongShort, PanelStrategy, Strategy

__all__ = [
    "BarHistory",
    "DataHandler",
    "EngineConfig",
    "EngineRunResult",
    "EventDrivenEngine",
    "EventType",
    "ExecutionHandler",
    "FillEvent",
    "FlatSlippageModel",
    "MarketEvent",
    "MomentumLongShort",
    "NavMark",
    "OrderEvent",
    "OrderSide",
    "PanelStrategy",
    "Portfolio",
    "SameBarCloseExecutionHandler",
    "SignalEvent",
    "Strategy",
]
