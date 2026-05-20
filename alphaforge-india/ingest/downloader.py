"""NSE bhavcopy / MTO / unified-format downloader.

Per `research/INDIA_DESIGN.md` §2.7. Three sources:

  - LEGACY  : pre-2020 bhavcopy zip — OHLCV only
              archives.nseindia.com/content/historical/EQUITIES/...
  - MTO     : pre-2020 delivery file — DELIV_QTY + DELIV_PER
              archives.nseindia.com/archives/equities/mto/...
  - UNIFIED : post-2020 bhavcopy CSV — OHLCV + DELIV inline
              archives.nseindia.com/products/content/sec_bhavdata_full_*.csv

Source selection by date is configurable. The default policy:
  date < 2020-02-01     → LEGACY + MTO required, UNIFIED skipped
  2020-02-01..present   → UNIFIED required, LEGACY + MTO optional

Checkpoint protocol:
  - Append one JSONL row per (date, source) attempt to
    `data/processed/_download_checkpoint.jsonl`
  - On restart, completed (date, source) pairs are skipped.
  - Atomic write: tmp file + os.replace. Partial files never appear under
    the canonical output path.

Retry policy:
  - 3 attempts per (date, source).
  - Backoff schedule: 2s → 8s → 32s.
  - 403 / 429 / 401 HALT the run (manual intervention required).
  - 5xx / timeouts / connection errors RETRY.
  - 404 is a terminal success ("no file on that date") — logged as such.

Holiday detection:
  - A weekday is suspected to be a non-trading day iff ALL applicable
    sources for that date return 404.
  - Logged to `data/processed/_holidays.jsonl` for the post-download
    validation pass per §2.6.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Iterable

import requests

# Module-level logger; configured by CLI or test harness.
log = logging.getLogger("india.downloader")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ARCHIVE_BASE = "https://archives.nseindia.com"

# Browser-shaped headers. NSE 403s anything that looks scripted.
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": "https://www.nseindia.com/",
}

MONTH_ABBR = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
              "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]

# Era boundary — first date the unified format is the primary source.
# Pre-boundary requires LEGACY + MTO; post-boundary requires UNIFIED.
DEFAULT_ERA_BOUNDARY = date(2020, 2, 1)

# Retry schedule (seconds). Length determines max attempt count.
RETRY_BACKOFF = (2.0, 8.0, 32.0)

# Status codes that halt the entire run (require manual intervention).
HALT_STATUSES = frozenset({401, 403, 429})


class Source(str, Enum):
    LEGACY = "legacy"
    MTO = "mto"
    UNIFIED = "unified"


class Result(str, Enum):
    OK = "ok"
    NOT_FOUND = "not_found"      # 404 — terminal, no retry
    FAILED = "failed"            # exhausted retries (server/network errors)
    HALTED = "halted"            # 403/429/401 — manual intervention needed
    SKIPPED = "skipped"          # already in checkpoint, not re-fetched


# ---------------------------------------------------------------------------
# URL construction
# ---------------------------------------------------------------------------

def legacy_url(d: date) -> str:
    return (
        f"{ARCHIVE_BASE}/content/historical/EQUITIES/{d.year}/"
        f"{MONTH_ABBR[d.month-1]}/cm{d.day:02d}{MONTH_ABBR[d.month-1]}{d.year}bhav.csv.zip"
    )


def mto_url(d: date) -> str:
    return (
        f"{ARCHIVE_BASE}/archives/equities/mto/"
        f"MTO_{d.day:02d}{d.month:02d}{d.year}.DAT"
    )


def unified_url(d: date) -> str:
    return (
        f"{ARCHIVE_BASE}/products/content/"
        f"sec_bhavdata_full_{d.day:02d}{d.month:02d}{d.year}.csv"
    )


# ---------------------------------------------------------------------------
# Output paths
# ---------------------------------------------------------------------------

def output_path(root: Path, source: Source, d: date) -> Path:
    """Where the downloaded body is written. One file per (date, source).

    Layout: {root}/{source}/{YYYY}/{MM}/{filename}
    Filenames preserve the canonical NSE naming for traceability.
    """
    sub = f"{d.year:04d}/{d.month:02d}"
    if source is Source.LEGACY:
        name = f"cm{d.day:02d}{MONTH_ABBR[d.month-1]}{d.year}bhav.csv.zip"
        return root / "bhavcopy" / sub / name
    if source is Source.MTO:
        name = f"MTO_{d.day:02d}{d.month:02d}{d.year}.DAT"
        return root / "mto" / sub / name
    if source is Source.UNIFIED:
        name = f"sec_bhavdata_full_{d.day:02d}{d.month:02d}{d.year}.csv"
        return root / "unified" / sub / name
    raise ValueError(f"unknown source: {source!r}")


# ---------------------------------------------------------------------------
# Source selection by era
# ---------------------------------------------------------------------------

def sources_for_date(d: date, era_boundary: date = DEFAULT_ERA_BOUNDARY,
                     overlap_days: int = 60) -> list[Source]:
    """Which sources to attempt for date `d`.

    `overlap_days` defines a validation window straddling the era boundary
    during which BOTH eras' sources are pulled, enabling the spike-test
    finding-1 cross-check.
    """
    overlap_start = era_boundary - timedelta(days=overlap_days)
    overlap_end = era_boundary + timedelta(days=overlap_days)
    if d < overlap_start:
        return [Source.LEGACY, Source.MTO]
    if d > overlap_end:
        return [Source.UNIFIED]
    # Overlap window: pull all three for cross-validation.
    return [Source.LEGACY, Source.MTO, Source.UNIFIED]


# ---------------------------------------------------------------------------
# Checkpoint
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CheckpointKey:
    date_iso: str  # YYYY-MM-DD
    source: str    # Source.value


@dataclass
class CheckpointRow:
    date: str          # YYYY-MM-DD
    source: str        # Source.value
    result: str        # Result.value
    status: int | None
    bytes: int
    sha256: str | None
    attempts: int
    completed_at: str  # ISO-8601 UTC
    error: str | None = None


class Checkpoint:
    """Append-only JSONL checkpoint with in-memory completed-set."""

    def __init__(self, path: Path):
        self.path = path
        self._completed: dict[CheckpointKey, CheckpointRow] = {}
        if path.exists():
            self._load()

    def _load(self) -> None:
        with self.path.open() as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    log.warning("checkpoint: skipping malformed line: %r", line[:80])
                    continue
                key = CheckpointKey(obj["date"], obj["source"])
                self._completed[key] = CheckpointRow(**obj)

    def is_done(self, d: date, source: Source) -> bool:
        """A (date, source) is done iff it has a terminal result (ok / not_found / halted).
        FAILED entries are re-attempted on resume."""
        row = self._completed.get(CheckpointKey(d.isoformat(), source.value))
        if row is None:
            return False
        return row.result in {Result.OK.value, Result.NOT_FOUND.value, Result.HALTED.value}

    def append(self, row: CheckpointRow) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Append-then-fsync; safe against partial writes (newline-delimited).
        with self.path.open("a") as fp:
            fp.write(json.dumps(asdict(row), separators=(",", ":")) + "\n")
            fp.flush()
            os.fsync(fp.fileno())
        self._completed[CheckpointKey(row.date, row.source)] = row

    def completed_count(self) -> int:
        return sum(1 for r in self._completed.values()
                   if r.result in {Result.OK.value, Result.NOT_FOUND.value})


# ---------------------------------------------------------------------------
# Holiday log
# ---------------------------------------------------------------------------

class HolidayLog:
    """Records weekdays where ALL applicable sources returned 404."""

    def __init__(self, path: Path):
        self.path = path
        self._dates: set[str] = set()
        if path.exists():
            with path.open() as fp:
                for line in fp:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        self._dates.add(json.loads(line)["date"])
                    except (json.JSONDecodeError, KeyError):
                        pass

    def record(self, d: date, sources_attempted: list[Source]) -> None:
        if d.isoformat() in self._dates:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as fp:
            fp.write(json.dumps({
                "date": d.isoformat(),
                "weekday": d.strftime("%A"),
                "sources_attempted": [s.value for s in sources_attempted],
                "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }) + "\n")
        self._dates.add(d.isoformat())


# ---------------------------------------------------------------------------
# Atomic write
# ---------------------------------------------------------------------------

def atomic_write_bytes(path: Path, body: bytes) -> str:
    """Write `body` to `path` atomically. Returns sha256 hex digest."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    sha = hashlib.sha256(body).hexdigest()
    with tmp.open("wb") as fp:
        fp.write(body)
        fp.flush()
        os.fsync(fp.fileno())
    os.replace(tmp, path)
    return sha


