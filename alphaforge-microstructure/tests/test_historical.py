"""Tests for historical.binance_vision archive parser + writer.

These exercise:
  - header vs no-header CSV detection
  - is_buyer_maker bool parsing for both 'true'/'false' and '0'/'1' formats
  - hourly bucketing on the date boundary
  - parquet schema match with collector/storage.py::_trade_schema
  - checksum verification (mismatch raises)
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from datetime import date as date_t

import pytest
import pyarrow.parquet as pq

from collector.storage import _trade_schema as live_trade_schema
from historical.binance_vision import (
    ArchiveCorrupt,
    _has_header,
    _parse_bool,
    _row_from_csv,
    _trade_schema as historical_trade_schema,
    parse_zip,
    write_day,
)


# --- schema parity ---------------------------------------------------------


def test_historical_schema_matches_live_collector():
    """Archive trades must land in the same parquet schema the live
    collector writes; downstream code is then origin-agnostic."""
    assert historical_trade_schema().equals(live_trade_schema())


# --- header detection ------------------------------------------------------


def test_has_header_detects_string_header():
    assert _has_header(["agg_trade_id", "price", "quantity"])


def test_has_header_rejects_numeric_first_row():
    assert not _has_header(["12345", "50000.0", "0.001"])


def test_has_header_handles_empty():
    assert not _has_header([])


# --- bool parsing ----------------------------------------------------------


@pytest.mark.parametrize("val,expected", [
    ("true", True), ("True", True), ("TRUE", True), ("1", True),
    ("false", False), ("False", False), ("FALSE", False), ("0", False),
])
def test_parse_bool_accepts_known_forms(val, expected):
    assert _parse_bool(val) is expected


def test_parse_bool_rejects_unknown():
    with pytest.raises(ValueError):
        _parse_bool("yes")


# --- row parsing -----------------------------------------------------------


def test_row_from_csv_converts_ms_to_ns():
    row = ["123", "50000.5", "0.001", "100", "100", "1700000000000", "true"]
    r = _row_from_csv(row)
    assert r.agg_trade_id == 123
    assert r.price == 50000.5
    assert r.size == 0.001
    assert r.exchange_ts_ns == 1700000000000 * 1_000_000
    assert r.is_buyer_maker is True


# --- zip parsing -----------------------------------------------------------


def _build_zip(rows: list[list[str]], include_header: bool = False) -> bytes:
    """Build an in-memory zip mimicking a Binance Vision daily file."""
    csv_lines = []
    if include_header:
        csv_lines.append(",".join([
            "agg_trade_id", "price", "quantity", "first_trade_id",
            "last_trade_id", "transact_time", "is_buyer_maker",
        ]))
    for r in rows:
        csv_lines.append(",".join(r))
    csv_bytes = ("\n".join(csv_lines) + "\n").encode("utf-8")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("BTCUSDT-aggTrades-2024-01-01.csv", csv_bytes)
    return buf.getvalue()


def test_parse_zip_without_header():
    rows = [
        ["1", "50000.0", "0.1", "10", "10", "1704067200000", "false"],
        ["2", "50001.0", "0.2", "11", "11", "1704067201000", "true"],
    ]
    parsed = list(parse_zip(_build_zip(rows, include_header=False)))
    assert len(parsed) == 2
    assert parsed[0].agg_trade_id == 1
    assert parsed[0].is_buyer_maker is False
    assert parsed[1].agg_trade_id == 2
    assert parsed[1].is_buyer_maker is True


def test_parse_zip_with_header():
    rows = [["1", "50000.0", "0.1", "10", "10", "1704067200000", "0"]]
    parsed = list(parse_zip(_build_zip(rows, include_header=True)))
    assert len(parsed) == 1
    assert parsed[0].agg_trade_id == 1


def test_parse_zip_rejects_multifile_archive():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a.csv", "1,2,3\n")
        zf.writestr("b.csv", "4,5,6\n")
    with pytest.raises(ArchiveCorrupt):
        list(parse_zip(buf.getvalue()))


# --- hourly bucketing ------------------------------------------------------


def test_write_day_buckets_by_hour(tmp_path):
    """Two trades on the same day, two different hours → two parquet files."""
    rows = [
        # 2024-01-01 00:00:00 UTC = 1704067200000 ms
        ["1", "50000.0", "0.1", "10", "10", "1704067200000", "false"],
        # 2024-01-01 03:30:00 UTC = 1704079800000 ms
        ["2", "50001.0", "0.2", "11", "11", "1704079800000", "true"],
    ]
    zb = _build_zip(rows, include_header=False)
    summary = write_day(tmp_path, date_t(2024, 1, 1), parse_zip(zb))
    assert summary["total_rows"] == 2
    assert set(summary["by_hour"].keys()) == {0, 3}

    p0 = tmp_path / "trades" / "2024-01-01" / "00.parquet"
    p3 = tmp_path / "trades" / "2024-01-01" / "03.parquet"
    assert p0.exists() and p3.exists()

    t0 = pq.read_table(p0)
    assert t0.num_rows == 1
    # Schema written must match the live collector's exactly
    assert t0.schema.equals(live_trade_schema())


def test_write_day_drops_rows_from_other_dates(tmp_path):
    """A row whose timestamp falls outside the target date is skipped."""
    rows = [
        ["1", "50000.0", "0.1", "10", "10", "1704067200000", "false"],   # 2024-01-01
        ["2", "50001.0", "0.2", "11", "11", "1704153600000", "true"],    # 2024-01-02
    ]
    zb = _build_zip(rows, include_header=False)
    summary = write_day(tmp_path, date_t(2024, 1, 1), parse_zip(zb))
    assert summary["total_rows"] == 1
    assert list(summary["by_hour"].keys()) == [0]


# --- checksum verification --------------------------------------------------


def test_fetch_archive_checksum_mismatch(monkeypatch):
    """If the published checksum doesn't match the zip's sha256, raise."""
    from historical import binance_vision as bv

    payload = _build_zip(
        [["1", "50000.0", "0.1", "10", "10", "1704067200000", "true"]]
    )

    class FakeResponse:
        def __init__(self, status, content=b"", text=""):
            self.status_code = status
            self.content = content
            self.text = text
        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

    class FakeSession:
        def get(self, url, timeout=None):
            if url.endswith(".CHECKSUM"):
                # Return a deliberately wrong checksum
                return FakeResponse(200, text="0" * 64 + "  filename\n")
            return FakeResponse(200, content=payload)

    with pytest.raises(ArchiveCorrupt):
        bv.fetch_archive("BTCUSDT", date_t(2024, 1, 1), session=FakeSession())


def test_fetch_archive_checksum_match(monkeypatch):
    from historical import binance_vision as bv

    payload = _build_zip(
        [["1", "50000.0", "0.1", "10", "10", "1704067200000", "true"]]
    )
    expected = hashlib.sha256(payload).hexdigest()

    class FakeResponse:
        def __init__(self, status, content=b"", text=""):
            self.status_code = status
            self.content = content
            self.text = text
        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

    class FakeSession:
        def get(self, url, timeout=None):
            if url.endswith(".CHECKSUM"):
                return FakeResponse(200, text=f"{expected}  filename\n")
            return FakeResponse(200, content=payload)

    got = bv.fetch_archive("BTCUSDT", date_t(2024, 1, 1), session=FakeSession())
    assert got == payload
