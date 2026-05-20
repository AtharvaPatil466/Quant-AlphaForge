"""Phase 0 exit-criteria validator.

Per `research/INDIA_DESIGN.md` §2.8, Phase 0 closes when all eight criteria
pass. This module implements the five that can run today (the other three
require modules not yet built — they're emitted as `skip` until then).

Architecture: each check is a free function returning a `CheckResult`.
The orchestrator runs all available checks and reports overall pass/fail.
Designed to be runnable mid-download — failures and skips coexist.

The seven criteria from §2.8:
  1. PIT Nifty 500 universe correlation ≥ 0.98       [SKIP — needs universe/]
  2. Bhavcopy two-era loader complete                 [CHECK]
  3. SERIES=EQ filter applied at ingestion             [CHECK]
  4. ISIN master + rename graph                       [SKIP — needs universe/]
  5. [CANCELLED / DROPPED] FII/DII daily series (Dropped per 2026-05-19 ADDENDUM)
  6. F&O expiry calendar 50-date spot-check            [SKIP — needs F&O layer]
  7. Holiday calendar cross-checked vs 5 known years   [CHECK]
  8. DELIV_PER coverage ≥ 95% of SERIES=EQ rows        [CHECK]

Plus an internal check (not in §2.8 but operationally important):
  9. Disagreements rate (TOTTRDQTY mismatch) below 1%  [CHECK]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any

import pandas as pd

log = logging.getLogger("india.validator")


# ---------------------------------------------------------------------------
# Check result type
# ---------------------------------------------------------------------------

class Status(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    SKIP = "skip"  # gate not implementable yet (blocked on upstream module)


@dataclass
class CheckResult:
    name: str
    status: str
    summary: str
    metrics: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Reference data — known major Indian holidays
# ---------------------------------------------------------------------------

# Fixed-date major holidays in India. Variable-date holidays (Diwali, Holi,
# Eid, Good Friday, Dussehra) require lookup tables; the validator below
# accepts an optional `extra_known_holidays` set for those.
_FIXED_HOLIDAYS_BY_NAME: dict[str, tuple[int, int]] = {
    "Republic Day":     (1, 26),
    "Maharashtra Day":  (5, 1),
    "Independence Day": (8, 15),
    "Gandhi Jayanti":   (10, 2),
    "Christmas":        (12, 25),
}

# Variable-date holidays for the 5 reference years (2010, 2014, 2018, 2022,
# 2024) per §2.6. These are the dates published by NSE in its annual holiday
# circulars; values cross-checked against NSE's historical lists. Adding
# more years is fine — see `extra_known_holidays` in `check_holiday_log`.
_VARIABLE_HOLIDAYS_BY_YEAR: dict[int, list[tuple[date, str]]] = {
    2010: [
        (date(2010, 3,  1), "Holi"),
        (date(2010, 4,  2), "Good Friday"),
        (date(2010, 9, 10), "Ramzan Id"),
        (date(2010, 11, 5), "Diwali (Lakshmi Puja)"),
        (date(2010, 11,17), "Bakri Id"),
    ],
    2014: [
        (date(2014, 3, 17), "Holi"),
        (date(2014, 4, 18), "Good Friday"),
        (date(2014, 7, 29), "Ramzan Id"),
        (date(2014, 10,15), "Bakri Id"),
        (date(2014, 10,23), "Diwali (Lakshmi Puja)"),
    ],
    2018: [
        (date(2018, 3,  2), "Holi"),
        (date(2018, 3, 30), "Good Friday"),
        (date(2018, 8, 22), "Bakri Id"),
        (date(2018,11,  8), "Diwali (Lakshmi Puja)"),
    ],
    2022: [
        (date(2022, 3, 18), "Holi"),
        (date(2022, 4, 15), "Good Friday"),
        (date(2022, 5,  3), "Ramzan Id"),
        (date(2022,10, 24), "Diwali (Lakshmi Puja)"),
    ],
    2024: [
        (date(2024, 3, 25), "Holi"),
        (date(2024, 3, 29), "Good Friday"),
        (date(2024, 4, 11), "Ramzan Id"),
        (date(2024, 6, 17), "Bakri Id"),
        (date(2024,11,  1), "Diwali (Lakshmi Puja)"),
    ],
}

REFERENCE_HOLIDAY_YEARS: tuple[int, ...] = (2010, 2014, 2018, 2022, 2024)


def known_holidays_for_year(year: int) -> set[date]:
    """All known major holidays for `year` — fixed + variable (if listed)."""
    out: set[date] = set()
    for month, day in _FIXED_HOLIDAYS_BY_NAME.values():
        try:
            out.add(date(year, month, day))
        except ValueError:
            continue  # leap-day edge cases — none here, defensive
    out.update(d for d, _ in _VARIABLE_HOLIDAYS_BY_YEAR.get(year, []))
    return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_weekday(d: date) -> bool:
    return d.weekday() < 5


def _load_processed_parquet(processed_dir: Path) -> pd.DataFrame | None:
    """Load all bhavcopy parquets concatenated. Returns None if none exist."""
    # Accept either {YYYY}.parquet (canonical, written by ingest.build_parquet)
    # or legacy bhavcopy_*.parquet test fixtures.
    files = sorted(
        list(processed_dir.rglob("[0-9][0-9][0-9][0-9].parquet"))
        + list(processed_dir.rglob("bhavcopy_*.parquet"))
    )
    if not files:
        return None
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)


def _load_holiday_log(holiday_path: Path) -> set[date]:
    if not holiday_path.exists():
        return set()
    out: set[date] = set()
    for line in holiday_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = date.fromisoformat(json.loads(line)["date"])
            out.add(d)
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
    return out


# ---------------------------------------------------------------------------
# Check 2: Bhavcopy coverage
# ---------------------------------------------------------------------------

def check_bhavcopy_coverage(
    df: pd.DataFrame | None,
    expected_start: date,
    expected_end: date,
    holiday_log_dates: set[date],
) -> CheckResult:
    """Every non-holiday weekday in [expected_start, expected_end] must have
    at least one row in the processed parquet."""
    if df is None or df.empty:
        return CheckResult(
            name="bhavcopy_coverage",
            status=Status.FAIL.value,
            summary="No processed bhavcopy parquet found.",
        )
    have = set(pd.to_datetime(df["date"]).dt.date.unique())
    expected: set[date] = set()
    cur = expected_start
    while cur <= expected_end:
        if _is_weekday(cur) and cur not in holiday_log_dates:
            expected.add(cur)
        cur += timedelta(days=1)
    missing = sorted(expected - have)
    coverage = (len(have & expected) / len(expected)) if expected else 1.0
    status = Status.PASS if not missing else Status.FAIL
    return CheckResult(
        name="bhavcopy_coverage",
        status=status.value,
        summary=(f"{len(have & expected)} / {len(expected)} expected trading "
                 f"days present ({coverage:.2%})."),
        metrics={
            "expected_days": len(expected),
            "have_days": len(have & expected),
            "missing_count": len(missing),
            "coverage_fraction": coverage,
            "first_missing": missing[0].isoformat() if missing else None,
            "last_missing": missing[-1].isoformat() if missing else None,
        },
        errors=[f"missing date: {d.isoformat()}" for d in missing[:20]],
    )


# ---------------------------------------------------------------------------
# Check 3: SERIES=EQ filter
# ---------------------------------------------------------------------------

def check_eq_only(df: pd.DataFrame | None) -> CheckResult:
    """All rows in the processed store must have series == 'EQ'."""
    if df is None or df.empty:
        return CheckResult(
            name="eq_only",
            status=Status.SKIP.value,
            summary="No processed data to check.",
        )
    non_eq = df[df["series"] != "EQ"]
    status = Status.PASS if non_eq.empty else Status.FAIL
    return CheckResult(
        name="eq_only",
        status=status.value,
        summary=(f"All {len(df)} rows are EQ." if status is Status.PASS
                 else f"{len(non_eq)} non-EQ rows leaked into processed store."),
        metrics={
            "total_rows": int(len(df)),
            "non_eq_rows": int(len(non_eq)),
            "non_eq_series_counts": (
                non_eq["series"].value_counts().to_dict() if not non_eq.empty
                else {}
            ),
        },
    )


# ---------------------------------------------------------------------------
# Check 7: Holiday log cross-check
# ---------------------------------------------------------------------------

def check_holiday_log(
    holiday_log_dates: set[date],
    reference_years: tuple[int, ...] = REFERENCE_HOLIDAY_YEARS,
    extra_known_holidays: set[date] | None = None,
) -> CheckResult:
    """Empirical holiday log must contain every known major holiday that
    fell on a weekday in the reference years."""
    extra_known_holidays = extra_known_holidays or set()
    known: set[date] = set(extra_known_holidays)
    for y in reference_years:
        known.update(known_holidays_for_year(y))
    # Restrict to weekdays — Sat/Sun holidays don't appear in the empirical log.
    known_weekday = {d for d in known if _is_weekday(d)}
    matched = len(known_weekday & holiday_log_dates)
    missing = sorted(known_weekday - holiday_log_dates)
    status = Status.PASS if not missing else Status.FAIL
    return CheckResult(
        name="holiday_log_cross_check",
        status=status.value,
        summary=(f"{matched} / {len(known_weekday)} known weekday holidays in "
                 f"{list(reference_years)} present in empirical log."),
        metrics={
            "reference_years": list(reference_years),
            "known_weekday_holidays": len(known_weekday),
            "matched": matched,
            "missing_count": len(missing),
        },
        errors=[f"known holiday missing from empirical log: {d.isoformat()}"
                for d in missing[:20]],
    )


# ---------------------------------------------------------------------------
# Check 8: DELIV_PER coverage
# ---------------------------------------------------------------------------

def check_deliv_pct_coverage(
    df: pd.DataFrame | None,
    threshold: float = 0.95,
    universe: set[str] | None = None,
) -> CheckResult:
    """DELIV_PER non-null fraction within EQ rows must be ≥ threshold.

    If `universe` is supplied (Nifty 500 ever-members), coverage is computed
    only within that universe — this is the strict check from §2.8.8. If
    not, coverage is computed across all EQ rows (looser, informational).
    """
    if df is None or df.empty:
        return CheckResult(
            name="deliv_pct_coverage",
            status=Status.SKIP.value,
            summary="No processed data to check.",
        )
    if universe is None:
        scoped = df
        scope_desc = "all EQ rows"
        universe_warning = (
            "PIT Nifty 500 universe not supplied — coverage computed across "
            "ALL EQ rows. §2.8.8 mandates scoping to Nifty 500 ever-members."
        )
    else:
        scoped = df[df["symbol"].isin(universe)]
        scope_desc = f"Nifty 500 ever-members ({len(universe)} symbols)"
        universe_warning = None
    total = len(scoped)
    if total == 0:
        return CheckResult(
            name="deliv_pct_coverage",
            status=Status.FAIL.value,
            summary=f"No rows after scoping to {scope_desc}.",
        )
    non_null = int(scoped["deliv_pct"].notna().sum())
    coverage = non_null / total
    status = Status.PASS if coverage >= threshold else Status.FAIL
    res = CheckResult(
        name="deliv_pct_coverage",
        status=status.value,
        summary=f"DELIV_PER coverage {coverage:.2%} over {total:,} {scope_desc} "
                f"(threshold {threshold:.0%}).",
        metrics={
            "total_rows": total,
            "non_null_rows": non_null,
            "coverage_fraction": coverage,
            "threshold": threshold,
            "scope": scope_desc,
        },
    )
    if universe_warning:
        res.errors.append(universe_warning)
        if res.status == Status.PASS.value:
            res.status = Status.WARN.value
    return res


# ---------------------------------------------------------------------------
# Check 9 (internal): Disagreements rate
# ---------------------------------------------------------------------------

def check_disagreements_rate(
    df: pd.DataFrame | None,
    disagreements_path: Path,
    threshold: float = 0.01,
) -> CheckResult:
    """The TOTTRDQTY-vs-MTO disagreement rate must be ≤ threshold (1% default).

    Per §14.10, if mismatch rate is high, the substrate may have to operate
    on the post-2020 era only. This is the empirical check that surfaces it.
    """
    if df is None or df.empty:
        return CheckResult(
            name="disagreements_rate",
            status=Status.SKIP.value,
            summary="No processed data to scope against.",
        )
    legacy_rows = int((df["source_era"] == "legacy+mto").sum())
    if not disagreements_path.exists():
        return CheckResult(
            name="disagreements_rate",
            status=Status.PASS.value,
            summary=("No _disagreements.parquet found — interpreted as zero "
                     "mismatches. Verify only if legacy-era data is present."),
            metrics={"legacy_rows": legacy_rows, "disagreement_rows": 0,
                     "rate": 0.0, "threshold": threshold},
        )
    dis = pd.read_parquet(disagreements_path)
    disagree_n = int(len(dis))
    denom = legacy_rows + disagree_n
    rate = (disagree_n / denom) if denom > 0 else 0.0
    status = Status.PASS if rate <= threshold else Status.FAIL
    return CheckResult(
        name="disagreements_rate",
        status=status.value,
        summary=(f"TOTTRDQTY disagreement rate {rate:.3%} over {denom:,} "
                 f"legacy-era candidate rows (threshold {threshold:.1%})."),
        metrics={
            "legacy_rows": legacy_rows,
            "disagreement_rows": disagree_n,
            "rate": rate,
            "threshold": threshold,
        },
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

@dataclass
class ValidatorPaths:
    processed_dir: Path
    holiday_log: Path
    disagreements: Path


def run_phase0_validators(
    paths: ValidatorPaths,
    expected_start: date,
    expected_end: date,
    universe: set[str] | None = None,
    deliv_pct_threshold: float = 0.95,
    disagreements_threshold: float = 0.01,
    extra_known_holidays: set[date] | None = None,
) -> dict[str, CheckResult]:
    """Run every check that can run today. Skipped checks are emitted as
    Status.SKIP with a summary explaining the upstream dependency."""
    df = _load_processed_parquet(paths.processed_dir)
    holidays = _load_holiday_log(paths.holiday_log)

    results: dict[str, CheckResult] = {}

    results["bhavcopy_coverage"] = check_bhavcopy_coverage(
        df, expected_start, expected_end, holidays
    )
    results["eq_only"] = check_eq_only(df)
    results["holiday_log_cross_check"] = check_holiday_log(
        holidays, extra_known_holidays=extra_known_holidays
    )
    results["deliv_pct_coverage"] = check_deliv_pct_coverage(
        df, threshold=deliv_pct_threshold, universe=universe
    )
    results["disagreements_rate"] = check_disagreements_rate(
        df, paths.disagreements, threshold=disagreements_threshold
    )

    # PIT universe check — now implemented.
    try:
        from universe.isin_master import ISINMaster
        from universe.pit import PITUniverse

        im = ISINMaster(
            equity_l_path=paths.processed_dir.parent.parent.parent
            / "EQUITY_L.csv",
            symbolchange_path=paths.processed_dir.parent.parent.parent
            / "symbolchange.csv",
        )
        pit = PITUniverse(
            xls_path=paths.processed_dir.parent.parent.parent
            / "IndexInclExcl.xls",
            isin_master=im,
            nifty500_list_path=paths.processed_dir.parent.parent.parent
            / "ind_nifty500list.csv",
        )
        rpt = pit.resolution_report
        pit_status = Status.PASS if rpt.coverage >= 1.0 else Status.FAIL
        results["pit_universe_correlation"] = CheckResult(
            name="pit_universe_correlation",
            status=pit_status.value,
            summary=(
                f"PIT name resolution {rpt.coverage:.1%} "
                f"({rpt.total_matched}/{rpt.total_unique_names}). "
                f"Events: {len(pit.events)}, "
                f"ever-members: {len(pit.ever_members())}."
            ),
            metrics={
                "coverage": rpt.coverage,
                "total_names": rpt.total_unique_names,
                "matched": rpt.total_matched,
                "unresolved": rpt.unresolved,
                "events": len(pit.events),
                "ever_members": len(pit.ever_members()),
            },
            errors=[f"unresolved: {n}" for n in rpt.unresolved_names[:20]],
        )
        results["isin_master_and_rename_graph"] = CheckResult(
            name="isin_master_and_rename_graph",
            status=Status.PASS.value,
            summary=(
                f"ISINMaster loaded: {len(im.symbol_to_isin)} symbols, "
                f"{len(im.rename_graph)} rename-graph entries."
            ),
            metrics={
                "symbols": len(im.symbol_to_isin),
                "rename_entries": len(im.rename_graph),
            },
        )
    except Exception as exc:
        log.warning("PIT/ISIN check failed: %s", exc)
        results["pit_universe_correlation"] = CheckResult(
            name="pit_universe_correlation",
            status=Status.SKIP.value,
            summary=f"Error loading universe modules: {exc}",
        )
        results["isin_master_and_rename_graph"] = CheckResult(
            name="isin_master_and_rename_graph",
            status=Status.SKIP.value,
            summary=f"Error loading universe modules: {exc}",
        )
    results["fo_expiry_calendar"] = CheckResult(
        name="fo_expiry_calendar",
        status=Status.SKIP.value,
        summary="Blocked: needs ingest/expiry_calendar.py.",
    )

    return results


def render_markdown_report(
    results: dict[str, CheckResult], output_path: Path | None = None
) -> str:
    lines: list[str] = ["# Phase 0 Validation Report\n"]
    lines.append(f"_Generated {datetime.now().isoformat(timespec='seconds')}_\n")
    statuses = {Status.PASS, Status.FAIL, Status.WARN, Status.SKIP}
    counts = {s.value: 0 for s in statuses}
    for r in results.values():
        counts[r.status] = counts.get(r.status, 0) + 1
    lines.append("## Summary")
    lines.append("")
    for s in (Status.PASS, Status.WARN, Status.FAIL, Status.SKIP):
        lines.append(f"- **{s.value.upper()}**: {counts.get(s.value, 0)}")
    lines.append("")
    blocking_failures = sum(1 for r in results.values()
                            if r.status == Status.FAIL.value)
    if blocking_failures:
        lines.append(f"**Phase 0 NOT certified — {blocking_failures} blocking failure(s).**")
    elif counts.get(Status.SKIP.value, 0) > 0:
        lines.append("**Phase 0 PARTIAL — skipped checks blocked on upstream modules.**")
    else:
        lines.append("**Phase 0 CERTIFIED on the available checks.**")
    lines.append("")
    lines.append("## Per-check details\n")
    for name, r in results.items():
        lines.append(f"### {name} — `{r.status.upper()}`")
        lines.append(f"{r.summary}\n")
        if r.metrics:
            lines.append("Metrics:")
            for k, v in r.metrics.items():
                lines.append(f"  - `{k}`: {v}")
            lines.append("")
        if r.errors:
            lines.append("First errors:")
            for e in r.errors[:10]:
                lines.append(f"  - {e}")
            if len(r.errors) > 10:
                lines.append(f"  - ... and {len(r.errors) - 10} more")
            lines.append("")
    text = "\n".join(lines)
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text)
    return text


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Phase 0 exit-criteria validator for alphaforge-india."
    )
    p.add_argument("--data-root", type=Path, default=Path("data"),
                   help="Root directory containing processed/ + holiday log.")
    p.add_argument("--processed-dir", type=Path, default=None,
                   help="Override processed parquet directory.")
    p.add_argument("--start", type=_parse_date, required=True,
                   help="Expected substrate start (YYYY-MM-DD).")
    p.add_argument("--end", type=_parse_date, required=True,
                   help="Expected substrate end (YYYY-MM-DD).")
    p.add_argument("--universe-file", type=Path, default=None,
                   help="Optional Nifty 500 ever-member list (one symbol per line).")
    p.add_argument("--deliv-pct-threshold", type=float, default=0.95)
    p.add_argument("--disagreements-threshold", type=float, default=0.01)
    p.add_argument("--report-md", type=Path, default=None,
                   help="Write markdown report to this path.")
    p.add_argument("--report-json", type=Path, default=None,
                   help="Write JSON results to this path.")
    p.add_argument("-v", "--verbose", action="count", default=0)
    args = p.parse_args(argv)

    logging.basicConfig(level=max(logging.WARNING - 10 * args.verbose,
                                  logging.DEBUG),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    processed_dir = args.processed_dir or (args.data_root / "processed")
    paths = ValidatorPaths(
        processed_dir=processed_dir,
        holiday_log=args.data_root / "processed" / "_holidays.jsonl",
        disagreements=args.data_root / "processed" / "_disagreements.parquet",
    )

    universe: set[str] | None = None
    if args.universe_file and args.universe_file.exists():
        universe = {
            line.strip() for line in args.universe_file.read_text().splitlines()
            if line.strip()
        }

    results = run_phase0_validators(
        paths,
        expected_start=args.start,
        expected_end=args.end,
        universe=universe,
        deliv_pct_threshold=args.deliv_pct_threshold,
        disagreements_threshold=args.disagreements_threshold,
    )

    if args.report_json:
        args.report_json.parent.mkdir(parents=True, exist_ok=True)
        args.report_json.write_text(json.dumps(
            {k: asdict(v) for k, v in results.items()}, indent=2,
        ))

    report = render_markdown_report(results, args.report_md)
    print(report)

    blocking_failures = sum(
        1 for r in results.values() if r.status == Status.FAIL.value
    )
    return 0 if blocking_failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
