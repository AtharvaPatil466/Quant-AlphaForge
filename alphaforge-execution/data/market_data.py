"""Load validated OHLCV market data from the local parquet store."""

from __future__ import annotations

from datetime import date, timedelta
import os
import sys
from typing import Dict, List, Optional

import pandas as pd

_ALPHA_ENGINE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "alphaforge-python",
)
if _ALPHA_ENGINE not in sys.path:
    sys.path.insert(0, _ALPHA_ENGINE)

from real_market_store import MarketDataLoader


def _window_start(end_date: date, days: int) -> date:
    return end_date - timedelta(days=max(days * 4, 365))


def fetch_history(
    tickers: List[str],
    days: int = 252,
    end: Optional[date] = None,
    market_dir: Optional[str] = None,
) -> Dict[str, pd.DataFrame]:
    """Load daily OHLCV history for each ticker from local parquet files."""
    end_date = end or date.today()
    loader = MarketDataLoader(base_dir=market_dir)
    history = loader.load_history(
        tickers,
        start_date=_window_start(end_date, days).isoformat(),
        end_date=end_date.isoformat(),
        align="inner",
        min_rows=max(2, min(days, 20)),
    )
    return {
        ticker: df.tail(days).copy()
        for ticker, df in history.items()
        if len(df.tail(days)) >= max(2, min(days, 20))
    }


def fetch_latest(
    tickers: List[str],
    end: Optional[date] = None,
    market_dir: Optional[str] = None,
) -> Dict[str, pd.Series]:
    """Load the most recent validated trading day's OHLCV for each ticker."""
    loader = MarketDataLoader(base_dir=market_dir)
    return loader.load_latest(tickers, end_date=(end or date.today()).isoformat())


def prices_array(history: Dict[str, pd.DataFrame], ticker: str) -> pd.Series:
    """Extract closing prices as a Series for a given ticker."""
    if ticker not in history:
        return pd.Series(dtype=float)
    return history[ticker]["Close"]
