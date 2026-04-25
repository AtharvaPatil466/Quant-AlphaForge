"""Strategy ABC and a reference momentum implementation.

A Strategy receives a `BarHistory` (PIT view) and returns a list of
`SignalEvent`s expressing target weights. The engine handles sizing,
order generation, fills, and accounting — the strategy is concerned only
with the alpha signal.

The contract is simple and deliberately narrow:
  on_bar(history) -> list[SignalEvent]

A SignalEvent omitted from the return list means "leave that position
alone." A SignalEvent with target_weight=0 means "close this position."
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

import numpy as np
import pandas as pd

from backtest.event_driven.data_handler import BarHistory
from backtest.event_driven.events import SignalEvent


class Strategy(ABC):
    @property
    def id(self) -> str:
        return self.__class__.__name__

    @abstractmethod
    def on_bar(self, history: BarHistory) -> List[SignalEvent]:
        """Generate signals at the bar timestamped `history.as_of`."""
        ...


class MomentumLongShort(Strategy):
    """Cross-sectional 12-1 momentum: long top quintile, short bottom.

    Score: price[t-skip] / price[t-lookback] - 1. Standard 12-month
    momentum with a 1-month skip to avoid the short-term reversal effect.
    """

    def __init__(
        self,
        lookback_days: int = 252,
        skip_days: int = 21,
        long_pct: float = 0.20,
        short_pct: float = 0.20,
        gross_leverage: float = 1.0,
    ):
        if not (0.0 < long_pct <= 1.0):
            raise ValueError("long_pct must be in (0, 1]")
        if not (0.0 < short_pct <= 1.0):
            raise ValueError("short_pct must be in (0, 1]")
        if lookback_days <= skip_days:
            raise ValueError("lookback_days must exceed skip_days")
        self.lookback_days = lookback_days
        self.skip_days = skip_days
        self.long_pct = long_pct
        self.short_pct = short_pct
        self.gross_leverage = gross_leverage

    def _score(self, history: BarHistory, ticker: str) -> Optional[float]:
        closes = history.closes(ticker)
        if len(closes) < self.lookback_days + 1:
            return None
        p_skip = float(closes.iloc[-self.skip_days - 1])
        p_lookback = float(closes.iloc[-self.lookback_days - 1])
        if p_lookback <= 0:
            return None
        return p_skip / p_lookback - 1.0

    def on_bar(self, history: BarHistory) -> List[SignalEvent]:
        scored = []
        for ticker in history.tickers():
            s = self._score(history, ticker)
            if s is not None and np.isfinite(s):
                scored.append((ticker, s))
        if not scored:
            return []
        scored.sort(key=lambda x: x[1], reverse=True)

        n = len(scored)
        n_long = max(1, int(round(n * self.long_pct)))
        n_short = max(1, int(round(n * self.short_pct)))
        long_set = scored[:n_long]
        short_set = scored[-n_short:]
        # Avoid double-counting a ticker that lands in both legs on tiny universes.
        short_set = [(t, s) for (t, s) in short_set if t not in {x[0] for x in long_set}]

        long_w = (self.gross_leverage / 2.0) / max(1, len(long_set))
        short_w = (self.gross_leverage / 2.0) / max(1, len(short_set))
        signals: List[SignalEvent] = []
        held = set()
        for ticker, _ in long_set:
            signals.append(
                SignalEvent(
                    timestamp=history.as_of,
                    ticker=ticker,
                    target_weight=+long_w,
                    strategy_id=self.id,
                )
            )
            held.add(ticker)
        for ticker, _ in short_set:
            signals.append(
                SignalEvent(
                    timestamp=history.as_of,
                    ticker=ticker,
                    target_weight=-short_w,
                    strategy_id=self.id,
                )
            )
            held.add(ticker)
        # Close anything we previously held but no longer want — strategy
        # cannot know what's held, so the engine layers this on. Here we
        # only emit explicit zero-targets for the universe minus current
        # picks so the engine treats them as flat-target.
        for ticker in history.tickers():
            if ticker not in held:
                signals.append(
                    SignalEvent(
                        timestamp=history.as_of,
                        ticker=ticker,
                        target_weight=0.0,
                        strategy_id=self.id,
                    )
                )
        return signals


class PanelStrategy(Strategy):
    """Adapter: drive the engine from a precomputed factor panel.

    Lets `factor_study.py`-style workflows (where scores are computed
    once, vectorized, before the backtest) run through the event-driven
    engine without rewriting the scoring path. At each on_bar(), reads
    the panel's row at as_of and constructs a quintile-spread signal.

    Conventions match the existing quintile_backtest:
      - Sort scores ascending
      - Bottom q_size = top quintile by ascending = SHORT leg
      - Top q_size = LONG leg
      - q_size = floor(N_valid / n_quintiles)
      - Equal-weight within each leg, gross_leverage / 2 per leg.
    """

    def __init__(
        self,
        panel: pd.DataFrame,
        n_quintiles: int = 5,
        gross_leverage: float = 1.0,
        min_universe: Optional[int] = None,
    ):
        if not isinstance(panel.index, pd.DatetimeIndex):
            raise TypeError("PanelStrategy: panel must have a DatetimeIndex")
        if not panel.index.is_monotonic_increasing:
            raise ValueError("PanelStrategy: panel index must be sorted")
        if n_quintiles < 2:
            raise ValueError("n_quintiles must be >= 2")
        self._panel = panel
        self._n_quintiles = n_quintiles
        self._gross = gross_leverage
        self._min_universe = min_universe or (2 * n_quintiles)

    def on_bar(self, history: BarHistory) -> List[SignalEvent]:
        as_of = history.as_of
        if as_of not in self._panel.index:
            return []
        row = self._panel.loc[as_of].dropna()
        if len(row) < self._min_universe:
            return []
        ranked = row.sort_values()
        q_size = len(ranked) // self._n_quintiles
        if q_size < 1:
            return []
        bot = ranked.index[:q_size]
        top = ranked.index[-q_size:]
        long_w = (self._gross / 2.0) / len(top)
        short_w = (self._gross / 2.0) / len(bot)
        signals: List[SignalEvent] = []
        held = set()
        for tk in top:
            signals.append(
                SignalEvent(timestamp=as_of, ticker=str(tk),
                             target_weight=+long_w, strategy_id="PanelStrategy")
            )
            held.add(tk)
        for tk in bot:
            signals.append(
                SignalEvent(timestamp=as_of, ticker=str(tk),
                             target_weight=-short_w, strategy_id="PanelStrategy")
            )
            held.add(tk)
        # Flat-target every other ticker the engine knows about
        for tk in history.tickers():
            if tk not in held:
                signals.append(
                    SignalEvent(timestamp=as_of, ticker=tk,
                                 target_weight=0.0, strategy_id="PanelStrategy")
                )
        return signals
