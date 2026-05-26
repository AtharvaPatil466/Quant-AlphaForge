"""Unit tests for the three Phase-0 validation modules.

These exercise the pure logic — diff computation, temporal-ordering
search, gap thresholding — against synthetic parquet fixtures so the
validators have test coverage independent of any live data.
"""

from __future__ import annotations

from datetime import date as date_t, datetime, timezone
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from collector.storage import _book_schema, _trade_schema


# --- helpers --------------------------------------------------------------


def _write_book(path: Path, rows: list[dict], levels: int = 20) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    schema = _book_schema(levels)
    # Fill missing level columns with NaN
    filled = []
    for r in rows:
        row = dict(r)
        for i in range(1, levels + 1):
            row.setdefault(f"bid_px_{i}", float("nan"))
            row.setdefault(f"bid_sz_{i}", float("nan"))
            row.setdefault(f"ask_px_{i}", float("nan"))
            row.setdefault(f"ask_sz_{i}", float("nan"))
        filled.append(row)
    pq.write_table(pa.Table.from_pylist(filled, schema=schema), path)


def _write_trades(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=_trade_schema()), path)


# --- book_snapshot_check._diff_books -------------------------------------


def test_diff_books_identical_returns_empty():
    from validation.book_snapshot_check import _diff_books

    local = {
        "bid_px_1": 100.0, "bid_sz_1": 1.0,
        "ask_px_1": 101.0, "ask_sz_1": 2.0,
    }
    rest = {"bids": [["100.0", "1.0"]], "asks": [["101.0", "2.0"]]}
    diffs = _diff_books(local, rest, levels=1)
    assert diffs == []


def test_diff_books_flags_price_mismatch():
    from validation.book_snapshot_check import _diff_books

    local = {
        "bid_px_1": 100.0, "bid_sz_1": 1.0,
        "ask_px_1": 101.0, "ask_sz_1": 2.0,
    }
    rest = {"bids": [["99.5", "1.0"]], "asks": [["101.0", "2.0"]]}
    diffs = _diff_books(local, rest, levels=1)
    assert len(diffs) == 1
    assert "bid[1]" in diffs[0]


def test_diff_books_flags_size_mismatch():
    from validation.book_snapshot_check import _diff_books

    local = {
        "bid_px_1": 100.0, "bid_sz_1": 1.0,
        "ask_px_1": 101.0, "ask_sz_1": 2.5,
    }
    rest = {"bids": [["100.0", "1.0"]], "asks": [["101.0", "2.0"]]}
    diffs = _diff_books(local, rest, levels=1)
    assert len(diffs) == 1
    assert "ask[1]" in diffs[0]


def test_diff_books_handles_short_rest_book():
    """REST returns fewer levels than expected — treated as NaN diff."""
    from validation.book_snapshot_check import _diff_books

    local = {
        "bid_px_1": 100.0, "bid_sz_1": 1.0,
        "bid_px_2": 99.0,  "bid_sz_2": 1.0,
        "ask_px_1": 101.0, "ask_sz_1": 1.0,
        "ask_px_2": 102.0, "ask_sz_2": 1.0,
    }
    rest = {"bids": [["100.0", "1.0"]], "asks": [["101.0", "1.0"]]}
    diffs = _diff_books(local, rest, levels=2)
    # level 2 missing in REST → diff
    assert any("bid[2]" in d for d in diffs)
    assert any("ask[2]" in d for d in diffs)


# --- temporal_alignment ---------------------------------------------------


def test_temporal_alignment_all_in_window(tmp_path, monkeypatch):
    """Every trade lies between two book snapshots → 0 violations."""
    import sys
    from validation import temporal_alignment as ta

    day = date_t(2026, 5, 18)
    base_ns = int(datetime(2026, 5, 18, 0, 0, tzinfo=timezone.utc).timestamp() * 1e9)

    # Book snapshots every second for 10 seconds
    book_rows = [
        {"exchange_ts_ns": base_ns + i * 1_000_000_000,
         "local_ts_ns":    base_ns + i * 1_000_000_000,
         "last_update_id": i, "mid": 100.0, "spread": 1.0}
        for i in range(10)
    ]
    _write_book(tmp_path / "book_snapshots" / "2026-05-18" / "00.parquet", book_rows)

    # Trades at +0.5s, +1.5s, +5.5s
    trade_rows = [
        {"exchange_ts_ns": base_ns + 500_000_000,
         "local_ts_ns": base_ns + 500_000_000,
         "agg_trade_id": 1, "price": 100.0, "size": 0.1, "is_buyer_maker": False},
        {"exchange_ts_ns": base_ns + 1_500_000_000,
         "local_ts_ns": base_ns + 1_500_000_000,
         "agg_trade_id": 2, "price": 100.1, "size": 0.2, "is_buyer_maker": True},
        {"exchange_ts_ns": base_ns + 5_500_000_000,
         "local_ts_ns": base_ns + 5_500_000_000,
         "agg_trade_id": 3, "price": 100.2, "size": 0.3, "is_buyer_maker": False},
    ]
    _write_trades(tmp_path / "trades" / "2026-05-18" / "00.parquet", trade_rows)

    monkeypatch.setattr(sys, "argv", [
        "temporal_alignment",
        "--data-root", str(tmp_path),
        "--date", day.isoformat(),
    ])
    rc = ta.main()
    assert rc == 0


