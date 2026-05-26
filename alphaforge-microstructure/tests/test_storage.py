"""Round-trip tests for ParquetStore.

The parquet store is the immutable Phase 0 artifact. If a value written
by the live collector cannot be read back identically, every downstream
signal computation is silently wrong. These tests assert the round-trip
identity at the type level and the value level for both tables.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pyarrow.parquet as pq

from collector.book import BookSnapshot
from collector.binance_ws import TradeEvent
from collector.storage import ParquetStore, _book_schema, _trade_schema


# --- schema-level invariants ----------------------------------------------


def test_book_schema_field_count():
    """20 levels × 2 sides × 2 (px+sz) + 5 header fields = 85 columns."""
    s = _book_schema(levels=20)
    assert len(s) == 85


def test_book_schema_levels_parameter():
    s5 = _book_schema(levels=5)
    s20 = _book_schema(levels=20)
    assert len(s20) - len(s5) == (20 - 5) * 4


def test_trade_schema_columns():
    s = _trade_schema()
    assert s.names == [
        "exchange_ts_ns",
        "local_ts_ns",
        "agg_trade_id",
        "price",
        "size",
        "is_buyer_maker",
    ]


# --- value-level round-trip -----------------------------------------------


def _make_snapshot(ts_ns: int, last_update_id: int = 42) -> BookSnapshot:
    bids = [(99.0 - i * 0.1, 1.0 + i) for i in range(5)]
    asks = [(101.0 + i * 0.1, 1.0 + i) for i in range(5)]
    return BookSnapshot(
        exchange_ts_ns=ts_ns,
        local_ts_ns=ts_ns + 1_000,
        last_update_id=last_update_id,
        bids=bids,
        asks=asks,
    )


def _make_trade(ts_ns: int, agg_id: int = 1) -> TradeEvent:
    return TradeEvent(
        exchange_ts_ns=ts_ns,
        local_ts_ns=ts_ns + 500,
        agg_trade_id=agg_id,
        price=50_000.5,
        size=0.123,
        is_buyer_maker=False,
    )


def test_book_round_trip_preserves_top_levels(tmp_path: Path):
    store = ParquetStore(tmp_path, levels=20)
    ts = int(datetime(2026, 5, 18, 14, 30, tzinfo=timezone.utc).timestamp() * 1e9)
    snap = _make_snapshot(ts)
    store.write_book_snapshot(snap)
    store.close()

    files = list((tmp_path / "book_snapshots" / "2026-05-18").glob("*.parquet"))
    assert len(files) == 1
    assert files[0].name == "14.parquet"

    table = pq.read_table(files[0])
    df = table.to_pandas()
    assert len(df) == 1
    row = df.iloc[0]
    assert int(row["exchange_ts_ns"]) == ts
    assert int(row["last_update_id"]) == 42
    assert row["mid"] == 100.0
    assert row["spread"] == 2.0
    # Top bid level survives intact
    assert row["bid_px_1"] == 99.0
    assert row["bid_sz_1"] == 1.0
    assert row["ask_px_1"] == 101.0
    # Levels past what we wrote are NaN (we wrote 5, schema holds 20)
    import math
    assert math.isnan(row["bid_px_6"])
    assert math.isnan(row["ask_sz_20"])


def test_trade_round_trip(tmp_path: Path):
    store = ParquetStore(tmp_path)
    ts = int(datetime(2026, 5, 18, 9, 15, tzinfo=timezone.utc).timestamp() * 1e9)
    t = _make_trade(ts, agg_id=999)
    store.write_trade(t)
    store.close()

    f = tmp_path / "trades" / "2026-05-18" / "09.parquet"
    assert f.exists()
    table = pq.read_table(f)
    df = table.to_pandas()
    assert len(df) == 1
    row = df.iloc[0]
    assert int(row["agg_trade_id"]) == 999
    assert row["price"] == 50_000.5
    assert row["size"] == 0.123
    assert row["is_buyer_maker"] is False or row["is_buyer_maker"] == 0


# --- hourly bucketing -----------------------------------------------------


def test_hourly_roll_creates_separate_files(tmp_path: Path):
    store = ParquetStore(tmp_path)
    base = datetime(2026, 5, 18, 14, 59, 0, tzinfo=timezone.utc)
    ts_before = int(base.timestamp() * 1e9)
    ts_after = int((base + timedelta(minutes=2)).timestamp() * 1e9)
    store.write_book_snapshot(_make_snapshot(ts_before))
    store.write_book_snapshot(_make_snapshot(ts_after))
    store.close()

    files = sorted((tmp_path / "book_snapshots" / "2026-05-18").glob("*.parquet"))
    assert [f.name for f in files] == ["14.parquet", "15.parquet"]


def test_day_roll_creates_separate_directories(tmp_path: Path):
    store = ParquetStore(tmp_path)
    base = datetime(2026, 5, 18, 23, 59, 0, tzinfo=timezone.utc)
    ts_before = int(base.timestamp() * 1e9)
    ts_after = int((base + timedelta(minutes=2)).timestamp() * 1e9)
    store.write_trade(_make_trade(ts_before, agg_id=1))
    store.write_trade(_make_trade(ts_after, agg_id=2))
    store.close()

    dirs = sorted((tmp_path / "trades").iterdir())
    assert [d.name for d in dirs] == ["2026-05-18", "2026-05-19"]


# --- gap log --------------------------------------------------------------


def test_gap_log_appends_jsonl(tmp_path: Path):
    store = ParquetStore(tmp_path)
    store.write_gap({"reason": "seq_gap:test1", "ts_ns": 1})
    store.write_gap({"reason": "seq_gap:test2", "ts_ns": 2})
    store.close()

    lines = (tmp_path / "_gaps.jsonl").read_text().strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["reason"] == "seq_gap:test1"
    assert json.loads(lines[1])["reason"] == "seq_gap:test2"


# --- batched flush --------------------------------------------------------


def test_many_writes_then_close_flushes_all(tmp_path: Path):
    store = ParquetStore(tmp_path)
    base_ts = int(datetime(2026, 5, 18, 10, 0, tzinfo=timezone.utc).timestamp() * 1e9)
    N = 250
    for i in range(N):
        store.write_book_snapshot(_make_snapshot(base_ts + i * 100_000_000, last_update_id=i))
    store.close()

    table = pq.read_table(tmp_path / "book_snapshots" / "2026-05-18" / "10.parquet")
    assert table.num_rows == N
    # Ordering preserved
    ids = table.column("last_update_id").to_pylist()
    assert ids == list(range(N))
