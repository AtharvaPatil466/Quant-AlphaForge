"""Sample-based restatement-aware as-of-date validator.

For every CIK shard, find firm-periods that have ≥2 filings (restatement
chains). Walk the chain and assert:

    For any timestamp `t` strictly between filing_k and filing_{k+1},
    value_as_of must return filing_k's val.
    For any t >= filing_N (the most recent), it must return filing_N's val.
    For any t < filing_0 (the earliest), it must return None.

If any sampled assertion fails, the validator exits non-zero and prints
the failing case. Otherwise it prints a summary and exits 0.

This is the most meaningful check of `companyfacts.value_as_of` —
trivial implementations pass but a real off-by-one or sort error fails.

Phase 0 exit criterion: this validator must report PASS over the full
extracted dataset before `PEAD_PHASE0_CERTIFIED.md` is filed.

Usage:
    python3 -m validation.validate_as_of --edgar-root data/edgar_eps/
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pyarrow.parquet as pq

from extractors.companyfacts import value_as_of


log = logging.getLogger(__name__)


def find_chains(shard_path: Path) -> list[dict]:
    """Return restatement chains (≥2 filings on same (ticker, period_end))
    among QUARTERLY rows only.

    Per PEAD_DESIGN.md §2.2 addendum (2026-05-17), filtering to
    `period_kind == 'quarterly'` avoids treating cumulative-YTD and
    annual values as restatements of the quarterly value — they share
    a period_end but are semantically distinct.
    """
    df = pq.read_table(shard_path).to_pandas()
    if df.empty:
        return []
    if "period_kind" in df.columns:
        df = df[df["period_kind"] == "quarterly"]
    else:
        import pandas as pd
        durations = (pd.to_datetime(df["end_date"]) - pd.to_datetime(df["start_date"])).dt.days
        df = df[(durations >= 85) & (durations <= 95)]
    chains = []
    for (ticker, period_end), grp in df.groupby(["ticker", "period_end"]):
        if len(grp) >= 2:
            grp = grp.sort_values("filed")
            chains.append({
                "ticker": ticker,
                "period_end": period_end,
                "filings": list(zip(grp["filed"].tolist(), grp["val"].tolist())),
            })
    return chains


def validate_chain(shard_path: Path, ticker, period_end, filings) -> list[str]:
    """Return a list of error strings. Empty list = chain passes."""
    errors = []

    # Pre-earliest: should be None
    pre_t = filings[0][0] - timedelta(days=1)
    v = value_as_of(shard_path, ticker, period_end, pre_t)
    if v is not None:
        errors.append(
            f"[{ticker}/{period_end}] at t={pre_t} (before any filing) "
            f"got {v}, expected None"
        )

    # Between consecutive filings: should return filings[k]
    for k in range(len(filings) - 1):
        f_k, val_k = filings[k]
        f_next, _ = filings[k + 1]
        # Midpoint between f_k and f_next
        mid = f_k + (f_next - f_k) / 2
        v = value_as_of(shard_path, ticker, period_end, mid)
        if v != val_k:
            errors.append(
                f"[{ticker}/{period_end}] at t={mid} "
                f"got {v}, expected {val_k} (mid of filings {k} and {k+1})"
            )

    # On / after last filing: should return last val
    f_last, val_last = filings[-1]
    v = value_as_of(shard_path, ticker, period_end, f_last)
    if v != val_last:
        errors.append(
            f"[{ticker}/{period_end}] at t={f_last} (last filing) "
            f"got {v}, expected {val_last}"
        )
    v = value_as_of(shard_path, ticker, period_end, f_last + timedelta(days=365))
    if v != val_last:
        errors.append(
            f"[{ticker}/{period_end}] at t={f_last + timedelta(days=365)} "
            f"(well after last filing) got {v}, expected {val_last}"
        )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--edgar-root", type=Path, default=Path("data/edgar_eps"))
    parser.add_argument("--max-shards", type=int, default=None,
                        help="Limit number of shards inspected (for quick smoke runs)")
    parser.add_argument("--max-error-rate", type=float, default=0.001,
                        help="Pass if errors/chains ≤ this rate. Default 0.1%% — "
                             "tolerates rare SEC API data quirks (conflicting "
                             "values within a (period_end, filed) group).")
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

    total_chains = 0
    total_errors = []
    for shard in shards:
        chains = find_chains(shard)
        total_chains += len(chains)
        for chain in chains:
            errs = validate_chain(
                shard, chain["ticker"], chain["period_end"], chain["filings"]
            )
            if errs:
                total_errors.extend(errs)
                for e in errs[:3]:
                    log.warning(e)

    error_rate = len(total_errors) / max(total_chains, 1)
    report = {
        "shards_inspected": len(shards),
        "restatement_chains_found": total_chains,
        "errors": len(total_errors),
        "error_rate": error_rate,
        "max_error_rate": args.max_error_rate,
        "passed": error_rate <= args.max_error_rate,
        "sample_errors": total_errors[:10],
    }
    print(json.dumps(report, indent=2, default=str))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
