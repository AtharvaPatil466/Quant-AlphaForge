"""Loader smoke tests — write fixtures, read panels, check shapes."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from data.loader import load_funding_panel, load_klines_panel
from data.paths import funding_path, kline_year_path


HOUR_MS = 3_600_000


def _utc_ms(year: int, month: int, day: int) -> int:
    return int(datetime(year, month, day, tzinfo=timezone.utc).timestamp() * 1000)


def _write_klines(base, symbol: str, year: int, market: str, n: int):
    start = _utc_ms(year, 1, 1)
    rows = []
    for i in range(n):
        ot = start + i * HOUR_MS
        rows.append([ot, 100.0, 110.0, 95.0, 105.0, 1000.0, ot + HOUR_MS - 1, 100000.0, 50, 500.0, 50000.0])
    cols = ["open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trade_count", "taker_buy_base", "taker_buy_quote"]
    df = pd.DataFrame(rows, columns=cols)
    df["open_time"] = df["open_time"].astype("int64")
    df["close_time"] = df["close_time"].astype("int64")
    df["trade_count"] = df["trade_count"].astype("int64")
    for c in ["open", "high", "low", "close", "volume", "quote_volume", "taker_buy_base", "taker_buy_quote"]:
        df[c] = df[c].astype("float64")
    path = kline_year_path(symbol, year, market, base_dir=base)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False), path)


def test_load_klines_panel_returns_long_format(tmp_path) -> None:
    base = tmp_path / "binance"
    _write_klines(base, "BTCUSDT", 2024, "perp", 24)
    _write_klines(base, "ETHUSDT", 2024, "perp", 24)

    panel = load_klines_panel(["BTCUSDT", "ETHUSDT"], market="perp", base_dir=base)
    assert len(panel) == 48
    assert set(panel["symbol"].unique()) == {"BTCUSDT", "ETHUSDT"}
    assert "ts_utc" in panel.columns
    assert panel["ts_utc"].dt.tz is not None


def test_load_klines_panel_filters_by_date(tmp_path) -> None:
    base = tmp_path / "binance"
    _write_klines(base, "BTCUSDT", 2024, "perp", 48)  # 2 days starting 2024-01-01
    panel = load_klines_panel(
        ["BTCUSDT"], market="perp", base_dir=base,
        start_date="2024-01-02", end_date="2024-01-03",
    )
    assert len(panel) > 0
    assert panel["ts_utc"].min() >= pd.Timestamp("2024-01-02", tz="UTC")


def test_load_funding_panel(tmp_path) -> None:
    base = tmp_path / "binance"
    df = pd.DataFrame(
        [
            {"funding_time": _utc_ms(2024, 1, 1), "symbol": "BTCUSDT",
             "funding_rate": 0.0001, "mark_price": 42000.0},
            {"funding_time": _utc_ms(2024, 1, 2), "symbol": "BTCUSDT",
             "funding_rate": -0.0001, "mark_price": 42100.0},
        ]
    )
    df["funding_time"] = df["funding_time"].astype("int64")
    df["symbol"] = df["symbol"].astype("string")
    fp = funding_path("BTCUSDT", base_dir=base)
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False), fp)

    panel = load_funding_panel(["BTCUSDT"], base_dir=base)
    assert len(panel) == 2
    assert panel["ts_utc"].dt.tz is not None


def test_empty_loader_returns_empty_frame(tmp_path) -> None:
    base = tmp_path / "binance"
    panel = load_klines_panel(["NOPEUSDT"], market="perp", base_dir=base)
    assert panel.empty
    assert "symbol" in panel.columns
