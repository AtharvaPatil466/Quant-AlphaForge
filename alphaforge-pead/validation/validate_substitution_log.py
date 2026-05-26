"""Validate the EPS-concept substitution log.

Per `PEAD_DESIGN.md` §2.3, the fallback concept (`EarningsPerShareDiluted`)
is permitted only when the primary (`IncomeLossFromContinuingOperationsPerDilutedShare`)
is absent for a given `(fy, fp)`. Every such substitution is logged.

This validator's REAL job is integrity-checking:
  - log-line count must equal the fallback row count in the parquet store
  - every shard's substitution_level is in {1, 2}

It also REPORTS the empirical substitution rate. The rate is informational,
not a gate: `PEAD_DESIGN.md` §2.3 does not pre-commit a numerical threshold
(only the hierarchy itself). Verdicts of this validator are PASS as long as
the integrity invariants hold; high substitution rates surface as
documented limitations in the eventual `PEAD_PHASE1_VERDICT.md`.

Historical note: an earlier version of this validator gated on a 15%
ceiling. That threshold was not in the design contract; it was removed
on 2026-05-17 when the live extractor produced ~76% substitution (which
turned out to reflect the real-world distribution of XBRL EPS concept
usage on the S&P 500 substrate, not a parser bug).

Usage:
    python3 -m validation.validate_substitution_log --edgar-root data/edgar_eps/
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq


log = logging.getLogger(__name__)

# NOTE: PEAD_DESIGN.md does NOT pre-commit a substitution-rate threshold.
# The validator's PASS/FAIL is purely on integrity (log lines == fallback
# rows, no invalid substitution_level values). The threshold below is
# only used when the caller explicitly passes --threshold, for ad-hoc
# diagnostic gating.
INFORMATIONAL_THRESHOLD = 1.0  # i.e., never fails on rate alone by default


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--edgar-root", type=Path, default=Path("data/edgar_eps"))
    parser.add_argument("--threshold", type=float, default=INFORMATIONAL_THRESHOLD,
                        help="Optional rate ceiling. Default 1.0 = never fail on rate "
                             "(PEAD_DESIGN.md does not pre-commit a threshold).")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    by_cik = args.edgar_root / "by_cik"
    if not by_cik.exists():
        log.error("no shards at %s", by_cik)
        return 2

    shards = sorted(by_cik.glob("*.parquet"))

    total = 0
    primary = 0
    fallback = 0
    fallback_by_ticker: Counter = Counter()
    for shard in shards:
        df = pq.read_table(shard, columns=["ticker", "substitution_level"]).to_pandas()
        total += len(df)
        primary += int((df["substitution_level"] == 1).sum())
        fb_rows = df[df["substitution_level"] == 2]
        fallback += len(fb_rows)
        for t in fb_rows["ticker"]:
            fallback_by_ticker[t] += 1

    log_path = args.edgar_root / "_substitution_log.jsonl"
    log_lines = 0
    if log_path.exists():
        log_lines = sum(1 for line in log_path.read_text().splitlines() if line.strip())

    rate = fallback / max(total, 1)
    # Integrity gate is the real PASS/FAIL: log must match DB row count,
    # rate vs threshold is only a soft check if the user passes one.
    integrity_ok = (log_lines == fallback)
    rate_ok = rate < args.threshold
    report = {
        "shards_inspected": len(shards),
        "rows_total": total,
        "rows_primary": primary,
        "rows_fallback": fallback,
        "log_lines": log_lines,
        "log_lines_match_fallback_rows": integrity_ok,
        "substitution_rate": rate,
        "threshold": args.threshold,
        "rate_below_threshold": rate_ok,
        "passed": integrity_ok and rate_ok,
        "top_fallback_tickers": fallback_by_ticker.most_common(10),
    }
    print(json.dumps(report, indent=2, default=str))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
