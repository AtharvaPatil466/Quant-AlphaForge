"""Paginated Binance downloader → local parquet store.

For each (symbol, stream) pair the downloader:
1. Reads the existing on-disk shard(s) to find the latest stored timestamp.
2. Resumes pagination from that point — fully idempotent reruns.
3. Writes data partitioned by year (klines, open interest) or as a single
   whole-history file (funding rate, which is low-cardinality at 3 events/day).

The downloader does not perform validation; the validator runs as a separate
pass over the parquet store after the sync.

Binance API caveats baked in:
- Klines: max 1000 rows per request, paginate by startTime.
- Funding rate: max 1000 rows per request, paginate by startTime.
- Open interest history: only the trailing ~30 days are available from Binance,
  so backfilling more than that yields nothing. We treat OI as "forward roll
  from today" rather than as a historical backfill stream and document this.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .binance_client import BinanceClient
from .paths import (
    BinancePaths,
    default_paths,
    funding_path,
    kline_year_path,
    oi_year_path,
)


INTERVAL_MS = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "8h": 28_800_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
}

KLINE_COLUMNS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "trade_count",
    "taker_buy_base",
    "taker_buy_quote",
]

FUNDING_COLUMNS = ["funding_time", "symbol", "funding_rate", "mark_price"]

OI_COLUMNS = ["timestamp", "sum_open_interest", "sum_open_interest_value"]


@dataclass
class SyncResult:
    klines_spot_rows: dict[str, int] = field(default_factory=dict)
    klines_perp_rows: dict[str, int] = field(default_factory=dict)
    funding_rows: dict[str, int] = field(default_factory=dict)
    oi_rows: dict[str, int] = field(default_factory=dict)
    files_written: list[Path] = field(default_factory=list)

    def total_rows(self) -> int:
        return (
            sum(self.klines_spot_rows.values())
            + sum(self.klines_perp_rows.values())
            + sum(self.funding_rows.values())
            + sum(self.oi_rows.values())
        )


class BinanceDataDownloader:
    """Idempotent fetcher that writes a parquet store under `<repo>/data/binance/`.

    The constructor takes a `BinanceClient` so callers (and tests) can inject a
    mock-transport client without the downloader doing its own HTTP setup.
    """

    def __init__(
        self,
        client: BinanceClient,
        *,
        base_dir: str | Path | None = None,
        kline_interval: str = "1h",
    ):
        if kline_interval not in INTERVAL_MS:
            raise ValueError(f"unsupported kline interval {kline_interval!r}")
        self.client = client
        self.paths: BinancePaths = default_paths(base_dir)
        self.kline_interval = kline_interval
        self.interval_ms = INTERVAL_MS[kline_interval]

    # ---- public sync entry ----------------------------------------------------

    def sync(
        self,
        symbols: Iterable[str],
        *,
        start_date: str,
        end_date: str | None = None,
        include_spot: bool = True,
        include_perp: bool = True,
        include_funding: bool = True,
        include_open_interest: bool = False,
    ) -> SyncResult:
        start_ms = _date_to_ms(start_date)
        end_ms = _date_to_ms(end_date) if end_date else _now_ms()
        result = SyncResult()

        for symbol in symbols:
            symbol = symbol.upper()
            if include_spot:
                rows, files = self._sync_klines(symbol, "spot", start_ms, end_ms)
                result.klines_spot_rows[symbol] = rows
                result.files_written.extend(files)
            if include_perp:
                rows, files = self._sync_klines(symbol, "perp", start_ms, end_ms)
                result.klines_perp_rows[symbol] = rows
                result.files_written.extend(files)
            if include_funding:
                rows, file = self._sync_funding(symbol, start_ms, end_ms)
                result.funding_rows[symbol] = rows
                if file is not None:
                    result.files_written.append(file)
            if include_open_interest:
                rows, files = self._sync_open_interest(symbol, start_ms, end_ms)
                result.oi_rows[symbol] = rows
                result.files_written.extend(files)

        return result

    # ---- klines ----------------------------------------------------------------

    def _sync_klines(
        self,
        symbol: str,
        market: str,
        start_ms: int,
        end_ms: int,
    ) -> tuple[int, list[Path]]:
        """Idempotently fill klines for `[start_ms, end_ms]`.

        Handles three cases:
          1. No existing data → walk the entire range.
          2. Existing data ends before `end_ms` → suffix backfill from latest+interval.
          3. Existing data starts after `start_ms` → prefix backfill for the
             gap `[start_ms, earliest_existing)`. (Bug fix from 2026-05-15:
             the original logic skipped this gap, so a smoke test followed by
             a longer-range run silently lost the prefix.)
        """
        earliest, latest = self._kline_range(symbol, market)
        suffix_start = max(start_ms, (latest + self.interval_ms) if latest >= 0 else start_ms)
        total_rows = 0
        new_rows_by_year: dict[int, list[list]] = {}

        # Prefix backfill: existing data starts later than what was requested.
        if earliest >= 0 and start_ms < earliest:
            total_rows += self._walk_klines_range(
                symbol, market, start_ms, earliest - 1, new_rows_by_year
            )

        # Normal/suffix walk.
        if suffix_start < end_ms:
            total_rows += self._walk_klines_range(
                symbol, market, suffix_start, end_ms, new_rows_by_year
            )

        written: list[Path] = []
        for year, year_rows in new_rows_by_year.items():
            frame = pd.DataFrame(year_rows, columns=KLINE_COLUMNS)
            frame = _normalize_kline_frame(frame)
            path = kline_year_path(symbol, year, market, base_dir=self.paths.binance_root)
            self._append_parquet(path, frame, key_column="open_time")
            written.append(path)
        return total_rows, written

    def _walk_klines_range(
        self,
        symbol: str,
        market: str,
        from_ms: int,
        to_ms: int,
        sink: dict[int, list[list]],
    ) -> int:
        fetch = self.client.spot_klines if market == "spot" else self.client.fapi_klines
        cursor = from_ms
        rows_added = 0
        while cursor < to_ms:
            rows = fetch(
                symbol,
                self.kline_interval,
                start_time_ms=cursor,
                end_time_ms=to_ms,
                limit=1000,
            )
            if not rows:
                break
            for row in rows:
                year = _year_of_ms(int(row[0]))
                sink.setdefault(year, []).append(row[:11])
                rows_added += 1
            last_open = int(rows[-1][0])
            if last_open + self.interval_ms <= cursor:
                break
            cursor = last_open + self.interval_ms
            if len(rows) < 1000:
                break
        return rows_added

    def _kline_range(self, symbol: str, market: str) -> tuple[int, int]:
        """Return (earliest_open_time, latest_open_time) across stored shards.

        Returns (-1, -1) if no data is on disk.
        """
        symbol_dir = (
            self.paths.spot_klines_root if market == "spot" else self.paths.perp_klines_root
        ) / symbol.upper()
        if not symbol_dir.exists():
            return -1, -1
        earliest, latest = -1, -1
        for f in sorted(symbol_dir.glob("*.parquet")):
            table = pq.read_table(f, columns=["open_time"])
            if table.num_rows == 0:
                continue
            series = table.column("open_time").to_pandas()
            year_min, year_max = int(series.min()), int(series.max())
            if earliest < 0 or year_min < earliest:
                earliest = year_min
            if year_max > latest:
                latest = year_max
        return earliest, latest

    def _latest_kline_open_time(self, symbol: str, market: str) -> int:
        _, latest = self._kline_range(symbol, market)
        return latest

    # ---- funding ---------------------------------------------------------------

    def _sync_funding(self, symbol: str, start_ms: int, end_ms: int) -> tuple[int, Path | None]:
        """Idempotently fill funding history for `[start_ms, end_ms]`.

        Same prefix/suffix logic as `_sync_klines`: if existing rows start
        later than `start_ms`, we backfill the prefix too.
        """
        earliest, latest = self._funding_range(symbol)
        collected: list[dict] = []

        if earliest >= 0 and start_ms < earliest:
            collected.extend(self._walk_funding_range(symbol, start_ms, earliest - 1))

        suffix_start = max(start_ms, (latest + 1) if latest >= 0 else start_ms)
        if suffix_start < end_ms:
            collected.extend(self._walk_funding_range(symbol, suffix_start, end_ms))

        if not collected:
            return 0, None

        frame = pd.DataFrame(collected, columns=FUNDING_COLUMNS)
        frame = _normalize_funding_frame(frame)
        path = funding_path(symbol, base_dir=self.paths.binance_root)
        self._append_parquet(path, frame, key_column="funding_time")
        return len(collected), path

    def _walk_funding_range(self, symbol: str, from_ms: int, to_ms: int) -> list[dict]:
        rows_out: list[dict] = []
        cursor = from_ms
        while cursor < to_ms:
            rows = self.client.funding_rate_history(
                symbol, start_time_ms=cursor, end_time_ms=to_ms, limit=1000,
            )
            if not rows:
                break
            for row in rows:
                rows_out.append(
                    {
                        "funding_time": int(row["fundingTime"]),
                        "symbol": str(row["symbol"]),
                        "funding_rate": _safe_float(row.get("fundingRate")),
                        "mark_price": _safe_float(row.get("markPrice")),
                    }
                )
            last_ft = int(rows[-1]["fundingTime"])
            if last_ft + 1 <= cursor:
                break
            cursor = last_ft + 1
            if len(rows) < 1000:
                break
        return rows_out

    def _funding_range(self, symbol: str) -> tuple[int, int]:
        path = funding_path(symbol, base_dir=self.paths.binance_root)
        if not path.exists():
            return -1, -1
        table = pq.read_table(path, columns=["funding_time"])
        if table.num_rows == 0:
            return -1, -1
        series = table.column("funding_time").to_pandas()
        return int(series.min()), int(series.max())

    def _latest_funding_time(self, symbol: str) -> int:
        _, latest = self._funding_range(symbol)
        return latest

    # ---- open interest --------------------------------------------------------

    def _sync_open_interest(
        self, symbol: str, start_ms: int, end_ms: int
    ) -> tuple[int, list[Path]]:
        thirty_days_ago = _now_ms() - 30 * 86_400_000
        effective_start = max(start_ms, thirty_days_ago, self._latest_oi_time(symbol) + 1)
        if effective_start >= end_ms:
            return 0, []

        cursor = effective_start
        new_rows_by_year: dict[int, list[dict]] = {}
        total_rows = 0

        while cursor < end_ms:
            rows = self.client.open_interest_history(
                symbol,
                period="1h",
                start_time_ms=cursor,
                end_time_ms=end_ms,
                limit=500,
            )
            if not rows:
                break
            for row in rows:
                ts = int(row["timestamp"])
                year = _year_of_ms(ts)
                new_rows_by_year.setdefault(year, []).append(
                    {
                        "timestamp": ts,
                        "sum_open_interest": float(row["sumOpenInterest"]),
                        "sum_open_interest_value": float(row["sumOpenInterestValue"]),
                    }
                )
                total_rows += 1
            last_ts = int(rows[-1]["timestamp"])
            if last_ts + 1 <= cursor:
                break
            cursor = last_ts + 1
            if len(rows) < 500:
                break

        written: list[Path] = []
        for year, year_rows in new_rows_by_year.items():
            frame = pd.DataFrame(year_rows, columns=OI_COLUMNS)
            frame = _normalize_oi_frame(frame)
            path = oi_year_path(symbol, year, base_dir=self.paths.binance_root)
            self._append_parquet(path, frame, key_column="timestamp")
            written.append(path)
        return total_rows, written

    def _latest_oi_time(self, symbol: str) -> int:
        symbol_dir = self.paths.open_interest_root / symbol.upper()
        if not symbol_dir.exists():
            return -1
        latest = -1
        for f in sorted(symbol_dir.glob("*.parquet")):
            table = pq.read_table(f, columns=["timestamp"])
            if table.num_rows == 0:
                continue
            year_max = int(table.column("timestamp").to_pandas().max())
            if year_max > latest:
                latest = year_max
        return latest

    # ---- shared write helper --------------------------------------------------

    @staticmethod
    def _append_parquet(path: Path, new_frame: pd.DataFrame, *, key_column: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            existing = pq.read_table(path).to_pandas()
            combined = pd.concat([existing, new_frame], ignore_index=True)
            combined = combined.drop_duplicates(subset=[key_column], keep="last")
            combined = combined.sort_values(key_column).reset_index(drop=True)
        else:
            combined = new_frame.drop_duplicates(subset=[key_column], keep="last")
            combined = combined.sort_values(key_column).reset_index(drop=True)
        pq.write_table(pa.Table.from_pandas(combined, preserve_index=False), path)


# ---- frame normalization helpers ---------------------------------------------

def _normalize_kline_frame(frame: pd.DataFrame) -> pd.DataFrame:
    int_cols = ["open_time", "close_time", "trade_count"]
    float_cols = [c for c in frame.columns if c not in int_cols]
    for c in int_cols:
        frame[c] = frame[c].astype("int64")
    for c in float_cols:
        frame[c] = pd.to_numeric(frame[c], errors="coerce").astype("float64")
    return frame


def _normalize_funding_frame(frame: pd.DataFrame) -> pd.DataFrame:
    frame["funding_time"] = frame["funding_time"].astype("int64")
    frame["symbol"] = frame["symbol"].astype("string")
    frame["funding_rate"] = frame["funding_rate"].astype("float64")
    frame["mark_price"] = frame["mark_price"].astype("float64")
    return frame


def _normalize_oi_frame(frame: pd.DataFrame) -> pd.DataFrame:
    frame["timestamp"] = frame["timestamp"].astype("int64")
    frame["sum_open_interest"] = frame["sum_open_interest"].astype("float64")
    frame["sum_open_interest_value"] = frame["sum_open_interest_value"].astype("float64")
    return frame


def _safe_float(v) -> float:
    """Convert a Binance API value to float, treating None/empty-string/'NaN' as NaN.

    Some endpoints (notably `/fapi/v1/fundingRate` for older symbols) return
    empty strings for fields like `markPrice` — `float("")` raises, so we
    coerce explicitly.
    """
    if v is None:
        return float("nan")
    if isinstance(v, str):
        s = v.strip()
        if not s or s.lower() == "nan":
            return float("nan")
        return float(s)
    return float(v)


def _date_to_ms(date_str: str) -> int:
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _year_of_ms(ms: int) -> int:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).year
