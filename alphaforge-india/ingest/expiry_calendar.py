"""F&O monthly expiry calendar generator.

Per `research/INDIA_DESIGN.md` §2.6. NSE's monthly F&O expiry is the **last
Thursday of each month**, with two well-documented behaviors:

  1. If Thursday is a market holiday, expiry shifts BACKWARD by one
     trading day (Wednesday). If Wednesday is also a holiday, expiry
     shifts to Tuesday, and so on.
  2. The shift never crosses calendar-month boundaries — it cannot,
     because no Indian holiday calendar has ever knocked out the full
     last calendar week of a month.

The empirical holiday log (`data/processed/_holidays.jsonl`) is the source
of truth for "is this date a holiday." This module reads that log and
emits a Parquet file with one row per month: `(year, month, expiry_date,
shifted_from_thursday)`.

A 50-date spot-check against NSE's published expiry records is a Phase 0
exit criterion (§2.8.6). `validate_expiry_calendar` is the verification
function — pass it a reference set you've manually verified from NSE.
"""
from __future__ import annotations

import argparse
import calendar
import json
import logging
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

log = logging.getLogger("india.expiry_calendar")

THURSDAY = 3   # Python weekday code (Monday=0)


# ---------------------------------------------------------------------------
# Core algorithm
# ---------------------------------------------------------------------------

def last_thursday_of_month(year: int, month: int) -> date:
    """The mathematical last Thursday — before holiday adjustment."""
    last_day_num = calendar.monthrange(year, month)[1]
    d = date(year, month, last_day_num)
    while d.weekday() != THURSDAY:
        d -= timedelta(days=1)
    return d


def expiry_for_month(
    year: int, month: int, holiday_set: frozenset[date] | set[date]
) -> date:
    """Last Thursday, with backward holiday shift.

    Shifts backward one day at a time through any holidays (and weekends,
    defensively). Raises ValueError if the shift escapes the calendar
    month — that would indicate a holiday-set bug, not real data.
    """
    d = last_thursday_of_month(year, month)
    while d in holiday_set or d.weekday() >= 5:
        d -= timedelta(days=1)
        if d.month != month:
            raise ValueError(
                f"expiry shift escaped month {year}-{month:02d}: "
                f"landed on {d.isoformat()}. Holiday set may be wrong."
            )
    return d


# ---------------------------------------------------------------------------
# Calendar generation
# ---------------------------------------------------------------------------

@dataclass
class ExpiryRow:
    year: int
    month: int
    expiry_date: date
    canonical_last_thursday: date
    shifted: bool
    shift_days: int


def generate_calendar(
    start_year: int,
    start_month: int,
    end_year: int,
    end_month: int,
    holiday_set: frozenset[date] | set[date],
) -> list[ExpiryRow]:
    """Generate expiry rows for every month in [start, end] inclusive."""
    out: list[ExpiryRow] = []
    y, m = start_year, start_month
    while (y, m) <= (end_year, end_month):
        canonical = last_thursday_of_month(y, m)
        actual = expiry_for_month(y, m, holiday_set)
        out.append(ExpiryRow(
            year=y, month=m,
            expiry_date=actual,
            canonical_last_thursday=canonical,
            shifted=(actual != canonical),
            shift_days=(canonical - actual).days,
        ))
        m += 1
        if m == 13:
            m = 1
            y += 1
    return out


def calendar_to_dataframe(rows: list[ExpiryRow]) -> pd.DataFrame:
    return pd.DataFrame([{
        "year": r.year,
        "month": r.month,
        "expiry_date": pd.Timestamp(r.expiry_date),
        "canonical_last_thursday": pd.Timestamp(r.canonical_last_thursday),
        "shifted": r.shifted,
        "shift_days": r.shift_days,
    } for r in rows])


# ---------------------------------------------------------------------------
# Holiday-log loader (mirrors validator's; kept local to avoid coupling)
# ---------------------------------------------------------------------------

def load_holiday_set(holiday_log: Path) -> frozenset[date]:
    if not holiday_log.exists():
        return frozenset()
    out: set[date] = set()
    for line in holiday_log.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.add(date.fromisoformat(json.loads(line)["date"]))
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
    return frozenset(out)


# ---------------------------------------------------------------------------
# 50-date spot-check validation (Phase 0 exit gate §2.8.6)
# ---------------------------------------------------------------------------

@dataclass
class CalendarValidationResult:
    total_checked: int
    matched: int
    mismatches: list[tuple[date, date, date]]  # (canonical, generated, reference)

    @property
    def passed(self) -> bool:
        return not self.mismatches


def validate_expiry_calendar(
    generated_rows: list[ExpiryRow],
    reference: dict[tuple[int, int], date],
) -> CalendarValidationResult:
    """Compare generated calendar against a manually-verified NSE reference.

    `reference` maps (year, month) -> expiry_date as published by NSE.
    Returns a result with per-mismatch detail. Phase 0 exit requires 0
    mismatches on a ≥50-month reference set.
    """
    by_ym = {(r.year, r.month): r for r in generated_rows}
    mismatches: list[tuple[date, date, date]] = []
    checked = 0
    for (y, m), ref_date in reference.items():
        if (y, m) not in by_ym:
            mismatches.append((date(y, m, 1), date(y, m, 1), ref_date))
            checked += 1
            continue
        gen = by_ym[(y, m)]
        checked += 1
        if gen.expiry_date != ref_date:
            mismatches.append((
                gen.canonical_last_thursday, gen.expiry_date, ref_date
            ))
    return CalendarValidationResult(
        total_checked=checked,
        matched=checked - len(mismatches),
        mismatches=mismatches,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Generate NSE F&O monthly expiry calendar.")
    p.add_argument("--holiday-log", type=Path, required=True,
                   help="Path to empirical holiday log (_holidays.jsonl).")
    p.add_argument("--start", type=str, required=True,
                   help="Start YYYY-MM (inclusive).")
    p.add_argument("--end", type=str, required=True,
                   help="End YYYY-MM (inclusive).")
    p.add_argument("--out", type=Path, required=True,
                   help="Output Parquet path.")
    p.add_argument("--verbose", "-v", action="count", default=0)
    args = p.parse_args(argv)

    logging.basicConfig(level=max(logging.WARNING - 10 * args.verbose,
                                  logging.DEBUG),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    sy, sm = (int(x) for x in args.start.split("-"))
    ey, em = (int(x) for x in args.end.split("-"))
    holidays = load_holiday_set(args.holiday_log)
    log.info("loaded %d holidays from %s", len(holidays), args.holiday_log)

    rows = generate_calendar(sy, sm, ey, em, holidays)
    df = calendar_to_dataframe(rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(args.out, index=False)
    shifted_count = sum(r.shifted for r in rows)
    print(json.dumps({
        "months": len(rows),
        "shifted_expiries": shifted_count,
        "first": rows[0].expiry_date.isoformat() if rows else None,
        "last": rows[-1].expiry_date.isoformat() if rows else None,
        "output": str(args.out),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
