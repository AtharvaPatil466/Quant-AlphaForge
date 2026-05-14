"""Aligned-panel readers over the local Binance parquet store.

Returns long-format DataFrames keyed by (symbol, timestamp_utc). Downstream
research code can pivot to wide as needed; long is more memory-friendly for
the v0 universe sizes and cheaper to filter by date range.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd
import pyarrow.parquet as pq

from .paths import (
    BinancePaths,
    default_paths,
    funding_path,
    oi_year_path,
)


def load_klines_panel(
    symbols: Iterable[str],
    market: str = "perp",
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    base_dir: str | Path | None = None,
) -> pd.DataFrame:
    """Return a long-format kline panel for the given symbols and market.

    Columns: symbol, open_time, open, high, low, close, volume, close_time,
    quote_volume, trade_count, taker_buy_base, taker_buy_quote, ts_utc.
    """
    paths = default_paths(base_dir)
    root = paths.spot_klines_root if market == "spot" else paths.perp_klines_root
    start_ms, end_ms = _parse_range_ms(start_date, end_date)

    frames: list[pd.DataFrame] = []
    for symbol in symbols:
        symbol = symbol.upper()
        symbol_dir = root / symbol
        if not symbol_dir.exists():
            continue
        for parquet in sorted(symbol_dir.glob("*.parquet")):
            frame = pq.read_table(parquet).to_pandas()
            frame.insert(0, "symbol", symbol)
            if start_ms is not None:
                frame = frame[frame["open_time"] >= start_ms]
            if end_ms is not None:
                frame = frame[frame["open_time"] <= end_ms]
            if not frame.empty:
                frames.append(frame)

    if not frames:
        return pd.DataFrame(
            columns=["symbol", "open_time", "open", "high", "low", "close", "volume", "ts_utc"]
        )

    panel = pd.concat(frames, ignore_index=True)
    panel = panel.sort_values(["symbol", "open_time"]).reset_index(drop=True)
    panel["ts_utc"] = pd.to_datetime(panel["open_time"], unit="ms", utc=True)
    return panel


def load_funding_panel(
    symbols: Iterable[str],
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    base_dir: str | Path | None = None,
) -> pd.DataFrame:
    """Return a long-format funding panel.

    Columns: symbol, funding_time, funding_rate, mark_price, ts_utc.
    """
    start_ms, end_ms = _parse_range_ms(start_date, end_date)
    frames: list[pd.DataFrame] = []
    for symbol in symbols:
        symbol = symbol.upper()
        path = funding_path(symbol, base_dir=base_dir)
        if not path.exists():
            continue
        frame = pq.read_table(path).to_pandas()
        if start_ms is not None:
            frame = frame[frame["funding_time"] >= start_ms]
        if end_ms is not None:
            frame = frame[frame["funding_time"] <= end_ms]
        if not frame.empty:
            frames.append(frame)

    if not frames:
        return pd.DataFrame(columns=["symbol", "funding_time", "funding_rate", "mark_price", "ts_utc"])

    panel = pd.concat(frames, ignore_index=True)
    panel = panel.sort_values(["symbol", "funding_time"]).reset_index(drop=True)
    panel["ts_utc"] = pd.to_datetime(panel["funding_time"], unit="ms", utc=True)
    return panel


def load_open_interest_panel(
    symbols: Iterable[str],
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    base_dir: str | Path | None = None,
) -> pd.DataFrame:
    """Return a long-format open-interest panel."""
    paths: BinancePaths = default_paths(base_dir)
    start_ms, end_ms = _parse_range_ms(start_date, end_date)
    frames: list[pd.DataFrame] = []
    for symbol in symbols:
        symbol = symbol.upper()
        symbol_dir = paths.open_interest_root / symbol
        if not symbol_dir.exists():
            continue
        for parquet in sorted(symbol_dir.glob("*.parquet")):
            frame = pq.read_table(parquet).to_pandas()
            frame.insert(0, "symbol", symbol)
            if start_ms is not None:
                frame = frame[frame["timestamp"] >= start_ms]
            if end_ms is not None:
                frame = frame[frame["timestamp"] <= end_ms]
            if not frame.empty:
                frames.append(frame)
    if not frames:
        return pd.DataFrame(
            columns=["symbol", "timestamp", "sum_open_interest", "sum_open_interest_value", "ts_utc"]
        )

    panel = pd.concat(frames, ignore_index=True)
    panel = panel.sort_values(["symbol", "timestamp"]).reset_index(drop=True)
    panel["ts_utc"] = pd.to_datetime(panel["timestamp"], unit="ms", utc=True)
    return panel


def _parse_range_ms(start_date: str | None, end_date: str | None) -> tuple[int | None, int | None]:
    def to_ms(s: str | None) -> int | None:
        if s is None:
            return None
        return int(pd.Timestamp(s, tz="UTC").timestamp() * 1000)

    return to_ms(start_date), to_ms(end_date)
