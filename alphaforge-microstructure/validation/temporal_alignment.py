"""Validate trade tape timestamps against book snapshot timestamps.

For every trade in the collected data on a given day, find the book
snapshots immediately before and immediately after by exchange_ts_ns.
The trade's exchange_ts_ns MUST lie in [before_ts, after_ts].

If more than 0.01% of trades violate this, the collector's ordering is
broken and signal research cannot proceed. This is Phase 0 exit
criterion #3.

Usage:
    python3 -m validation.temporal_alignment --date 2026-05-18
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date as date_t
from pathlib import Path

import pyarrow.parquet as pq
import numpy as np


def _load_day(folder: Path, day: date_t):
    day_dir = folder / day.isoformat()
    if not day_dir.exists():
        return None
    tables = []
    for p in sorted(day_dir.glob("*.parquet")):
        tables.append(pq.read_table(p))
    if not tables:
        return None
    import pyarrow as pa
    return pa.concat_tables(tables).to_pandas()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--date", type=date_t.fromisoformat, required=True)
    parser.add_argument("--max-violation-rate", type=float, default=0.0001)
    args = parser.parse_args()

    books = _load_day(args.data_root / "book_snapshots", args.date)
    trades = _load_day(args.data_root / "trades", args.date)
    if books is None or trades is None:
        print("no data for date", file=sys.stderr)
        return 2

    book_ts = np.sort(books["exchange_ts_ns"].to_numpy())
    trade_ts = trades["exchange_ts_ns"].to_numpy()

    # For each trade, find the index of the book snapshot just before.
    idx = np.searchsorted(book_ts, trade_ts, side="right") - 1

    violations = 0
    # A trade is well-ordered if there is at least one book snapshot at or
    # before its timestamp. We can't check "after" reliably because the
    # very last trade of the day may legitimately have no after-snapshot.
    n_before = (idx >= 0).sum()
    violations += int((idx < 0).sum())  # trades that arrived before ANY book

    # Sanity: for trades with an after-snapshot, check the trade ts is
    # between before and after (allowing equality).
    has_after = idx < len(book_ts) - 1
    before = book_ts[np.where(idx >= 0, idx, 0)]
    after = book_ts[np.where(has_after, idx + 1, len(book_ts) - 1)]
    inverted = (trade_ts < before) | ((trade_ts > after) & has_after)
    violations += int(inverted[idx >= 0].sum())

    total = len(trade_ts)
    rate = violations / max(total, 1)
    report = {
        "date": args.date.isoformat(),
        "trades": int(total),
        "books": int(len(book_ts)),
        "violations": int(violations),
        "violation_rate": rate,
        "trades_before_any_book": int((idx < 0).sum()),
        "passed": rate <= args.max_violation_rate,
    }
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