# ---------------------------------------------------------------------------
# Downloader
# ---------------------------------------------------------------------------

class HaltedError(Exception):
    """Raised when NSE returns a halt-status (403/429/401). Caller decides whether
    to abort the run; the checkpoint records the failure."""


@dataclass
class DownloadConfig:
    output_root: Path
    rate_limit_seconds: float = 1.0
    timeout_seconds: int = 30
    era_boundary: date = DEFAULT_ERA_BOUNDARY
    overlap_days: int = 60
    headers: dict = field(default_factory=lambda: dict(DEFAULT_HEADERS))


class Downloader:
    def __init__(self, config: DownloadConfig, session: requests.Session | None = None):
        self.cfg = config
        self.session = session or requests.Session()
        self.checkpoint = Checkpoint(
            config.output_root / "processed" / "_download_checkpoint.jsonl"
        )
        self.holidays = HolidayLog(
            config.output_root / "processed" / "_holidays.jsonl"
        )
        self._last_request_at: float = 0.0

    def _throttle(self) -> None:
        elapsed = time.time() - self._last_request_at
        wait = self.cfg.rate_limit_seconds - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.time()

    def warmup(self) -> None:
        """Hit the NSE homepage so the session collects any required cookies."""
        try:
            self.session.get(
                "https://www.nseindia.com/",
                headers=self.cfg.headers,
                timeout=self.cfg.timeout_seconds,
            )
        except requests.RequestException as e:
            log.warning("warmup failed (continuing): %r", e)

    def _url_for(self, source: Source, d: date) -> str:
        if source is Source.LEGACY:
            return legacy_url(d)
        if source is Source.MTO:
            return mto_url(d)
        if source is Source.UNIFIED:
            return unified_url(d)
        raise ValueError(source)

    def fetch_one(self, d: date, source: Source) -> CheckpointRow:
        """Fetch a single (date, source). Idempotent w.r.t. checkpoint.

        Returns the CheckpointRow that was (or would have been) appended.
        Caller is responsible for appending it via `self.checkpoint.append`.
        """
        url = self._url_for(source, d)
        last_error: str | None = None
        last_status: int | None = None
        for attempt_idx, backoff in enumerate(RETRY_BACKOFF, start=1):
            self._throttle()
            try:
                resp = self.session.get(
                    url, headers=self.cfg.headers, timeout=self.cfg.timeout_seconds
                )
                last_status = resp.status_code
                if resp.status_code in HALT_STATUSES:
                    return CheckpointRow(
                        date=d.isoformat(), source=source.value,
                        result=Result.HALTED.value, status=resp.status_code,
                        bytes=len(resp.content), sha256=None,
                        attempts=attempt_idx,
                        completed_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        error=f"halt status {resp.status_code}",
                    )
                if resp.status_code == 404:
                    return CheckpointRow(
                        date=d.isoformat(), source=source.value,
                        result=Result.NOT_FOUND.value, status=404,
                        bytes=0, sha256=None, attempts=attempt_idx,
                        completed_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    )
                if resp.status_code == 200 and resp.content:
                    out = output_path(self.cfg.output_root, source, d)
                    sha = atomic_write_bytes(out, resp.content)
                    return CheckpointRow(
                        date=d.isoformat(), source=source.value,
                        result=Result.OK.value, status=200,
                        bytes=len(resp.content), sha256=sha,
                        attempts=attempt_idx,
                        completed_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    )
                # Other statuses (5xx, or 200 with empty body) → retry.
                last_error = f"http {resp.status_code} body={len(resp.content)}"
            except requests.RequestException as e:
                last_error = repr(e)
            # Backoff before next attempt — but skip the last sleep.
            if attempt_idx < len(RETRY_BACKOFF):
                time.sleep(backoff)
        return CheckpointRow(
            date=d.isoformat(), source=source.value,
            result=Result.FAILED.value, status=last_status,
            bytes=0, sha256=None, attempts=len(RETRY_BACKOFF),
            completed_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            error=last_error,
        )

    def fetch_date(self, d: date) -> list[CheckpointRow]:
        """Fetch all applicable sources for a single date. Updates checkpoint
        and holiday log. Returns the rows that were written this call (skips
        excluded)."""
        sources = sources_for_date(d, self.cfg.era_boundary, self.cfg.overlap_days)
        rows_this_call: list[CheckpointRow] = []
        all_not_found = True
        any_attempted = False
        for source in sources:
            if self.checkpoint.is_done(d, source):
                continue
            any_attempted = True
            row = self.fetch_one(d, source)
            self.checkpoint.append(row)
            rows_this_call.append(row)
            if row.result == Result.HALTED.value:
                raise HaltedError(
                    f"NSE returned {row.status} on {d.isoformat()}/{source.value}; "
                    f"halting run. Inspect checkpoint and resume after manual review."
                )
            if row.result != Result.NOT_FOUND.value:
                all_not_found = False
        if any_attempted and all_not_found:
            self.holidays.record(d, sources)
        return rows_this_call

    def run(self, dates: Iterable[date]) -> dict:
        """Iterate dates in order, fetching each. Returns aggregate stats."""
        stats = {"dates_processed": 0, "rows_written": 0, "ok": 0,
                 "not_found": 0, "failed": 0, "skipped_already_done": 0}
        for d in dates:
            stats["dates_processed"] += 1
            try:
                rows = self.fetch_date(d)
            except HaltedError as e:
                log.error("HALTED: %s", e)
                stats["halted"] = True
                return stats
            for row in rows:
                stats["rows_written"] += 1
                if row.result == Result.OK.value:
                    stats["ok"] += 1
                elif row.result == Result.NOT_FOUND.value:
                    stats["not_found"] += 1
                else:
                    stats["failed"] += 1
            sources_today = sources_for_date(
                d, self.cfg.era_boundary, self.cfg.overlap_days
            )
            stats["skipped_already_done"] += sum(
                1 for s in sources_today if self.checkpoint.is_done(d, s)
                and CheckpointKey(d.isoformat(), s.value) not in {
                    CheckpointKey(r.date, r.source) for r in rows
                }
            )
        return stats


