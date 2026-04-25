"""Point-in-time data access for the event-driven engine.

`DataHandler` owns the full historical OHLCV panel; `BarHistory` is the
sliced view it hands to a strategy at decision time `t`. Construction-
time slicing is the PIT enforcement: a `BarHistory` literally contains
no rows whose timestamp exceeds `as_of`. This makes look-ahead
architecturally impossible — a strategy cannot read what was sliced
away.

Frames must have a sorted `DatetimeIndex` and the standard OHLCV column
schema: Open, High, Low, Close, Volume.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import pandas as pd

REQUIRED_COLUMNS = ("Open", "High", "Low", "Close", "Volume")


class BarHistory:
    """A point-in-time view of historical OHLCV across tickers.

    Holds pre-sliced DataFrames keyed by ticker. The class invariant is
    that no held DataFrame contains rows past `as_of` — checked at
    construction. Strategies receive an instance of this class and can
    only see what was sliced in.
    """

    def __init__(
        self, as_of: pd.Timestamp, frames: Dict[str, pd.DataFrame]
    ):
        for ticker, df in frames.items():
            if df.empty:
                continue
            last_ts = df.index.max()
            if last_ts > as_of:
                raise ValueError(
                    f"BarHistory PIT violation: {ticker} contains data at "
                    f"{last_ts} which is past as_of {as_of}"
                )
        self._as_of = as_of
        self._frames = frames

    @property
    def as_of(self) -> pd.Timestamp:
        return self._as_of

    def tickers(self) -> List[str]:
        return list(self._frames)

    def history(self, ticker: str) -> pd.DataFrame:
        if ticker not in self._frames:
            raise KeyError(f"BarHistory: unknown ticker {ticker!r}")
        return self._frames[ticker]

    def closes(self, ticker: str) -> pd.Series:
        return self.history(ticker)["Close"]

    def latest_close(self, ticker: str) -> Optional[float]:
        s = self.closes(ticker)
        if s.empty:
            return None
        return float(s.iloc[-1])

    def returns(self, ticker: str) -> pd.Series:
        return self.closes(ticker).pct_change().dropna()


class DataHandler:
    """Owns the full panel; produces PIT views and resolves next-bar fills.

    The handler is the only object that knows what tomorrow looks like.
    It exposes that knowledge in two narrow places: `next_bar()` for the
    execution handler (next-bar-open fills) and `closes_at()` for NAV
    marking. Strategies never receive a `DataHandler` — only a
    `BarHistory` view.
    """

    def __init__(self, frames: Dict[str, pd.DataFrame]):
        if not frames:
            raise ValueError("DataHandler requires at least one ticker")
        for ticker, df in frames.items():
            if not isinstance(df.index, pd.DatetimeIndex):
                raise TypeError(
                    f"{ticker}: index must be pd.DatetimeIndex, "
                    f"got {type(df.index).__name__}"
                )
            if not df.index.is_monotonic_increasing:
                raise ValueError(f"{ticker}: index must be sorted ascending")
            missing = set(REQUIRED_COLUMNS) - set(df.columns)
            if missing:
                raise ValueError(
                    f"{ticker}: missing required columns {sorted(missing)}"
                )
        all_ts = sorted(set().union(*(df.index for df in frames.values())))
        self._timestamps = pd.DatetimeIndex(all_ts)
        self._frames = frames

    @property
    def timestamps(self) -> pd.DatetimeIndex:
        return self._timestamps

    def tickers(self) -> List[str]:
        return list(self._frames)

    def view_as_of(self, t: pd.Timestamp) -> BarHistory:
        sliced = {tk: df.loc[:t] for tk, df in self._frames.items()}
        return BarHistory(as_of=t, frames=sliced)

    def next_bar(
        self, ticker: str, t: pd.Timestamp
    ) -> Optional[Tuple[pd.Timestamp, pd.Series]]:
        """Return (timestamp, bar) of the first bar strictly after `t`."""
        df = self._frames[ticker]
        future = df.loc[df.index > t]
        if future.empty:
            return None
        return future.index[0], future.iloc[0]

    def closes_at(self, t: pd.Timestamp) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for ticker, df in self._frames.items():
            if t in df.index:
                out[ticker] = float(df.at[t, "Close"])
        return out
