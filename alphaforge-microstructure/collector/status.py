"""Phase 0 status / readiness CLI.

Walks the data/ directory and reports a single human-readable summary of:
    - how many days of book + trade data are on disk
    - total snapshot/trade row counts
    - gap fraction in book coverage
    - whether the Phase 0 exit criteria are met

The four exit criteria, from research/MICROSTRUCTURE_DESIGN.md and CLAUDE.md:
    1. ≥30 days of collected data (90 preferred).
    2. Book snapshots match REST snapshots tick-for-tick (validation/book_snapshot_check.py).
    3. Temporal alignment between trade tape and book (validation/temporal_alignment.py).
    4. Gap fraction <0.1% of collection window.

This CLI checks #1 and #4 directly from disk. It cannot run #2 (needs a
live REST call) or #3 (needs to walk every trade) — those have dedicated
scripts. The intent is a quick "where am I in Phase 0" status check the
user can run any time during the 30-day accumulation window.

Usage:
    python3 -m collector.status --data-root data/
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone, date as date_t
from pathlib import Path

import pyarrow.parquet as pq


PHASE0_MIN_DAYS = 30
PHASE0_GOAL_DAYS = 90
PHASE0_MAX_GAP_FRACTION = 0.001


def _is_readable_parquet(p: Path) -> bool:
    """True if `p` has a valid parquet footer. The live collector's current
    hourly file has no footer until it rolls, so it must be skipped rather than
    crash the readiness scan."""
    try:
        pq.read_metadata(p)
        return True
    except Exception:
        return False


def _scan_table_dir(root: Path) -> dict:
    """Walk a YYYY-MM-DD/*.parquet tree, return per-table stats. Files that are
    not yet valid parquet (e.g. the live in-progress hourly file) are skipped
    and counted in ``skipped`` so the omission is visible, never silent."""
    if not root.exists():
        return {"days": [], "files": 0, "rows": 0, "skipped": 0}
    days = []
    total_files = 0
    total_rows = 0
    skipped = 0
    for day_dir in sorted(root.iterdir()):
        if not day_dir.is_dir():
            continue
        parquets = sorted(day_dir.glob("*.parquet"))
        if not parquets:
            continue
        day_rows = 0
        day_files = 0
        for p in parquets:
            if not _is_readable_parquet(p):
                skipped += 1
                continue
            day_rows += pq.read_metadata(p).num_rows
            day_files += 1
        if day_files == 0:
            continue
        days.append({"date": day_dir.name, "files": day_files, "rows": day_rows})
        total_files += day_files
        total_rows += day_rows
    return {"days": days, "files": total_files, "rows": total_rows, "skipped": skipped}


def _gap_fraction(book_root: Path) -> dict:
    """Compute total-gap-seconds / total-window-seconds from local_ts_ns deltas."""
    if not book_root.exists():
        return {"window_seconds": 0.0, "gap_seconds": 0.0, "gap_fraction": 0.0}

    import numpy as np

    ts_chunks = []
    for day_dir in sorted(book_root.iterdir()):
        if not day_dir.is_dir():
            continue
        for p in sorted(day_dir.glob("*.parquet")):
            if not _is_readable_parquet(p):
                continue  # live in-progress file — no footer yet
            t = pq.read_table(p, columns=["local_ts_ns"])
            ts_chunks.append(t.column("local_ts_ns").to_numpy())

    if not ts_chunks:
        return {"window_seconds": 0.0, "gap_seconds": 0.0, "gap_fraction": 0.0}

    ts = np.concatenate(ts_chunks)
    ts.sort()
    if len(ts) < 2:
        return {"window_seconds": 0.0, "gap_seconds": 0.0, "gap_fraction": 0.0}

    window_ns = int(ts[-1] - ts[0])
    deltas_ns = np.diff(ts)
    threshold_ns = 1_000_000_000  # 1 second
    gap_ns = int(deltas_ns[deltas_ns > threshold_ns].sum())
    fraction = gap_ns / window_ns if window_ns > 0 else 0.0
    return {
        "window_seconds": window_ns / 1e9,
        "gap_seconds": gap_ns / 1e9,
        "gap_fraction": fraction,
    }


def _explicit_gap_count(data_root: Path) -> int:
    p = data_root / "_gaps.jsonl"
    if not p.exists():
        return 0
    return sum(1 for line in p.read_text().splitlines() if line.strip())


def build_report(data_root: Path) -> dict:
    book = _scan_table_dir(data_root / "book_snapshots")
    trades = _scan_table_dir(data_root / "trades")
    gap = _gap_fraction(data_root / "book_snapshots")
    explicit_gaps = _explicit_gap_count(data_root)

    book_days = len(book["days"])
    trade_days = len(trades["days"])

    criteria = {
        "min_30_days_of_book_data": book_days >= PHASE0_MIN_DAYS,
        "goal_90_days_of_book_data": book_days >= PHASE0_GOAL_DAYS,
        "gap_fraction_under_0_1_pct": gap["gap_fraction"] < PHASE0_MAX_GAP_FRACTION,
    }
    not_yet_checked = {
        "book_matches_rest_snapshot": "run validation/book_snapshot_check.py",
        "trade_book_temporal_alignment": "run validation/temporal_alignment.py",
    }

    ready_minimum = (
        criteria["min_30_days_of_book_data"]
        and criteria["gap_fraction_under_0_1_pct"]
    )

    return {
        "data_root": str(data_root),
        "book": {
            "days": book_days,
            "files": book["files"],
            "rows": book["rows"],
            "first_day": book["days"][0]["date"] if book["days"] else None,
            "last_day": book["days"][-1]["date"] if book["days"] else None,
        },
        "trades": {
            "days": trade_days,
            "files": trades["files"],
            "rows": trades["rows"],
            "first_day": trades["days"][0]["date"] if trades["days"] else None,
            "last_day": trades["days"][-1]["date"] if trades["days"] else None,
        },
        "gaps": {**gap, "explicit_gap_events": explicit_gaps},
        "skipped_in_progress_files": book.get("skipped", 0) + trades.get("skipped", 0),
        "phase0_criteria": criteria,
        "phase0_not_yet_checked": not_yet_checked,
        "phase0_minimum_ready": ready_minimum,
    }


def _format_report(r: dict) -> str:
    lines: list[str] = []
    lines.append("=" * 60)
    lines.append(f"Phase 0 status — {r['data_root']}")
    lines.append("=" * 60)
    b = r["book"]
    t = r["trades"]
    lines.append(
        f"Book snapshots: {b['days']:>3} days, {b['rows']:>12,} rows "
        f"({b['first_day']} → {b['last_day']})"
    )
    lines.append(
        f"Trades       : {t['days']:>3} days, {t['rows']:>12,} rows "
        f"({t['first_day']} → {t['last_day']})"
    )
    g = r["gaps"]
    lines.append(
        f"Gaps         : {g['gap_seconds']:.1f}s of "
        f"{g['window_seconds']:.1f}s window "
        f"({g['gap_fraction']*100:.3f}% — threshold 0.1%) "
        f"| explicit events: {g['explicit_gap_events']}"
    )
    if r.get("skipped_in_progress_files"):
        lines.append(
            f"Skipped      : {r['skipped_in_progress_files']} in-progress "
            f"file(s) without a parquet footer (live collector writing)"
        )
    lines.append("")
    lines.append("Exit criteria:")
    for k, v in r["phase0_criteria"].items():
        mark = "[OK]" if v else "[--]"
        lines.append(f"  {mark} {k}")
    lines.append("")
    lines.append("Not checked by this CLI (run validators separately):")
    for k, v in r["phase0_not_yet_checked"].items():
        lines.append(f"  [?]  {k:42s} → {v}")
    lines.append("")
    verdict = "READY (minimum)" if r["phase0_minimum_ready"] else "NOT YET — keep collecting"
    lines.append(f"Verdict: {verdict}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args()

    report = build_report(args.data_root)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(_format_report(report))
    return 0 if report["phase0_minimum_ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
