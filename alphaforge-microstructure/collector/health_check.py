#!/usr/bin/env python3
"""Collector health check — operational liveness monitor for Phase 0.

Distinct from `collector.status`, which reports *Phase 0 research readiness*
(row counts, gap fractions, exit criteria). This script answers one operational
question: **is the collector currently running and writing fresh data?**

Run manually at any time, or via cron every 5 minutes during the Phase 0
accumulation window (2026-05-17 → 2026-06-17):

    */5 * * * * cd /path/to/alphaforge-microstructure && python3 -m collector.health_check

Exit codes (standard monitoring convention):
    0 — OK        (last write ≤ 10 minutes ago, no hour-bucket gaps in past 24h)
    1 — WARNING   (last write 10–60 minutes ago, or ≤ 2 gaps in past 24h)
    2 — CRITICAL  (last write > 60 minutes ago, or > 2 gaps in past 24h,
                   or data directory entirely absent)

The thresholds mirror the collector's own HEARTBEAT_INTERVAL_SECONDS (60s)
and the FLUSH_INTERVAL_SECONDS (30s) from storage.py. A healthy collector
flushes every 30 seconds, so 10 minutes is already 20× the expected cadence
— a generous WARNING threshold.

Example output (healthy):
    === Microstructure Collector Health ===
    Status:     OK
    Last write: 2026-05-26 14:23:01 UTC (47s ago)
    Total rows: 14,823,441 (book: 9,201,312  trades: 5,622,129)
    Total size: 2.3 GB
    Data gaps:  none in last 24h
    Gaps file:  87 logged events in _gaps.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pyarrow.parquet as pq

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

# How old the most recently modified parquet file can be before we warn/crit.
WARN_AGE_SECONDS = 10 * 60   # 10 minutes
CRIT_AGE_SECONDS = 60 * 60   # 60 minutes

# How many missing hour-buckets in the last 24h trigger warning vs critical.
# Missing 1 bucket = one hour of outage; 3+ = CRITICAL.
WARN_GAP_BUCKETS = 1
CRIT_GAP_BUCKETS = 3

# The collector start date — used to calculate total accumulation days.
COLLECTION_START = datetime(2026, 5, 17, tzinfo=timezone.utc)

# Default data root (matches run_collector.py --out default).
DEFAULT_DATA_ROOT = Path("data")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_newest_parquet(root: Path) -> tuple[Path | None, float]:
    """Return (path, mtime_seconds) of the most recently modified .parquet file
    under *root*, or (None, 0.0) if none exist."""
    newest_path: Path | None = None
    newest_mtime = 0.0
    for p in root.rglob("*.parquet"):
        try:
            mtime = p.stat().st_mtime
        except OSError:
            continue
        if mtime > newest_mtime:
            newest_mtime = mtime
            newest_path = p
    return newest_path, newest_mtime


def _scan_rows(table_root: Path) -> int:
    """Count total rows across all parquet files under *table_root*."""
    if not table_root.exists():
        return 0
    total = 0
    for p in table_root.rglob("*.parquet"):
        try:
            meta = pq.read_metadata(p)
            total += meta.num_rows
        except Exception:
            pass
    return total


def _total_size_bytes(root: Path) -> int:
    """Recursively sum file sizes under *root* (parquet + jsonl)."""
    if not root.exists():
        return 0
    total = 0
    for p in root.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total


def _expected_book_buckets_last_24h(now: datetime) -> list[str]:
    """Return hour-bucket strings (YYYY-MM-DD/HH) for every UTC hour in [now-24h, now).

    The storage layout is:  book_snapshots/YYYY-MM-DD/HH.parquet
    So we enumerate exactly 24 bucket strings.
    """
    buckets = []
    # Walk backwards from the *completed* hour just before now.
    current = now.replace(minute=0, second=0, microsecond=0)
    for _ in range(24):
        current -= timedelta(hours=1)
        # Only include hours after the collector started.
        if current < COLLECTION_START:
            break
        buckets.append(f"{current.strftime('%Y-%m-%d')}/{current.strftime('%H')}")
    return buckets


def _find_missing_buckets(book_snapshots_root: Path, now: datetime) -> list[str]:
    """Return bucket strings that are expected but have no parquet file on disk."""
    expected = _expected_book_buckets_last_24h(now)
    missing = []
    for bucket in expected:
        day, hour = bucket.split("/")
        path = book_snapshots_root / day / f"{hour}.parquet"
        if not path.exists():
            missing.append(bucket)
    return missing


def _gap_event_count(data_root: Path) -> int:
    gaps_path = data_root / "_gaps.jsonl"
    if not gaps_path.exists():
        return 0
    try:
        lines = gaps_path.read_text().splitlines()
        return sum(1 for line in lines if line.strip())
    except OSError:
        return 0


def _fmt_bytes(n: int) -> str:
    for unit, threshold in [("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)]:
        if n >= threshold:
            return f"{n / threshold:.1f} {unit}"
    return f"{n} B"


def _fmt_age(age_seconds: float) -> str:
    if age_seconds < 60:
        return f"{int(age_seconds)}s ago"
    if age_seconds < 3600:
        return f"{int(age_seconds // 60)}m {int(age_seconds % 60)}s ago"
    hours = int(age_seconds // 3600)
    minutes = int((age_seconds % 3600) // 60)
    return f"{hours}h {minutes}m ago"


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

def run_health_check(
    data_root: Path,
    warn_age: int = WARN_AGE_SECONDS,
    crit_age: int = CRIT_AGE_SECONDS,
) -> dict:
    """Collect all health metrics and return a structured result dict."""
    now_utc = datetime.now(tz=timezone.utc)
    now_epoch = time.time()

    result: dict = {
        "data_root": str(data_root),
        "checked_at_utc": now_utc.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "data_root_exists": data_root.exists(),
    }

    # --- data root absent ---------------------------------------------------
    if not data_root.exists():
        result.update({
            "status": "CRITICAL",
            "exit_code": 2,
            "last_write_utc": None,
            "last_write_age_seconds": None,
            "book_rows": 0,
            "trade_rows": 0,
            "total_rows": 0,
            "total_size_bytes": 0,
            "missing_buckets_24h": [],
            "gap_events": 0,
            "detail": f"Data root {data_root} does not exist — collector never started?",
        })
        return result

    # --- last write timestamp -----------------------------------------------
    newest_path, newest_mtime = _find_newest_parquet(data_root)
    if newest_mtime == 0.0:
        age_seconds = float("inf")
        last_write_str = None
    else:
        age_seconds = now_epoch - newest_mtime
        last_write_str = datetime.fromtimestamp(newest_mtime, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )

    # --- row counts + disk size ---------------------------------------------
    book_rows = _scan_rows(data_root / "book_snapshots")
    trade_rows = _scan_rows(data_root / "trades")
    total_rows = book_rows + trade_rows
    total_bytes = _total_size_bytes(data_root)

    # --- gap detection: missing hour buckets in last 24h --------------------
    missing_buckets = _find_missing_buckets(data_root / "book_snapshots", now_utc)

    # --- gap events file ----------------------------------------------------
    gap_events = _gap_event_count(data_root)

    # --- determine overall status -------------------------------------------
    # CRITICAL if: no files at all, OR last write > 60 min, OR ≥3 missing buckets.
    # WARNING  if: last write 10–60 min, OR 1–2 missing buckets.
    # OK       otherwise.

    if newest_mtime == 0.0 or age_seconds > crit_age or len(missing_buckets) >= CRIT_GAP_BUCKETS:
        status = "CRITICAL"
        exit_code = 2
    elif age_seconds > warn_age or len(missing_buckets) >= WARN_GAP_BUCKETS:
        status = "WARNING"
        exit_code = 1
    else:
        status = "OK"
        exit_code = 0

    result.update({
        "status": status,
        "exit_code": exit_code,
        "last_write_utc": last_write_str,
        "last_write_age_seconds": round(age_seconds, 1) if age_seconds != float("inf") else None,
        "book_rows": book_rows,
        "trade_rows": trade_rows,
        "total_rows": total_rows,
        "total_size_bytes": total_bytes,
        "missing_buckets_24h": missing_buckets,
        "gap_events": gap_events,
    })
    return result


def _format_human(r: dict) -> str:
    """Render a human-readable health summary."""
    lines = ["=== Microstructure Collector Health ==="]

    status_line = r["status"]
    lines.append(f"{'Status:':<12}{status_line}")

    if r["last_write_utc"] is not None and r["last_write_age_seconds"] is not None:
        age_str = _fmt_age(r["last_write_age_seconds"])
        lines.append(f"{'Last write:':<12}{r['last_write_utc']} ({age_str})")
    else:
        lines.append(f"{'Last write:':<12}none found")

    total = r["total_rows"]
    book = r["book_rows"]
    trades = r["trade_rows"]
    lines.append(
        f"{'Total rows:':<12}{total:,} (book: {book:,}  trades: {trades:,})"
    )

    lines.append(f"{'Total size:':<12}{_fmt_bytes(r['total_size_bytes'])}")

    missing = r["missing_buckets_24h"]
    if missing:
        lines.append(f"{'Data gaps:':<12}{len(missing)} missing hour-bucket(s) in last 24h:")
        for b in missing:
            lines.append(f"              {b}")
    else:
        lines.append(f"{'Data gaps:':<12}none in last 24h")

    lines.append(
        f"{'Gaps file:':<12}{r['gap_events']} logged event(s) in _gaps.jsonl"
    )

    if not r["data_root_exists"]:
        lines.append(f"\nWARNING: data root '{r['data_root']}' does not exist.")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Health check for the BTC-USDT L2 live collector (Phase 0 monitoring).",
        epilog=(
            "Cron usage: */5 * * * * cd /path/to/alphaforge-microstructure "
            "&& python3 -m collector.health_check"
        ),
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=DEFAULT_DATA_ROOT,
        help=f"Root directory written by run_collector.py (default: {DEFAULT_DATA_ROOT})",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of human-readable summary",
    )
    parser.add_argument(
        "--warn-age",
        type=int,
        default=WARN_AGE_SECONDS,
        metavar="SECONDS",
        help=f"Age (seconds) of newest file that triggers WARNING (default: {WARN_AGE_SECONDS})",
    )
    parser.add_argument(
        "--crit-age",
        type=int,
        default=CRIT_AGE_SECONDS,
        metavar="SECONDS",
        help=f"Age (seconds) of newest file that triggers CRITICAL (default: {CRIT_AGE_SECONDS})",
    )
    args = parser.parse_args()

    result = run_health_check(
        args.data_root,
        warn_age=args.warn_age,
        crit_age=args.crit_age,
    )

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(_format_human(result))

    return result["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
