"""Download + parse Binance Vision historical aggTrades archives.

Binance publishes daily ZIPs at:
    https://data.binance.vision/data/futures/um/daily/aggTrades/{SYMBOL}/{SYMBOL}-aggTrades-{YYYY-MM-DD}.zip
With matching SHA-256 checksum at the same URL plus `.CHECKSUM`.

Each ZIP contains one CSV with columns (in this order, sometimes with a
header row, sometimes without):

    agg_trade_id, price, quantity, first_trade_id, last_trade_id,
    transact_time, is_buyer_maker

`transact_time` is milliseconds since epoch. `is_buyer_maker` is "true" /
"false" string or 0/1 depending on the day's file format.

We parse a year of files into the SAME parquet schema the live collector
writes to (collector/storage.py::_trade_schema) so downstream signal code
is indifferent to data origin. Output layout:

    data/trades/YYYY-MM-DD/HH.parquet

…matching the live collector exactly. Each archive day produces 24 hourly
shards.

What this loader CANNOT do: there is no free historical L2 diff archive
from Binance Vision. This loader unblocks Trade-Flow-Imbalance research
on multi-year data; OBI / microprice / spread-dynamics research still
requires the live collector (collector/run_collector.py) to accumulate
~30+ days of book snapshots.

Usage:
    python3 -m historical.binance_vision \\
        --symbol BTCUSDT --start 2024-01-01 --end 2024-12-31 \\
        --out data/
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import logging
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date as date_t, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Iterator, Optional

import requests
import pyarrow as pa
import pyarrow.parquet as pq


log = logging.getLogger(__name__)


BASE_URL = "https://data.binance.vision/data/futures/um/daily/aggTrades"
EXPECTED_COLS = (
    "agg_trade_id",
    "price",
    "quantity",
    "first_trade_id",
    "last_trade_id",
    "transact_time",
    "is_buyer_maker",
)


@dataclass(slots=True)
class _TradeRow:
    exchange_ts_ns: int
    agg_trade_id: int
    price: float
    size: float
    is_buyer_maker: bool


# --- url builders -----------------------------------------------------------


def _zip_url(symbol: str, d: date_t) -> str:
    return f"{BASE_URL}/{symbol}/{symbol}-aggTrades-{d.isoformat()}.zip"


def _checksum_url(symbol: str, d: date_t) -> str:
    return _zip_url(symbol, d) + ".CHECKSUM"


# --- fetch + verify ---------------------------------------------------------


class ArchiveMissing(Exception):
    pass


class ArchiveCorrupt(Exception):
    pass


def fetch_archive(
    symbol: str,
    d: date_t,
    session: Optional[requests.Session] = None,
    verify_checksum: bool = True,
) -> bytes:
    """Download one daily ZIP, verify SHA-256 against the .CHECKSUM file.

    Raises ArchiveMissing if the day is unavailable (404), ArchiveCorrupt
    if the checksum mismatches.
    """
    s = session or requests.Session()
    url = _zip_url(symbol, d)
    r = s.get(url, timeout=60)
    if r.status_code == 404:
        raise ArchiveMissing(f"{url} returned 404")
    r.raise_for_status()
    payload = r.content

    if verify_checksum:
        cs = s.get(_checksum_url(symbol, d), timeout=30)
        if cs.status_code == 200:
            # Checksum file format: "<sha256>  <filename>\n"
            expected = cs.text.strip().split()[0].lower()
            actual = hashlib.sha256(payload).hexdigest()
            if actual != expected:
                raise ArchiveCorrupt(
                    f"sha256 mismatch for {url}: expected={expected} actual={actual}"
                )
        else:
            log.warning("no checksum file for %s (status %d); skipping verify", url, cs.status_code)

    return payload


# --- parsing ----------------------------------------------------------------


def _has_header(first_row: list[str]) -> bool:
    """True if the first CSV row is a header (non-numeric agg_trade_id)."""
    if not first_row:
        return False
    try:
        int(first_row[0])
        return False
    except ValueError:
        return True


def _parse_bool(s: str) -> bool:
    """is_buyer_maker is variously 'true'/'false' or '0'/'1' across years."""
    s = s.strip().lower()
    if s in ("true", "1"):
        return True
    if s in ("false", "0"):
        return False
    raise ValueError(f"unparseable is_buyer_maker value: {s!r}")


def parse_zip(zip_bytes: bytes) -> Iterator[_TradeRow]:
    """Yield _TradeRow from a daily aggTrades ZIP payload."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        if len(names) != 1:
            raise ArchiveCorrupt(f"expected single CSV in archive, got {names}")
        with zf.open(names[0]) as f:
            text_stream = io.TextIOWrapper(f, encoding="utf-8", newline="")
            reader = csv.reader(text_stream)
            first = next(reader, None)
            if first is None:
                return
            if not _has_header(first):
                # First row is data; yield it before continuing.
                yield _row_from_csv(first)
            for row in reader:
                if not row:
                    continue
                yield _row_from_csv(row)


