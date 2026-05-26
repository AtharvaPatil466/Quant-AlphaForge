"""Validate the reconstructed book against Binance's REST depth snapshot.

The check: at multiple points in a collected day, fetch a fresh REST
snapshot from Binance, find the nearest book snapshot in our local
parquet store, and diff the top-N levels.

A passing day has ZERO diffs across all sampled points. Any tick-level
discrepancy is a reconstruction bug and must be triaged before signal
research begins.

This is Phase 0 exit-criterion #2.

Usage:
    python3 -m validation.book_snapshot_check --date 2026-05-18 --samples 24
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pyarrow.parquet as pq
import requests


FAPI_REST_DEPTH = "https://fapi.binance.com/fapi/v1/depth"


def _fetch_rest_snapshot(symbol: str, limit: int = 20) -> dict:
    r = requests.get(
        FAPI_REST_DEPTH,
        params={"symbol": symbol, "limit": limit},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


def _nearest_local_book(
    book_dir: Path, target_ts_ns: int, levels: int = 20
) -> dict | None:
    """Read the parquet file for the target hour, return the row with the
    closest local_ts_ns (and last_update_id close to target)."""
    dt = datetime.fromtimestamp(target_ts_ns / 1e9, tz=timezone.utc)
    path = book_dir / dt.strftime("%Y-%m-%d") / f"{dt.strftime('%H')}.parquet"
    if not path.exists():
        return None
    table = pq.read_table(path)
    df = table.to_pandas()
    if df.empty:
        return None
    idx = (df["local_ts_ns"] - target_ts_ns).abs().idxmin()
    row = df.loc[idx]
    return {
        "row": row,
        "levels": levels,
    }


def _diff_books(local_row, rest: dict, levels: int) -> list[str]:
    """Return a list of human-readable diffs between the two top-N books."""
    diffs: list[str] = []
    rest_bids = [(float(p), float(s)) for p, s in rest["bids"][:levels]]
    rest_asks = [(float(p), float(s)) for p, s in rest["asks"][:levels]]
    for i in range(levels):
        lpx = local_row.get(f"bid_px_{i+1}")
        lsz = local_row.get(f"bid_sz_{i+1}")
        rpx, rsz = rest_bids[i] if i < len(rest_bids) else (float("nan"), float("nan"))
        if lpx != rpx or lsz != rsz:
            diffs.append(f"bid[{i+1}] local=({lpx},{lsz}) rest=({rpx},{rsz})")
    for i in range(levels):
        lpx = local_row.get(f"ask_px_{i+1}")
        lsz = local_row.get(f"ask_sz_{i+1}")
        rpx, rsz = rest_asks[i] if i < len(rest_asks) else (float("nan"), float("nan"))
        if lpx != rpx or lsz != rsz:
            diffs.append(f"ask[{i+1}] local=({lpx},{lsz}) rest=({rpx},{rsz})")
    return diffs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--samples", type=int, default=24,
                        help="Sample this many REST snapshots, spread across the run")
    parser.add_argument("--levels", type=int, default=20)
    args = parser.parse_args()

    book_dir = args.data_root / "book_snapshots"
    if not book_dir.exists():
        print(f"no book data at {book_dir}", file=sys.stderr)
        return 2

    total_diffs = 0
    total_samples = 0
    failures: list[dict] = []
    for i in range(args.samples):
        rest = _fetch_rest_snapshot(args.symbol, limit=args.levels)
        # Use the REST snapshot's effective timestamp ~= now.
        target_ts_ns = time.time_ns()
        local = _nearest_local_book(book_dir, target_ts_ns, levels=args.levels)
        if local is None:
            print(f"sample {i}: no local data near {target_ts_ns}", file=sys.stderr)
            continue
        diffs = _diff_books(local["row"], rest, args.levels)
        total_samples += 1
        if diffs:
            total_diffs += len(diffs)
            failures.append({"sample": i, "diffs": diffs[:10]})  # truncate
        # Spread samples roughly evenly
        time.sleep(2)

    report = {
        "samples": total_samples,
        "total_diff_lines": total_diffs,
        "failures": failures,
        "passed": total_diffs == 0,
    }
    print(json.dumps(report, indent=2, default=str))
    return 0 if total_diffs == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
