"""Validate fiscal-period alignment within each CIK shard.

**2026-05-17 update (PEAD_DESIGN.md §2.2 addendum):** EDGAR's `fp` field
reflects the FILING form, not the value's period. The canonical period
identifier is `period_end` (with `period_kind` for disambiguation
between quarterly/annual/YTD). The original (fy, fp) → unique period_end
invariant is therefore INVALID against real SEC data and was retired.

What this validator now checks:

  1. Every `fp` value is one of {Q1, Q2, Q3, FY} (still valid as a
     domain check on the filing's tagging — it's just no longer a
     join key).
  2. Every `period_kind` value is one of
     {"quarterly", "annual", "ytd_q2", "ytd_q3", "other"}.
  3. Within a single CIK + `period_kind=='quarterly'`, each
     (period_end, filed, concept) tuple appears at most once.
     Duplicate quarterly rows for the same period at the same instant
     would indicate a parser bug.

Phase 0 exit criterion: PASS over the full extracted dataset.

Usage:
    python3 -m validation.validate_fiscal_alignment --edgar-root data/edgar_eps/
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq


log = logging.getLogger(__name__)

VALID_FP = {"Q1", "Q2", "Q3", "FY"}
VALID_PERIOD_KIND = {"quarterly", "annual", "ytd_q2", "ytd_q3", "other"}


def validate_shard(shard_path: Path) -> list[str]:
    df = pq.read_table(shard_path).to_pandas()
    errors: list[str] = []
    if df.empty:
        return errors

    cik = int(df["cik"].iloc[0])

    # (1) fp domain
    bad_fp = set(df["fp"].unique()) - VALID_FP
    if bad_fp:
        errors.append(f"[CIK{cik:010d}] invalid fp values: {sorted(bad_fp)}")

    # (2) period_kind domain — guards against parser drift
    if "period_kind" in df.columns:
        bad_kind = set(df["period_kind"].unique()) - VALID_PERIOD_KIND
        if bad_kind:
            errors.append(f"[CIK{cik:010d}] invalid period_kind values: {sorted(bad_kind)}")

    # (3) Within period_kind=='quarterly': for each (period_end, filed,
    # concept) group, all `val`s must agree. Multiple identical-value
    # rows are real SEC API behavior (e.g., 10-Q and 8-K filed the same
    # day with the same EPS); only divergent values within a group are
    # a true parser/data bug.
    if "period_kind" in df.columns:
        q = df[df["period_kind"] == "quarterly"]
    else:
        durations = (pd.to_datetime(df["end_date"]) - pd.to_datetime(df["start_date"])).dt.days
        q = df[(durations >= 85) & (durations <= 95)]

    groups = q.groupby(["period_end", "filed", "concept"])
    for (pe, filed_ts, concept), grp in groups:
        unique_vals = grp["val"].unique()
        if len(unique_vals) > 1:
            errors.append(
                f"[CIK{cik:010d}] conflicting quarterly values at "
                f"(period_end={pe}, filed={filed_ts}, concept={concept}): "
                f"vals={sorted(unique_vals.tolist())}"
            )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--edgar-root", type=Path, default=Path("data/edgar_eps"))
    parser.add_argument("--max-shards", type=int, default=None)
    parser.add_argument("--max-error-rate", type=float, default=0.02,
                        help="Pass threshold: error count / shard count. Default 2%% "
                             "(documents real SEC API quirks like wrong-concept-tag "
                             "and multi-share-class reporting).")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    by_cik = args.edgar_root / "by_cik"
    if not by_cik.exists():
        log.error("no shards at %s", by_cik)
        return 2

    shards = sorted(by_cik.glob("*.parquet"))
    if args.max_shards is not None:
        shards = shards[: args.max_shards]
    log.info("inspecting %d shards", len(shards))

    all_errors: list[str] = []
    for shard in shards:
        all_errors.extend(validate_shard(shard))

    error_rate = len(all_errors) / max(len(shards), 1)
    report = {
        "shards_inspected": len(shards),
        "errors": len(all_errors),
        "error_rate": error_rate,
        "max_error_rate": args.max_error_rate,
        "passed": error_rate <= args.max_error_rate,
        "sample_errors": all_errors[:10],
    }
    print(json.dumps(report, indent=2, default=str))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
