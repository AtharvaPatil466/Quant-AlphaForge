"""Tests for ingest.validator."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from ingest import validator as V
from ingest.schema import COLUMNS, LEGACY_ERA, UNIFIED_ERA


# ---------------------------------------------------------------------------
# Fixtures: synthetic processed parquet
# ---------------------------------------------------------------------------

def _make_row(d: date, symbol: str, era: str = UNIFIED_ERA,
              deliv_pct: float | None = 80.0, series: str = "EQ") -> dict:
    return {
        "date": pd.Timestamp(d),
        "symbol": symbol,
        "series": series,
        "open": 100.0, "high": 105.0, "low": 99.0, "close": 102.0,
        "last": 102.0, "prev_close": 100.0,
        "volume": 10000, "value": 1_020_000.0,
        "num_trades": pd.NA if era == LEGACY_ERA else 50,
        "deliv_qty": 8000,
        "deliv_pct": deliv_pct,
        "source_era": era,
    }


@pytest.fixture
def processed_dir_complete(tmp_path: Path) -> Path:
    """A processed/ tree covering every weekday in Mon-Fri week 2024-01-08 to
    2024-01-12 with 100% DELIV_PER. No holidays in this window."""
    d = tmp_path / "processed"
    d.mkdir()
    rows = []
    for day in (8, 9, 10, 11, 12):
        rows.extend([
            _make_row(date(2024, 1, day), "RELIANCE"),
            _make_row(date(2024, 1, day), "TCS"),
        ])
    df = pd.DataFrame(rows)[list(COLUMNS)]
    df.to_parquet(d / "bhavcopy_2024.parquet", index=False)
    return tmp_path


@pytest.fixture
def processed_dir_with_gap(tmp_path: Path) -> Path:
    """Same as `_complete` but missing 2024-01-10 (Wed) — that's a data gap,
    not a known holiday."""
    d = tmp_path / "processed"
    d.mkdir()
    rows = []
    for day in (8, 9, 11, 12):  # skip 10
        rows.append(_make_row(date(2024, 1, day), "RELIANCE"))
    pd.DataFrame(rows)[list(COLUMNS)].to_parquet(
        d / "bhavcopy_2024.parquet", index=False
    )
    return tmp_path


@pytest.fixture
def processed_dir_with_low_deliv(tmp_path: Path) -> Path:
    """80% DELIV_PER coverage — fails the 95% gate."""
    d = tmp_path / "processed"
    d.mkdir()
    rows = []
    for day in (8, 9, 10, 11, 12):
        # 10 rows per day, 8 with deliv_pct, 2 NaN → 80%
        for i in range(10):
            rows.append(_make_row(
                date(2024, 1, day), f"SYM{i:02d}",
                deliv_pct=80.0 if i < 8 else None,
            ))
    pd.DataFrame(rows)[list(COLUMNS)].to_parquet(
        d / "bhavcopy_2024.parquet", index=False
    )
    return tmp_path


@pytest.fixture
def processed_dir_with_non_eq(tmp_path: Path) -> Path:
    """One row leaked through with SERIES != EQ — fails eq_only check."""
    d = tmp_path / "processed"
    d.mkdir()
    rows = [
        _make_row(date(2024, 1, 8), "RELIANCE"),
        _make_row(date(2024, 1, 8), "SOMEDEBT", series="GS"),  # leak
    ]
    pd.DataFrame(rows)[list(COLUMNS)].to_parquet(
        d / "bhavcopy_2024.parquet", index=False
    )
    return tmp_path


# ---------------------------------------------------------------------------
# Known-holiday reference data
# ---------------------------------------------------------------------------

def test_known_holidays_for_year_includes_fixed():
    out = V.known_holidays_for_year(2022)
    assert date(2022, 1, 26) in out   # Republic Day
    assert date(2022, 8, 15) in out   # Independence Day
    assert date(2022, 10, 2) in out   # Gandhi Jayanti
    assert date(2022, 12, 25) in out  # Christmas


def test_known_holidays_for_year_includes_variable():
    out = V.known_holidays_for_year(2024)
    assert date(2024, 3, 25) in out   # Holi 2024
    assert date(2024, 11, 1) in out   # Diwali 2024


def test_known_holidays_for_unknown_year_falls_back_to_fixed_only():
    out = V.known_holidays_for_year(2030)  # not in variable table
    # Fixed-date holidays still present.
    assert date(2030, 1, 26) in out
    assert date(2030, 12, 25) in out


# ---------------------------------------------------------------------------
# check_bhavcopy_coverage
# ---------------------------------------------------------------------------

def test_bhavcopy_coverage_passes_when_complete(processed_dir_complete: Path):
    df = V._load_processed_parquet(processed_dir_complete / "processed")
    r = V.check_bhavcopy_coverage(
        df,
        expected_start=date(2024, 1, 8),
        expected_end=date(2024, 1, 12),
        holiday_log_dates=set(),
    )
    assert r.status == V.Status.PASS.value
    assert r.metrics["expected_days"] == 5
    assert r.metrics["missing_count"] == 0


def test_bhavcopy_coverage_fails_on_gap(processed_dir_with_gap: Path):
    df = V._load_processed_parquet(processed_dir_with_gap / "processed")
    r = V.check_bhavcopy_coverage(
        df,
        expected_start=date(2024, 1, 8),
        expected_end=date(2024, 1, 12),
        holiday_log_dates=set(),
    )
    assert r.status == V.Status.FAIL.value
    assert r.metrics["missing_count"] == 1
    assert r.metrics["first_missing"] == "2024-01-10"


def test_bhavcopy_coverage_treats_known_holidays_as_expected_absent(
    processed_dir_with_gap: Path
):
    """If 2024-01-10 is in the holiday log, the gap is not a failure."""
    df = V._load_processed_parquet(processed_dir_with_gap / "processed")
    r = V.check_bhavcopy_coverage(
        df,
        expected_start=date(2024, 1, 8),
        expected_end=date(2024, 1, 12),
        holiday_log_dates={date(2024, 1, 10)},
    )
    assert r.status == V.Status.PASS.value
    assert r.metrics["expected_days"] == 4  # 5 - 1 holiday


def test_bhavcopy_coverage_no_data_fails(tmp_path: Path):
    r = V.check_bhavcopy_coverage(
        None, date(2024, 1, 8), date(2024, 1, 12), set()
    )
    assert r.status == V.Status.FAIL.value


def test_bhavcopy_coverage_skips_weekends_from_expected():
    """Weekends never count as expected trading days."""
    df = pd.DataFrame([_make_row(date(2024, 1, 8), "X")])[list(COLUMNS)]
    r = V.check_bhavcopy_coverage(
        df,
        expected_start=date(2024, 1, 6),   # Sat
        expected_end=date(2024, 1, 8),     # Mon
        holiday_log_dates=set(),
    )
    assert r.metrics["expected_days"] == 1  # only Monday counts


# ---------------------------------------------------------------------------
# check_eq_only
# ---------------------------------------------------------------------------

def test_eq_only_passes_when_all_eq(processed_dir_complete: Path):
    df = V._load_processed_parquet(processed_dir_complete / "processed")
    r = V.check_eq_only(df)
    assert r.status == V.Status.PASS.value


def test_eq_only_fails_on_non_eq_leak(processed_dir_with_non_eq: Path):
    df = V._load_processed_parquet(processed_dir_with_non_eq / "processed")
    r = V.check_eq_only(df)
    assert r.status == V.Status.FAIL.value
    assert r.metrics["non_eq_rows"] == 1
    assert "GS" in r.metrics["non_eq_series_counts"]


# ---------------------------------------------------------------------------
# check_holiday_log
# ---------------------------------------------------------------------------

def test_holiday_log_passes_when_known_holidays_present():
    # Synthesize a complete log: every known weekday holiday for the reference years.
    full: set[date] = set()
    for y in V.REFERENCE_HOLIDAY_YEARS:
        for d in V.known_holidays_for_year(y):
            if d.weekday() < 5:
                full.add(d)
    r = V.check_holiday_log(full)
    assert r.status == V.Status.PASS.value
    assert r.metrics["missing_count"] == 0


def test_holiday_log_fails_when_missing_known():
    """An empty empirical log fails — known holidays should appear there."""
    r = V.check_holiday_log(set())
    assert r.status == V.Status.FAIL.value
    assert r.metrics["missing_count"] > 0


def test_holiday_log_ignores_weekend_holidays():
    """A weekend-falling fixed holiday (Aug 15, 2010 was a Sunday) is NOT
    expected in the empirical log — it falls outside the weekday-scan."""
    aug_15_2010 = date(2010, 8, 15)
    assert aug_15_2010.weekday() == 6  # Sunday — sanity
    # Aug 15 2010 is in known_holidays_for_year(2010) but on Sunday.
    full: set[date] = set()
    for y in V.REFERENCE_HOLIDAY_YEARS:
        for d in V.known_holidays_for_year(y):
            if d.weekday() < 5:
                full.add(d)
    # full does not contain Aug 15 2010 because we filtered. But the check
    # also filters known→weekday, so it should still pass.
    r = V.check_holiday_log(full)
    assert r.status == V.Status.PASS.value


# ---------------------------------------------------------------------------
# check_deliv_pct_coverage
# ---------------------------------------------------------------------------

def test_deliv_pct_coverage_passes_at_100(processed_dir_complete: Path):
    df = V._load_processed_parquet(processed_dir_complete / "processed")
    r = V.check_deliv_pct_coverage(df, threshold=0.95)
    # Default (no universe) → WARN even when threshold met, because §2.8.8
    # mandates Nifty 500 ever-member scoping.
    assert r.status == V.Status.WARN.value
    assert r.metrics["coverage_fraction"] == pytest.approx(1.0)


def test_deliv_pct_coverage_fails_below_threshold(processed_dir_with_low_deliv: Path):
    df = V._load_processed_parquet(processed_dir_with_low_deliv / "processed")
    r = V.check_deliv_pct_coverage(df, threshold=0.95)
    assert r.status == V.Status.FAIL.value
    assert r.metrics["coverage_fraction"] == pytest.approx(0.80)


def test_deliv_pct_coverage_passes_with_universe(processed_dir_complete: Path):
    df = V._load_processed_parquet(processed_dir_complete / "processed")
    r = V.check_deliv_pct_coverage(
        df, threshold=0.95, universe={"RELIANCE", "TCS"}
    )
    assert r.status == V.Status.PASS.value
    assert "Nifty 500" in r.metrics["scope"]


def test_deliv_pct_coverage_fails_when_universe_disjoint(processed_dir_complete: Path):
    df = V._load_processed_parquet(processed_dir_complete / "processed")
    r = V.check_deliv_pct_coverage(
        df, threshold=0.95, universe={"NO_SUCH_SYMBOL"}
    )
    assert r.status == V.Status.FAIL.value


# ---------------------------------------------------------------------------
# check_disagreements_rate
# ---------------------------------------------------------------------------

def test_disagreements_rate_passes_when_no_file(processed_dir_complete: Path):
    df = V._load_processed_parquet(processed_dir_complete / "processed")
    r = V.check_disagreements_rate(
        df, processed_dir_complete / "processed" / "_disagreements.parquet"
    )
    # No file → interpreted as zero mismatches.
    assert r.status == V.Status.PASS.value
    assert r.metrics["disagreement_rows"] == 0


def test_disagreements_rate_passes_at_low_rate(tmp_path: Path):
    """1000 legacy rows, 5 disagreements → 0.5% → below 1% threshold."""
    d = tmp_path / "processed"
    d.mkdir()
    rows = [_make_row(date(2010, 1, 4), f"SYM{i}", era=LEGACY_ERA)
            for i in range(1000)]
    pd.DataFrame(rows)[list(COLUMNS)].to_parquet(
        d / "bhavcopy_2010.parquet", index=False
    )
    dis_rows = pd.DataFrame({
        "date": [pd.Timestamp(date(2010, 1, 4))] * 5,
        "symbol": [f"BAD{i}" for i in range(5)],
        "series": ["EQ"] * 5,
        "bhavcopy_volume": [100] * 5,
        "mto_quantity_traded": [101] * 5,
        "delta": [-1] * 5,
        "source_era": [LEGACY_ERA] * 5,
    })
    dis_path = d / "_disagreements.parquet"
    dis_rows.to_parquet(dis_path, index=False)

    df = V._load_processed_parquet(d)
    r = V.check_disagreements_rate(df, dis_path, threshold=0.01)
    assert r.status == V.Status.PASS.value
    assert r.metrics["rate"] == pytest.approx(5 / 1005)


def test_disagreements_rate_fails_above_threshold(tmp_path: Path):
    """100 legacy rows, 5 disagreements → ~4.8% → above 1% threshold."""
    d = tmp_path / "processed"
    d.mkdir()
    rows = [_make_row(date(2010, 1, 4), f"SYM{i}", era=LEGACY_ERA)
            for i in range(100)]
    pd.DataFrame(rows)[list(COLUMNS)].to_parquet(
        d / "bhavcopy_2010.parquet", index=False
    )
    dis_rows = pd.DataFrame({
        "date": [pd.Timestamp(date(2010, 1, 4))] * 5,
        "symbol": [f"BAD{i}" for i in range(5)],
        "series": ["EQ"] * 5,
        "bhavcopy_volume": [100] * 5,
        "mto_quantity_traded": [101] * 5,
        "delta": [-1] * 5,
        "source_era": [LEGACY_ERA] * 5,
    })
    dis_path = d / "_disagreements.parquet"
    dis_rows.to_parquet(dis_path, index=False)

    df = V._load_processed_parquet(d)
    r = V.check_disagreements_rate(df, dis_path, threshold=0.01)
    assert r.status == V.Status.FAIL.value


# ---------------------------------------------------------------------------
# Orchestrator + markdown
# ---------------------------------------------------------------------------

def test_run_phase0_validators_returns_all_checks(processed_dir_complete: Path):
    holiday_log = processed_dir_complete / "processed" / "_holidays.jsonl"
    # Synthesize a holiday log that satisfies the known-holiday cross-check.
    lines = []
    for y in V.REFERENCE_HOLIDAY_YEARS:
        for d in V.known_holidays_for_year(y):
            if d.weekday() < 5:
                lines.append(json.dumps({
                    "date": d.isoformat(), "weekday": d.strftime("%A"),
                    "sources_attempted": [], "recorded_at": "x",
                }))
    holiday_log.write_text("\n".join(lines) + "\n")

    paths = V.ValidatorPaths(
        processed_dir=processed_dir_complete / "processed",
        holiday_log=holiday_log,
        disagreements=processed_dir_complete / "processed" / "_disagreements.parquet",
    )
    results = V.run_phase0_validators(
        paths,
        expected_start=date(2024, 1, 8), expected_end=date(2024, 1, 12),
        universe={"RELIANCE", "TCS"},
    )
    # All seven criteria represented; five PASS, three SKIP (upstream blockers).
    assert len(results) == 8  # 5 active (including internal check) + 3 skipped
    status_counts = {}
    for r in results.values():
        status_counts[r.status] = status_counts.get(r.status, 0) + 1
    assert status_counts.get(V.Status.PASS.value, 0) >= 4
    assert status_counts.get(V.Status.SKIP.value, 0) == 3


def test_render_markdown_report_summarises(tmp_path: Path):
    results = {
        "a": V.CheckResult("a", V.Status.PASS.value, "ok"),
        "b": V.CheckResult("b", V.Status.FAIL.value, "broken",
                           errors=["err1", "err2"]),
        "c": V.CheckResult("c", V.Status.SKIP.value, "blocked"),
    }
    out_path = tmp_path / "report.md"
    text = V.render_markdown_report(results, out_path)
    assert "PASS" in text
    assert "FAIL" in text
    assert "SKIP" in text
    assert "broken" in text
    assert "Phase 0 NOT certified" in text
    assert out_path.read_text() == text
