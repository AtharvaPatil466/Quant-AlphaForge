"""Cross-check live-collector trades against Binance Vision archive trades.

The live collector and the archive loader both write into
`data/trades/YYYY-MM-DD/HH.parquet` with the same schema. They derive
from different sources (WebSocket aggTrade stream vs daily archive ZIP)
and *should* agree on `agg_trade_id`, `price`, `size`, `is_buyer_maker`,
and `exchange_ts_ns` for every trade.

This module compares them on overlap days and flags any divergence. It
is Phase 0 trust-but-verify between the two paths. Run it once the live
collector has produced ≥1 day of data that also exists in the archive.

The expected output on a clean overlap is: "0 mismatches across N
trades." Any non-zero count is a data-quality bug in one of the two
ingest paths and must be triaged before signal research.

Usage:
    python3 -m validation.live_vs_archive \\
        --live-root data/ \\
        --archive-root data/ \\
        --date 2026-05-18
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date as date_t
from pathlib import Path
from typing import Optional

import pyarrow as pa
import pyarrow.parquet as pq
import numpy as np


def _load_trades_for_day(root: Path, day: date_t) -> Optional[pa.Table]:
    day_dir = root / "trades" / day.isoformat()
    if not day_dir.exists():
        return None
    files = sorted(day_dir.glob("*.parquet"))
    if not files:
        return None
    return pa.concat_tables([pq.read_table(p) for p in files])


def compare_trades(live_table: pa.Table, archive_table: pa.Table) -> dict:
    """Compare two trade tables on `agg_trade_id`. Returns mismatch summary.

    Live and archive both index by `agg_trade_id`. For every id present
    in BOTH, we assert price/size/is_buyer_maker/exchange_ts_ns identity.
    Trades present in only one are reported as `only_in_live` / `only_in_archive`.
    """
    live = live_table.to_pandas()
    archive = archive_table.to_pandas()

    live_ids = set(live["agg_trade_id"].tolist())
    archive_ids = set(archive["agg_trade_id"].tolist())
    common = live_ids & archive_ids
    only_live = live_ids - archive_ids
    only_archive = archive_ids - live_ids

    if not common:
        return {
            "live_rows": len(live),
            "archive_rows": len(archive),
            "common_ids": 0,
            "only_in_live": len(only_live),
            "only_in_archive": len(only_archive),
            "mismatches": 0,
            "passed": False,
            "reason": "no overlap on agg_trade_id",
        }

    live_indexed = live.set_index("agg_trade_id").loc[sorted(common)]
    archive_indexed = archive.set_index("agg_trade_id").loc[sorted(common)]

    mismatches: list[dict] = []
    for col in ("price", "size", "is_buyer_maker", "exchange_ts_ns"):
        diff_mask = live_indexed[col].values != archive_indexed[col].values
        n = int(np.count_nonzero(diff_mask))
        if n > 0:
            # Sample up to 5 mismatched ids for the report
            ids = live_indexed.index[diff_mask].tolist()[:5]
            samples = []
            for tid in ids:
                samples.append({
                    "agg_trade_id": int(tid),
                    "live": live_indexed.loc[tid, col].item() if hasattr(live_indexed.loc[tid, col], "item") else live_indexed.loc[tid, col],
                    "archive": archive_indexed.loc[tid, col].item() if hasattr(archive_indexed.loc[tid, col], "item") else archive_indexed.loc[tid, col],
                })
            mismatches.append({"column": col, "n_mismatched": n, "samples": samples})

    return {
        "live_rows": int(len(live)),
        "archive_rows": int(len(archive)),
        "common_ids": len(common),
        "only_in_live": len(only_live),
        "only_in_archive": len(only_archive),
        "mismatches": mismatches,
        "n_mismatched_total": sum(m["n_mismatched"] for m in mismatches),
        "passed": len(mismatches) == 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live-root", type=Path, default=Path("data"))
    parser.add_argument("--archive-root", type=Path, default=Path("data"))
    parser.add_argument("--date", type=date_t.fromisoformat, required=True)
    args = parser.parse_args()

    live = _load_trades_for_day(args.live_root, args.date)
    archive = _load_trades_for_day(args.archive_root, args.date)
    if live is None:
        print(f"no live data for {args.date}", file=sys.stderr)
        return 2
    if archive is None:
        print(f"no archive data for {args.date}", file=sys.stderr)
        return 2

    # NOTE: when --live-root and --archive-root point to the same directory
    # (the default), the loader can't distinguish the two sources because
    # both write to the same path. In that case this script effectively
    # compares the table to itself; a true cross-check requires the user
    # to write the two sources into separate output roots. Detect and
    # warn so users don't conclude a self-comparison is meaningful.
    if args.live_root == args.archive_root:
        print(
            "WARN: --live-root and --archive-root point to the same directory; "
            "results are a self-comparison. Re-run with separate output roots "
            "(e.g. data/live/ and data/archive/) for a true cross-check.",
            file=sys.stderr,
        )

    report = {
        "date": args.date.isoformat(),
        **compare_trades(live, archive),
    }
    print(json.dumps(report, indent=2, default=str))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
