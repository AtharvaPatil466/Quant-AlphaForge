"""Adapters for loading local real-market history into AlphaForge datasets."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, Iterable, List

import numpy as np
import pandas as pd

from data.market.loader import MarketDataLoader
from data.market.universe import ALL_REAL_TICKERS, REAL_UNIVERSE
from data.synthetic import PriceSeries, compute_returns


def tickers_for_sector(sector: str) -> List[str]:
    if sector == "All":
        return list(ALL_REAL_TICKERS)
    return list(REAL_UNIVERSE.get(sector, REAL_UNIVERSE["Technology"]))


def load_real_history(
    sector: str = "All",
    lookback: int = 252,
    *,
    end_date: date | str | None = None,
    start_date: date | str | None = None,
    market_dir: str | None = None,
    min_rows: int | None = None,
    align: str = "inner",
) -> Dict[str, pd.DataFrame]:
    loader = MarketDataLoader(base_dir=market_dir)
    tickers = tickers_for_sector(sector)
    if isinstance(end_date, str):
        end = date.fromisoformat(end_date)
    else:
        end = end_date or date.today()
    if isinstance(start_date, str):
        start = date.fromisoformat(start_date)
    elif start_date is None:
        start = end - timedelta(days=max(lookback * 4, 365))
    else:
        start = start_date

    history = loader.load_history(
        tickers,
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        align=align,
        min_rows=min_rows or max(2, min(lookback, 20)),
    )
    if start_date is None:
        return {
            ticker: df.tail(lookback).copy()
            for ticker, df in history.items()
            if len(df.tail(lookback)) >= (min_rows or max(2, min(lookback, 20)))
        }
    return history


def history_to_dataset(history: Dict[str, pd.DataFrame]) -> Dict[str, PriceSeries]:
    dataset: Dict[str, PriceSeries] = {}
    for ticker, df in history.items():
        if df.empty or "Close" not in df.columns:
            continue
        prices = df["Close"].to_numpy(dtype=np.float64)
        volumes = df["Volume"].to_numpy(dtype=np.float64)
        dataset[ticker] = PriceSeries(
            ticker=ticker,
            name=ticker,
            prices=np.nan_to_num(prices, nan=0.0, posinf=0.0, neginf=0.0),
            volumes=np.nan_to_num(volumes, nan=0.0, posinf=0.0, neginf=0.0),
            returns=compute_returns(np.nan_to_num(prices, nan=0.0, posinf=0.0, neginf=0.0)),
        )
    return dataset


def load_real_dataset(
    sector: str = "All",
    lookback: int = 252,
    *,
    end_date: date | str | None = None,
    start_date: date | str | None = None,
    market_dir: str | None = None,
    min_rows: int | None = None,
    align: str = "inner",
) -> Dict[str, PriceSeries]:
    history = load_real_history(
        sector=sector,
        lookback=lookback,
        end_date=end_date,
        start_date=start_date,
        market_dir=market_dir,
        min_rows=min_rows,
        align=align,
    )
    return history_to_dataset(history)