# ---------------------------------------------------------------------------
# Date iteration helpers
# ---------------------------------------------------------------------------

def weekday_range(start: date, end: date) -> list[date]:
    """All Mon-Fri dates in [start, end] inclusive."""
    out: list[date] = []
    cur = start
    while cur <= end:
        if cur.weekday() < 5:
            out.append(cur)
        cur += timedelta(days=1)
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="NSE bhavcopy / MTO / unified downloader (checkpointed)."
    )
    p.add_argument("--start", type=_parse_date, required=True,
                   help="Start date (YYYY-MM-DD), inclusive.")
    p.add_argument("--end", type=_parse_date, required=True,
                   help="End date (YYYY-MM-DD), inclusive.")
    p.add_argument("--output-root", type=Path,
                   default=Path("data"),
                   help="Output root directory (default: ./data)")
    p.add_argument("--rate-limit-seconds", type=float, default=1.0,
                   help="Minimum seconds between requests (default: 1.0)")
    p.add_argument("--timeout-seconds", type=int, default=30)
    p.add_argument("--no-warmup", action="store_true",
                   help="Skip the homepage warmup that collects NSE cookies.")
    p.add_argument("--verbose", "-v", action="count", default=0)
    args = p.parse_args(argv)

    level = logging.WARNING - 10 * args.verbose
    logging.basicConfig(level=max(level, logging.DEBUG),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.start > args.end:
        log.error("--start (%s) is after --end (%s)", args.start, args.end)
        return 2

    cfg = DownloadConfig(
        output_root=args.output_root,
        rate_limit_seconds=args.rate_limit_seconds,
        timeout_seconds=args.timeout_seconds,
    )
    dl = Downloader(cfg)
    if not args.no_warmup:
        dl.warmup()

    dates = weekday_range(args.start, args.end)
    log.info("downloading %d weekdays from %s to %s",
             len(dates), args.start, args.end)
    stats = dl.run(dates)
    log.info("done: %s", stats)
    print(json.dumps(stats, indent=2))
    return 0 if not stats.get("halted") else 1


if __name__ == "__main__":
    sys.exit(main())
