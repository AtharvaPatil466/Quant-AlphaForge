"""Tests for ingest.expiry_calendar."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from ingest import expiry_calendar as E


# ---------------------------------------------------------------------------
# last_thursday_of_month — pure math
# ---------------------------------------------------------------------------

def test_last_thursday_january_2024():
    # Last Thursday of Jan 2024 = Jan 25, 2024.
    assert E.last_thursday_of_month(2024, 1) == date(2024, 1, 25)


def test_last_thursday_february_2024_leap():
    # Feb 2024 is a leap month. Feb 29 was a Thursday.
    assert E.last_thursday_of_month(2024, 2) == date(2024, 2, 29)


def test_last_thursday_december_2008():
    # Dec 2008: last day is Wed Dec 31. Previous Thursday = Dec 25.
    assert E.last_thursday_of_month(2008, 12) == date(2008, 12, 25)


def test_last_thursday_always_thursday():
    """Property: result is always a Thursday for every month in a wide range."""
    for y in (2004, 2010, 2018, 2024, 2030):
        for m in range(1, 13):
            d = E.last_thursday_of_month(y, m)
            assert d.weekday() == E.THURSDAY
            assert d.month == m
            # Must be in the last 7 days of the month.
            import calendar
            last_day = calendar.monthrange(y, m)[1]
            assert d.day >= last_day - 6


# ---------------------------------------------------------------------------
# expiry_for_month — holiday shift logic
# ---------------------------------------------------------------------------

def test_expiry_no_shift_when_thursday_clear():
    """No holidays → expiry == last Thursday."""
    assert E.expiry_for_month(2024, 1, frozenset()) == date(2024, 1, 25)


def test_expiry_shifts_to_wednesday_when_thursday_holiday():
    """Thursday is a holiday → Wednesday."""
    holidays = frozenset({date(2024, 1, 25)})  # synthetic
    assert E.expiry_for_month(2024, 1, holidays) == date(2024, 1, 24)


def test_expiry_shifts_to_tuesday_when_thursday_and_wednesday_holiday():
    """Both Thursday and Wednesday holidays → Tuesday."""
    holidays = frozenset({date(2024, 1, 25), date(2024, 1, 24)})
    assert E.expiry_for_month(2024, 1, holidays) == date(2024, 1, 23)


def test_expiry_skips_weekends_when_shifting_back():
    """If shifting back would land on a weekend, skip it (defensive)."""
    # Synthetic: Thu Oct 31 2024 is a holiday. Wed Oct 30 also a holiday.
    # Tue Oct 29 normal → expiry there.
    holidays = frozenset({date(2024, 10, 31), date(2024, 10, 30)})
    out = E.expiry_for_month(2024, 10, holidays)
    assert out == date(2024, 10, 29)
    assert out.weekday() == 1  # Tuesday


def test_expiry_shift_only_triggers_when_last_thursday_is_holiday():
    """Diwali 2014 was Thu Oct 23 — but the LAST Thursday of Oct 2014 was
    Oct 30. So no shift, even though a Thursday earlier in the month was
    a holiday. This is the exact scenario NSE schedules around."""
    holidays = frozenset({date(2014, 10, 23)})  # Diwali, mid-month Thursday
    assert E.expiry_for_month(2014, 10, holidays) == date(2014, 10, 30)


def test_expiry_raises_if_shift_escapes_month():
    """If every weekday in the month is a holiday, the shift escapes —
    caller's holiday set is wrong, not the algorithm. (This cannot happen
    with real NSE data; it's a defensive guard.)"""
    holidays = frozenset({
        date(2024, 6, d) for d in range(1, 31)
        if date(2024, 6, d).weekday() < 5
    })
    with pytest.raises(ValueError, match="escaped"):
        E.expiry_for_month(2024, 6, holidays)


# ---------------------------------------------------------------------------
# generate_calendar
# ---------------------------------------------------------------------------

