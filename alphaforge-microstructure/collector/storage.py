"""Rolling parquet writer for book snapshots and trade events.

Layout under the root data directory:

    data/
      book_snapshots/
        2026-05-17/
          14.parquet   # all snapshots whose local_ts hour-bucket is 14:00 UTC
          15.parquet
          ...
      trades/
        2026-05-17/
          14.parquet
          ...
      _gaps.jsonl      # one line per resync / gap event, append-only

Files are rolled hourly: when the local timestamp crosses an hour boundary
we flush the current writer and open a new one. The writer batches in
memory and flushes every FLUSH_INTERVAL_SECONDS (or on roll). A crash
loses at most one flush interval of data.

All timestamps are nanosecond ints. The book snapshot row layout is
flat — bid_px_1..N, bid_sz_1..N, ask_px_1..N, ask_sz_1..N — for fast
columnar reads downstream.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import pyarrow as pa
import pyarrow.parquet as pq

from .book import BookSnapshot

if TYPE_CHECKING:
    from .binance_ws import TradeEvent


log = logging.getLogger(__name__)


FLUSH_INTERVAL_SECONDS = 30
BOOK_LEVELS = 20


# --- schemas ----------------------------------------------------------------


def _book_schema(levels: int = BOOK_LEVELS) -> pa.Schema:
    fields = [
        pa.field("exchange_ts_ns", pa.int64()),
        pa.field("local_ts_ns", pa.int64()),
        pa.field("last_update_id", pa.int64()),
        pa.field("mid", pa.float64()),
        pa.field("spread", pa.float64()),
    ]
    for i in range(1, levels + 1):
        fields.append(pa.field(f"bid_px_{i}", pa.float64()))
        fields.append(pa.field(f"bid_sz_{i}", pa.float64()))
    for i in range(1, levels + 1):
        fields.append(pa.field(f"ask_px_{i}", pa.float64()))
        fields.append(pa.field(f"ask_sz_{i}", pa.float64()))
    return pa.schema(fields)


def _trade_schema() -> pa.Schema:
    return pa.schema([
        pa.field("exchange_ts_ns", pa.int64()),
        pa.field("local_ts_ns", pa.int64()),
        pa.field("agg_trade_id", pa.int64()),
        pa.field("price", pa.float64()),
        pa.field("size", pa.float64()),
        pa.field("is_buyer_maker", pa.bool_()),
    ])


# --- writer -----------------------------------------------------------------


@dataclass
class _BucketWriter:
    path: Path
    schema: pa.Schema
    writer: Optional[pq.ParquetWriter] = None
    rows: list[dict] = None
    last_flush_ns: int = 0

    def __post_init__(self) -> None:
        if self.rows is None:
            self.rows = []
        self.last_flush_ns = time.time_ns()

    def append(self, row: dict) -> None:
        self.rows.append(row)

    def flush(self) -> None:
        if not self.rows:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        table = pa.Table.from_pylist(self.rows, schema=self.schema)
        if self.writer is None:
            self.writer = pq.ParquetWriter(self.path, self.schema, compression="zstd")
        self.writer.write_table(table)
        self.rows.clear()
        self.last_flush_ns = time.time_ns()

    def close(self) -> None:
        self.flush()
        if self.writer is not None:
            self.writer.close()
            self.writer = None


class ParquetStore:
    """Append-only hourly-rolling parquet store for book + trades + gaps."""

    def __init__(self, root: Path, levels: int = BOOK_LEVELS) -> None:
        self.root = Path(root)
        self.levels = levels
        self._book_schema = _book_schema(levels)
        self._trade_schema = _trade_schema()
        self._book_writer: Optional[_BucketWriter] = None
        self._trade_writer: Optional[_BucketWriter] = None
        self._current_book_hour: Optional[str] = None
        self._current_trade_hour: Optional[str] = None
        self._gaps_path = self.root / "_gaps.jsonl"

    # -- public --------------------------------------------------------------

    def write_book_snapshot(self, snap: BookSnapshot) -> None:
        bucket = self._hour_bucket(snap.local_ts_ns)
        if bucket != self._current_book_hour:
            if self._book_writer is not None:
                self._book_writer.close()
            path = self.root / "book_snapshots" / bucket[:10] / f"{bucket[11:13]}.parquet"
            self._book_writer = _BucketWriter(path=path, schema=self._book_schema)
            self._current_book_hour = bucket

        row = {
            "exchange_ts_ns": int(snap.exchange_ts_ns),
            "local_ts_ns": int(snap.local_ts_ns),
            "last_update_id": int(snap.last_update_id),
            "mid": snap.mid if snap.mid is not None else float("nan"),
            "spread": snap.spread if snap.spread is not None else float("nan"),
        }
        for i in range(self.levels):
            if i < len(snap.bids):
                row[f"bid_px_{i+1}"] = float(snap.bids[i][0])
                row[f"bid_sz_{i+1}"] = float(snap.bids[i][1])
            else:
                row[f"bid_px_{i+1}"] = float("nan")
                row[f"bid_sz_{i+1}"] = float("nan")
            if i < len(snap.asks):
                row[f"ask_px_{i+1}"] = float(snap.asks[i][0])
                row[f"ask_sz_{i+1}"] = float(snap.asks[i][1])
            else:
                row[f"ask_px_{i+1}"] = float("nan")
                row[f"ask_sz_{i+1}"] = float("nan")
        self._book_writer.append(row)
        self._maybe_flush(self._book_writer)

    def write_trade(self, t: TradeEvent) -> None:
        bucket = self._hour_bucket(t.local_ts_ns)
        if bucket != self._current_trade_hour:
            if self._trade_writer is not None:
                self._trade_writer.close()
            path = self.root / "trades" / bucket[:10] / f"{bucket[11:13]}.parquet"
            self._trade_writer = _BucketWriter(path=path, schema=self._trade_schema)
            self._current_trade_hour = bucket

        self._trade_writer.append({
            "exchange_ts_ns": int(t.exchange_ts_ns),
            "local_ts_ns": int(t.local_ts_ns),
            "agg_trade_id": int(t.agg_trade_id),
            "price": float(t.price),
            "size": float(t.size),
            "is_buyer_maker": bool(t.is_buyer_maker),
        })
        self._maybe_flush(self._trade_writer)

    def write_gap(self, gap: dict) -> None:
        self._gaps_path.parent.mkdir(parents=True, exist_ok=True)
        with self._gaps_path.open("a") as f:
            f.write(json.dumps(gap) + "\n")

    def close(self) -> None:
        if self._book_writer is not None:
            self._book_writer.close()
        if self._trade_writer is not None:
            self._trade_writer.close()

    # -- internals -----------------------------------------------------------

    @staticmethod
    def _hour_bucket(ts_ns: int) -> str:
        dt = datetime.fromtimestamp(ts_ns / 1e9, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H")

    @staticmethod
    def _maybe_flush(writer: _BucketWriter) -> None:
        if time.time_ns() - writer.last_flush_ns >= FLUSH_INTERVAL_SECONDS * 1_000_000_000:
            writer.flush()
