"""Validator tests — write hand-crafted parquet files and check the report."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from data.paths import funding_path, kline_year_path
from data.validator import BinanceDataValidator


HOUR_MS = 3_600_000


def _utc_ms(year: int, month: int, day: int, hour: int = 0) -> int:
    return int(datetime(year, month, day, hour, tzinfo=timezone.utc).timestamp() * 1000)


def _write_kline_frame(path, rows):
    cols = ["open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trade_count", "taker_buy_base", "taker_buy_quote"]
    df = pd.DataFrame(rows, columns=cols)
    df["open_time"] = df["open_time"].astype("int64")
    df["close_time"] = df["close_time"].astype("int64")
    df["trade_count"] = df["trade_count"].astype("int64")
    for c in ["open", "high", "low", "close", "volume", "quote_volume", "taker_buy_base", "taker_buy_quote"]:
        df[c] = df[c].astype("float64")
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False), path)


def test_clean_kline_panel_passes(tmp_path) -> None:
    base = tmp_path / "binance"
    start = _utc_ms(2024, 1, 1)
    rows = []
    for i in range(24):
        ot = start + i * HOUR_MS
        rows.append([ot, 100.0, 110.0, 95.0, 105.0, 1000.0, ot + HOUR_MS - 1, 100000.0, 50, 500.0, 50000.0])
    path = kline_year_path("BTCUSDT", 2024, "perp", base_dir=base)
    _write_kline_frame(path, rows)

    v = BinanceDataValidator(base_dir=base)
    report = v.validate_all(["BTCUSDT"], include_spot=False, include_funding=False)
    items = [it for it in report.items if it.stream.endswith("perp")]
    assert len(items) == 1
    item = items[0]
    assert item.clean, f"expected clean, got issues: {item.issues}"
    assert item.rows == 24


def test_kline_irregular_spacing_flagged(tmp_path) -> None:
    base = tmp_path / "binance"
    start = _utc_ms(2024, 1, 1)
    # gap: bar at t+3h, then jump straight to t+5h (missing t+4h)
    rows = []
    for hr in [0, 1, 2, 3, 5]:
        ot = start + hr * HOUR_MS
        rows.append([ot, 100.0, 110.0, 95.0, 105.0, 1000.0, ot + HOUR_MS - 1, 100000.0, 50, 500.0, 50000.0])
    path = kline_year_path("BTCUSDT", 2024, "perp", base_dir=base)
    _write_kline_frame(path, rows)

    v = BinanceDataValidator(base_dir=base)
    report = v.validate_all(["BTCUSDT"], include_spot=False, include_funding=False)
    item = [it for it in report.items if it.stream.endswith("perp")][0]
    codes = {i.code for i in item.issues}
    assert "irregular_bar_spacing" in codes


def test_kline_negative_volume_flagged(tmp_path) -> None:
    base = tmp_path / "binance"
    start = _utc_ms(2024, 1, 1)
    rows = [[start, 100.0, 110.0, 95.0, 105.0, -1.0, start + HOUR_MS - 1, 100000.0, 50, 500.0, 50000.0]]
    path = kline_year_path("BTCUSDT", 2024, "perp", base_dir=base)
    _write_kline_frame(path, rows)

    v = BinanceDataValidator(base_dir=base)
    report = v.validate_all(["BTCUSDT"], include_spot=False, include_funding=False)
    item = [it for it in report.items if it.stream.endswith("perp")][0]
    assert "negative_volume" in {i.code for i in item.issues}


def test_funding_validator_flags_extreme_rate(tmp_path) -> None:
    base = tmp_path / "binance"
    rows = pd.DataFrame(
        [
            {"funding_time": _utc_ms(2024, 1, 1), "symbol": "BTCUSDT", "funding_rate": 0.0001, "mark_price": 42000.0},
            {"funding_time": _utc_ms(2024, 1, 1, 8), "symbol": "BTCUSDT", "funding_rate": 0.10, "mark_price": 42000.0},
        ]
    )
    rows["funding_time"] = rows["funding_time"].astype("int64")
    rows["symbol"] = rows["symbol"].astype("string")
    fp = funding_path("BTCUSDT", base_dir=base)
    pq.write_table(pa.Table.from_pandas(rows, preserve_index=False), fp)

    v = BinanceDataValidator(base_dir=base)
    report = v.validate_all(["BTCUSDT"], include_spot=False, include_perp=False)
    item = [it for it in report.items if it.stream == "funding"][0]
    assert "extreme_funding_rate" in {i.code for i in item.issues}


def test_no_data_reports_cleanly(tmp_path) -> None:
    base = tmp_path / "binance"
    v = BinanceDataValidator(base_dir=base)
    report = v.validate_all(["NEVERHEARDOFUSDT"])
    for item in report.items:
        assert "no_data" in {i.code for i in item.issues}