def test_generate_calendar_one_month():
    rows = E.generate_calendar(2024, 1, 2024, 1, frozenset())
    assert len(rows) == 1
    assert rows[0].year == 2024
    assert rows[0].month == 1
    assert rows[0].expiry_date == date(2024, 1, 25)
    assert rows[0].shifted is False
    assert rows[0].shift_days == 0


def test_generate_calendar_spans_year_boundary():
    rows = E.generate_calendar(2023, 11, 2024, 2, frozenset())
    assert [(r.year, r.month) for r in rows] == [
        (2023, 11), (2023, 12), (2024, 1), (2024, 2)
    ]


def test_generate_calendar_records_shift_metadata():
    holidays = frozenset({date(2024, 1, 25)})
    rows = E.generate_calendar(2024, 1, 2024, 1, holidays)
    assert rows[0].shifted is True
    assert rows[0].shift_days == 1
    assert rows[0].expiry_date == date(2024, 1, 24)
    assert rows[0].canonical_last_thursday == date(2024, 1, 25)


def test_calendar_to_dataframe_schema():
    rows = E.generate_calendar(2024, 1, 2024, 3, frozenset())
    df = E.calendar_to_dataframe(rows)
    assert list(df.columns) == [
        "year", "month", "expiry_date", "canonical_last_thursday",
        "shifted", "shift_days",
    ]
    assert len(df) == 3


# ---------------------------------------------------------------------------
# load_holiday_set
# ---------------------------------------------------------------------------

def test_load_holiday_set_empty_file_returns_empty(tmp_path: Path):
    p = tmp_path / "h.jsonl"
    assert E.load_holiday_set(p) == frozenset()


def test_load_holiday_set_parses_well_formed(tmp_path: Path):
    p = tmp_path / "h.jsonl"
    p.write_text(
        json.dumps({"date": "2024-01-26", "weekday": "Friday"}) + "\n"
        + json.dumps({"date": "2024-03-25", "weekday": "Monday"}) + "\n"
    )
    out = E.load_holiday_set(p)
    assert out == frozenset({date(2024, 1, 26), date(2024, 3, 25)})


def test_load_holiday_set_skips_malformed(tmp_path: Path):
    p = tmp_path / "h.jsonl"
    p.write_text(
        "not-json\n"
        + json.dumps({"date": "2024-01-26"}) + "\n"
        + json.dumps({"no_date_key": "x"}) + "\n"
    )
    assert E.load_holiday_set(p) == frozenset({date(2024, 1, 26)})


# ---------------------------------------------------------------------------
# validate_expiry_calendar
# ---------------------------------------------------------------------------

def test_validate_calendar_all_match():
    rows = E.generate_calendar(2024, 1, 2024, 3, frozenset())
    reference = {
        (2024, 1): date(2024, 1, 25),
        (2024, 2): date(2024, 2, 29),
        (2024, 3): date(2024, 3, 28),
    }
    r = E.validate_expiry_calendar(rows, reference)
    assert r.passed is True
    assert r.total_checked == 3
    assert r.matched == 3


def test_validate_calendar_detects_mismatch():
    rows = E.generate_calendar(2024, 1, 2024, 1, frozenset())
    bad_reference = {(2024, 1): date(2024, 1, 30)}  # wrong on purpose
    r = E.validate_expiry_calendar(rows, bad_reference)
    assert r.passed is False
    assert r.mismatches[0][1] == date(2024, 1, 25)  # generated
    assert r.mismatches[0][2] == date(2024, 1, 30)  # reference


# ---------------------------------------------------------------------------
# Sanity: a quick run over 22 years produces 22*12 = 264 expiries
# ---------------------------------------------------------------------------

def test_generate_calendar_full_substrate():
    """Mirror the substrate window from INDIA_DESIGN.md §3."""
    rows = E.generate_calendar(2004, 1, 2026, 5, frozenset())
    # 22 full years + first 5 months of 2026 = 22*12 + 5 = 269 months.
    assert len(rows) == 22 * 12 + 5
    # Every expiry is a Thursday (no holidays in this test).
    assert all(r.expiry_date.weekday() == E.THURSDAY for r in rows)
