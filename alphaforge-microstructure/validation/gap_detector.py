"""Inventory feed gaps in collected book data.

Two gap sources are inventoried:
    1. Explicit gap events written to _gaps.jsonl by the collector
       (resync events, connection drops).
    2. Implicit gaps inferred from book_snapshots: any two consecutive
       snapshots whose local_ts_ns differ by more than `--threshold-ms`
       are flagged.

The output is a JSON report with one entry per gap, the total
gap-duration in seconds, and the gap-duration as a fraction of the
inspected window.

Phase 0 exit criterion #4 requires the gap fraction < 0.1%.

Usage:
    python3 -m validation.gap_detector --start 2026-05-17 --end 2026-05-18
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date as date_t, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import numpy as np


def _load_range(folder: Path, start: date_t, end: date_t):
    tables = []
    d = start
    while d <= end:
        day_dir = folder / d.isoformat()
        if day_dir.exists():
            for p in sorted(day_dir.glob("*.parquet")):
                tables.append(pq.read_table(p, columns=["local_ts_ns"]))
        d += timedelta(days=1)
    if not tables:
        return None
    return pa.concat_tables(tables).to_pandas()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--start", type=date_t.fromisoformat, required=True)
    parser.add_argument("--end", type=date_t.fromisoformat, required=True)
    parser.add_argument("--threshold-ms", type=int, default=1000,
                        help="Inter-snapshot gap considered a feed gap (ms)")
    args = parser.parse_args()

    books = _load_range(args.data_root / "book_snapshots", args.start, args.end)
    if books is None:
        print("no book data in range", file=sys.stderr)
        return 2

    ts = np.sort(books["local_ts_ns"].to_numpy())
    deltas_ns = np.diff(ts)
    threshold_ns = args.threshold_ms * 1_000_000

    gap_mask = deltas_ns > threshold_ns
    gaps_ns = deltas_ns[gap_mask]
    gap_starts = ts[:-1][gap_mask]

    implicit_gaps = [
        {
            "start_ts_ns": int(s),
            "duration_ns": int(d),
            "duration_s": d / 1e9,
        }
        for s, d in zip(gap_starts, gaps_ns)
    ]

    # Read explicit gap log
    explicit_path = args.data_root / "_gaps.jsonl"
    explicit_gaps = []
    if explicit_path.exists():
        for line in explicit_path.read_text().splitlines():
            try:
                explicit_gaps.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    total_window_ns = int(ts[-1] - ts[0]) if len(ts) > 1 else 0
    total_gap_ns = int(gaps_ns.sum())
    gap_fraction = (total_gap_ns / total_window_ns) if total_window_ns > 0 else 0.0

    report = {
        "start": args.start.isoformat(),
        "end": args.end.isoformat(),
        "snapshots": int(len(ts)),
        "implicit_gaps": len(implicit_gaps),
        "explicit_gap_events": len(explicit_gaps),
        "total_window_seconds": total_window_ns / 1e9,
        "total_gap_seconds": total_gap_ns / 1e9,
        "gap_fraction": gap_fraction,
        "passed": gap_fraction < 0.001,
        "top_gaps": sorted(implicit_gaps, key=lambda g: -g["duration_s"])[:10],
    }
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