def test_temporal_alignment_detects_pre_book_trade(tmp_path, monkeypatch, capsys):
    """A trade with timestamp earlier than any book → counted as violation."""
    import sys
    from validation import temporal_alignment as ta

    day = date_t(2026, 5, 18)
    base_ns = int(datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc).timestamp() * 1e9)

    book_rows = [
        {"exchange_ts_ns": base_ns + i * 1_000_000_000,
         "local_ts_ns":    base_ns + i * 1_000_000_000,
         "last_update_id": i, "mid": 100.0, "spread": 1.0}
        for i in range(5)
    ]
    _write_book(tmp_path / "book_snapshots" / "2026-05-18" / "12.parquet", book_rows)

    # A single trade BEFORE every book snapshot
    trade_rows = [
        {"exchange_ts_ns": base_ns - 5_000_000_000,
         "local_ts_ns":    base_ns - 5_000_000_000,
         "agg_trade_id": 1, "price": 100.0, "size": 0.1, "is_buyer_maker": False},
    ]
    _write_trades(tmp_path / "trades" / "2026-05-18" / "11.parquet", trade_rows)

    monkeypatch.setattr(sys, "argv", [
        "temporal_alignment",
        "--data-root", str(tmp_path),
        "--date", day.isoformat(),
        "--max-violation-rate", "0.0",
    ])
    rc = ta.main()
    assert rc == 1  # violation rate > threshold


# --- gap_detector ---------------------------------------------------------


def test_gap_detector_no_gaps(tmp_path, monkeypatch):
    """Dense snapshots (every 100ms) → 0% gap fraction."""
    import sys
    from validation import gap_detector as gd

    base_ns = int(datetime(2026, 5, 18, 0, 0, tzinfo=timezone.utc).timestamp() * 1e9)
    rows = [
        {"exchange_ts_ns": base_ns + i * 100_000_000,
         "local_ts_ns":    base_ns + i * 100_000_000,
         "last_update_id": i, "mid": 100.0, "spread": 1.0}
        for i in range(36000)  # 1 hour at 100ms cadence
    ]
    _write_book(tmp_path / "book_snapshots" / "2026-05-18" / "00.parquet", rows)

    monkeypatch.setattr(sys, "argv", [
        "gap_detector",
        "--data-root", str(tmp_path),
        "--start", "2026-05-18", "--end", "2026-05-18",
    ])
    rc = gd.main()
    assert rc == 0


def test_gap_detector_finds_injected_gap(tmp_path, monkeypatch):
    """Inject a 5-second gap → reported as gap, fraction > 0."""
    import sys
    from validation import gap_detector as gd

    base_ns = int(datetime(2026, 5, 18, 0, 0, tzinfo=timezone.utc).timestamp() * 1e9)
    # 100 snapshots at 100ms, then 5s gap, then 100 more
    timestamps = [base_ns + i * 100_000_000 for i in range(100)]
    after_gap = timestamps[-1] + 5_000_000_000
    timestamps += [after_gap + i * 100_000_000 for i in range(100)]
    rows = [
        {"exchange_ts_ns": t, "local_ts_ns": t,
         "last_update_id": i, "mid": 100.0, "spread": 1.0}
        for i, t in enumerate(timestamps)
    ]
    _write_book(tmp_path / "book_snapshots" / "2026-05-18" / "00.parquet", rows)

    monkeypatch.setattr(sys, "argv", [
        "gap_detector",
        "--data-root", str(tmp_path),
        "--start", "2026-05-18", "--end", "2026-05-18",
    ])
    rc = gd.main()
    # A 5s gap in ~20s of data is ~25% — fails the 0.1% threshold
    assert rc == 1