def _row_from_csv(row: list[str]) -> _TradeRow:
    # agg_trade_id, price, quantity, first_trade_id, last_trade_id, transact_time, is_buyer_maker
    return _TradeRow(
        exchange_ts_ns=int(row[5]) * 1_000_000,
        agg_trade_id=int(row[0]),
        price=float(row[1]),
        size=float(row[2]),
        is_buyer_maker=_parse_bool(row[6]),
    )


# --- parquet write (matches collector/storage.py schema) ---------------------


def _trade_schema() -> pa.Schema:
    return pa.schema([
        pa.field("exchange_ts_ns", pa.int64()),
        pa.field("local_ts_ns", pa.int64()),
        pa.field("agg_trade_id", pa.int64()),
        pa.field("price", pa.float64()),
        pa.field("size", pa.float64()),
        pa.field("is_buyer_maker", pa.bool_()),
    ])


def write_day(out_root: Path, d: date_t, rows: Iterable[_TradeRow]) -> dict:
    """Bucket rows into hourly parquet files under data/trades/YYYY-MM-DD/HH.parquet.

    `local_ts_ns` is set equal to `exchange_ts_ns` for archive rows (no
    receive-side timestamp exists; downstream code should treat them
    interchangeably for archived data).
    """
    buckets: dict[int, list[dict]] = {h: [] for h in range(24)}
    total = 0
    for r in rows:
        dt = datetime.fromtimestamp(r.exchange_ts_ns / 1e9, tz=timezone.utc)
        # Defensive: skip rows that landed on a different day (timezone / DST)
        if dt.date() != d:
            continue
        buckets[dt.hour].append({
            "exchange_ts_ns": r.exchange_ts_ns,
            "local_ts_ns": r.exchange_ts_ns,  # archive: no separate local ts
            "agg_trade_id": r.agg_trade_id,
            "price": r.price,
            "size": r.size,
            "is_buyer_maker": r.is_buyer_maker,
        })
        total += 1

    day_dir = out_root / "trades" / d.isoformat()
    day_dir.mkdir(parents=True, exist_ok=True)
    schema = _trade_schema()
    written = {}
    for hour, hour_rows in buckets.items():
        if not hour_rows:
            continue
        path = day_dir / f"{hour:02d}.parquet"
        table = pa.Table.from_pylist(hour_rows, schema=schema)
        pq.write_table(table, path, compression="zstd")
        written[hour] = len(hour_rows)
    return {"date": d.isoformat(), "total_rows": total, "by_hour": written}


# --- end-to-end driver ------------------------------------------------------


def ingest_day(
    symbol: str,
    d: date_t,
    out_root: Path,
    session: Optional[requests.Session] = None,
    verify_checksum: bool = True,
    skip_existing: bool = True,
) -> dict:
    """Fetch one day, parse, write hourly parquet shards.

    Returns a summary dict. If `skip_existing` and any hourly shard for
    the day already exists, the day is skipped entirely (idempotency).
    """
    day_dir = out_root / "trades" / d.isoformat()
    if skip_existing and day_dir.exists() and any(day_dir.glob("*.parquet")):
        return {"date": d.isoformat(), "skipped": True}

    payload = fetch_archive(symbol, d, session=session, verify_checksum=verify_checksum)
    summary = write_day(out_root, d, parse_zip(payload))
    summary["bytes_downloaded"] = len(payload)
    return summary


def _daterange(start: date_t, end: date_t) -> Iterator[date_t]:
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Download Binance Vision aggTrades archives")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--start", type=date_t.fromisoformat, required=True)
    parser.add_argument("--end", type=date_t.fromisoformat, required=True)
    parser.add_argument("--out", type=Path, default=Path("data"))
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--no-verify-checksum", action="store_true")
    parser.add_argument("--force", action="store_true", help="Re-download even if present")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    days = list(_daterange(args.start, args.end))
    log.info("ingesting %d days for %s into %s", len(days), args.symbol, args.out)

    session = requests.Session()
    successes = 0
    skipped = 0
    failures: list[tuple[str, str]] = []

    with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futs = {
            ex.submit(
                ingest_day,
                args.symbol,
                d,
                args.out,
                session,
                not args.no_verify_checksum,
                not args.force,
            ): d
            for d in days
        }
        for f in as_completed(futs):
            d = futs[f]
            try:
                summary = f.result()
                if summary.get("skipped"):
                    skipped += 1
                    log.info("%s: skipped (already present)", d.isoformat())
                else:
                    successes += 1
                    log.info(
                        "%s: %d rows, %d hours, %.1fMB",
                        d.isoformat(),
                        summary.get("total_rows", 0),
                        len(summary.get("by_hour", {})),
                        summary.get("bytes_downloaded", 0) / 1e6,
                    )
            except ArchiveMissing as e:
                failures.append((d.isoformat(), f"missing: {e}"))
                log.warning("%s: %s", d.isoformat(), e)
            except Exception as e:
                failures.append((d.isoformat(), f"{type(e).__name__}: {e}"))
                log.error("%s: %s", d.isoformat(), e)

    log.info(
        "done. success=%d skipped=%d failed=%d",
        successes, skipped, len(failures),
    )
    if failures:
        log.info("first 5 failures: %s", failures[:5])
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
