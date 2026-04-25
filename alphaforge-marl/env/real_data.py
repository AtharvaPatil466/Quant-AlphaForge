"""Local real market-data provider for the MARL trading environment.

Reads OHLCV data from the repo-level parquet store created by
`alphaforge-python/sync_market_data.py`. Training and validation never touch
the network; all remote access is isolated to the explicit sync step.
"""

from __future__ import annotations

from datetime import date, timedelta
import sys
import os
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

# Add alpha engine to path for shared data packages and PriceSeries
_ALPHA_ENGINE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "alphaforge-python",
)
if _ALPHA_ENGINE not in sys.path:
    sys.path.insert(0, _ALPHA_ENGINE)

from data.market.loader import MarketDataLoader
from data.market.universe import ALL_REAL_TICKERS, REAL_UNIVERSE
from data.synthetic import PriceSeries, safe_div


def _coerce_end_date(end_date: Optional[date | str]) -> date:
    if isinstance(end_date, str):
        return date.fromisoformat(end_date)
    return end_date or date.today()


def _history_window(
    loader: MarketDataLoader,
    tickers: List[str],
    *,
    days: int,
    end_date: Optional[date | str],
    start_date: Optional[date | str] = None,
) -> Dict[str, pd.DataFrame]:
    end_dt = _coerce_end_date(end_date)
    if start_date is None:
        start_dt = end_dt - timedelta(days=max(days * 4, 365))
    else:
        start_dt = date.fromisoformat(start_date) if isinstance(start_date, str) else start_date

    history = loader.load_history(
        tickers,
        start_date=start_dt.isoformat(),
        end_date=end_dt.isoformat(),
        align="inner",
        min_rows=max(2, min(days, 20)),
    )
    if start_date is None:
        return {
            ticker: df.tail(days).copy()
            for ticker, df in history.items()
            if len(df.tail(days)) >= max(2, min(days, 20))
        }
    return history


def fetch_real_data(
    tickers: List[str],
    days: int = 504,
    end_date: Optional[date | str] = None,
    cache_dir: Optional[str] = None,
    market_dir: Optional[str] = None,
    start_date: Optional[date | str] = None,
) -> Dict[str, pd.DataFrame]:
    """Load aligned OHLCV history from the local parquet market store."""
    del cache_dir  # retained for backward-compatible call signatures
    loader = MarketDataLoader(base_dir=market_dir)
    return _history_window(
        loader,
        [ticker.upper() for ticker in tickers],
        days=days,
        end_date=end_date,
        start_date=start_date,
    )


def ohlcv_to_price_series(
    history: Dict[str, pd.DataFrame],
) -> Dict[str, PriceSeries]:
    """Convert OHLCV DataFrames to the PriceSeries structure used by TradingEnv."""
    dataset: Dict[str, PriceSeries] = {}

    for ticker, df in history.items():
        if df.empty or "Close" not in df.columns:
            continue

        prices = df["Close"].values.astype(np.float64)
        volumes = df["Volume"].values.astype(np.float64)
        returns = np.zeros(len(prices), dtype=np.float64)
        for i in range(1, len(prices)):
            returns[i] = safe_div(prices[i] - prices[i - 1], prices[i - 1], 0.0)

        dataset[ticker] = PriceSeries(
            ticker=ticker,
            name=ticker,
            prices=np.nan_to_num(prices, nan=0.0, posinf=0.0, neginf=0.0),
            volumes=np.nan_to_num(volumes, nan=0.0, posinf=0.0, neginf=0.0),
            returns=np.nan_to_num(returns, nan=0.0, posinf=0.0, neginf=0.0),
        )

    return dataset


def generate_real_dataset(
    sector: str = "Technology",
    lookback: int = 252,
    end_date: Optional[date | str] = None,
    cache_dir: Optional[str] = None,
    market_dir: Optional[str] = None,
    start_date: Optional[date | str] = None,
) -> Dict[str, PriceSeries]:
    """Drop-in replacement for synthetic generate_dataset() using local parquet data."""
    if sector == "All":
        tickers = ALL_REAL_TICKERS
    else:
        tickers = REAL_UNIVERSE.get(sector, REAL_UNIVERSE["Technology"])

    history = fetch_real_data(
        tickers,
        days=lookback,
        end_date=end_date,
        cache_dir=cache_dir,
        market_dir=market_dir,
        start_date=start_date,
    )
    return ohlcv_to_price_series(history)


def generate_real_dataset_windowed(
    sector: str = "Technology",
    total_days: int = 756,
    window_size: int = 252,
    end_date: Optional[date | str] = None,
    cache_dir: Optional[str] = None,
    market_dir: Optional[str] = None,
    start_date: Optional[date | str] = None,
) -> List[Dict[str, PriceSeries]]:
    """Create rolling training windows from locally stored historical data."""
    if sector == "All":
        tickers = ALL_REAL_TICKERS
    else:
        tickers = REAL_UNIVERSE.get(sector, REAL_UNIVERSE["Technology"])

    history = fetch_real_data(
        tickers,
        days=total_days,
        end_date=end_date,
        cache_dir=cache_dir,
        market_dir=market_dir,
        start_date=start_date,
    )
    if not history:
        return []

    min_len = min((len(df) for df in history.values()), default=0)
    if min_len < window_size:
        dataset = ohlcv_to_price_series(history)
        return [dataset] if dataset else []

    windows: List[Dict[str, PriceSeries]] = []
    n_windows = min_len - window_size + 1
    step = max(1, n_windows // 20)

    for start in range(0, n_windows, step):
        end = start + window_size
        sliced = {
            ticker: df.iloc[start:end].copy()
            for ticker, df in history.items()
            if len(df) >= end
        }
        if sliced:
            dataset = ohlcv_to_price_series(sliced)
            if dataset:
                windows.append(dataset)

    return windows


def validate_real_data(dataset: Dict[str, PriceSeries], min_days: int = 100) -> bool:
    """Basic runtime sanity checks for a prevalidated real dataset window."""
    if len(dataset) < 3:
        return False

    for ps in dataset.values():
        if len(ps.prices) < min_days:
            return False
        if ps.prices[-1] <= 0:
            return False
        zero_vol = np.sum(ps.volumes <= 0) / max(1, len(ps.volumes))
        if zero_vol > 0.05:
            return False
    return True
