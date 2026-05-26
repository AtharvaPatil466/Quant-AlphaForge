"""One-shot: add period_duration_days + period_kind columns to existing shards.

The 2026-05-17 parser fix added two derived columns to the schema. Shards
extracted before the fix lack them. This script reads each existing
shard, computes the columns from `start_date` and `end_date`, and writes
the shard back in place with the new schema.

Idempotent: shards already containing both columns are skipped.

Usage:
    python3 -m extractors.normalize_shards --edgar-root data/edgar_eps/
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .companyfacts import _classify_period, _schema


log = logging.getLogger(__name__)


def normalize_shard(shard_path: Path, dry_run: bool = False) -> dict:
    table = pq.read_table(shard_path)
    df = table.to_pandas()
    if df.empty:
        return {"path": str(shard_path), "rows": 0, "skipped": "empty"}

    have_kind = "period_kind" in df.columns
    have_dur = "period_duration_days" in df.columns
    if have_kind and have_dur:
        return {"path": str(shard_path), "rows": len(df), "skipped": "already_normalized"}

    durations = (pd.to_datetime(df["end_date"]) - pd.to_datetime(df["start_date"])).dt.days
    df["period_duration_days"] = durations.astype("int32")
    df["period_kind"] = df["period_duration_days"].apply(_classify_period)

    if dry_run:
        return {
            "path": str(shard_path), "rows": len(df), "skipped": "dry_run",
            "kind_counts": df["period_kind"].value_counts().to_dict(),
        }

    # Re-write with the canonical schema. The pylist conversion path
    # avoids type drift on the date32/timestamp columns.
    out = pa.Table.from_pylist(df.to_dict(orient="records"), schema=_schema())
    pq.write_table(out, shard_path, compression="zstd")
    return {
        "path": str(shard_path), "rows": len(df),
        "kind_counts": df["period_kind"].value_counts().to_dict(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--edgar-root", type=Path, default=Path("data/edgar_eps"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    by_cik = args.edgar_root / "by_cik"
    if not by_cik.exists():
        log.error("no shards at %s", by_cik)
        return 2

    shards = sorted(by_cik.glob("*.parquet"))
    log.info("normalizing %d shards (dry_run=%s)", len(shards), args.dry_run)

    n_normalized = 0
    n_skipped = 0
    kind_totals: dict[str, int] = {}
    for shard in shards:
        r = normalize_shard(shard, dry_run=args.dry_run)
        if r.get("skipped"):
            n_skipped += 1
        else:
            n_normalized += 1
        for k, v in (r.get("kind_counts") or {}).items():
            kind_totals[k] = kind_totals.get(k, 0) + int(v)

    log.info("done. normalized=%d skipped=%d", n_normalized, n_skipped)
    log.info("period_kind totals across all shards: %s", kind_totals)
    return 0


if __name__ == "__main__":
    sys.exit(main())
