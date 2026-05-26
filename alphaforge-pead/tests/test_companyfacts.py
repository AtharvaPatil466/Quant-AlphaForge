"""Tests for the EDGAR Company Facts extractor.

These exercise the four engineering pre-commitments from
`research/PEAD_DESIGN.md` §2:

  - As-of date discipline (value_as_of selects latest filed ≤ as_of)
  - Fiscal alignment (rows keyed by (fy, fp))
  - EPS concept hierarchy (primary first, fallback if missing, never Basic)
  - Substrate window filter (period_end >= 2012-01-01)

Plus the substitution logging contract and a restatement scenario.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from extractors.companyfacts import (
    PRIMARY_CONCEPT,
    FALLBACK_CONCEPT,
    BANNED_CONCEPT,
    SUBSTRATE_START,
    parse_company_facts,
    write_cik_shard,
    value_as_of,
)


# --- fixture builders -----------------------------------------------------


def _unit_row(
    fy: int, fp: str, val: float, filed: str,
    end: str, form: str = "10-Q", start: str | None = None,
) -> dict:
    if start is None:
        # Default to a 90-day duration so the row classifies as
        # period_kind="quarterly". The 2026-05-17 §2.2 addendum requires
        # quarterly classification for value_as_of's default behavior.
        from datetime import date as _date, timedelta as _td
        end_d = _date.fromisoformat(end)
        start = (end_d - _td(days=90)).isoformat()
    return {
        "start": start, "end": end, "val": val, "accn": f"acc-{fy}-{fp}-{filed}",
        "fy": fy, "fp": fp, "form": form, "filed": filed, "frame": f"CY{fy}{fp}",
    }


def _facts(cik: int, primary: list[dict] | None = None,
           fallback: list[dict] | None = None,
           basic: list[dict] | None = None) -> dict:
    us_gaap = {}
    if primary is not None:
        us_gaap[PRIMARY_CONCEPT] = {"units": {"USD/shares": primary}}
    if fallback is not None:
        us_gaap[FALLBACK_CONCEPT] = {"units": {"USD/shares": fallback}}
    if basic is not None:
        # Banned concept; included to verify we don't accidentally read it.
        us_gaap[BANNED_CONCEPT] = {"units": {"USD/shares": basic}}
    return {"cik": cik, "entityName": "TestCo", "facts": {"us-gaap": us_gaap}}


# --- contract: concept hierarchy ------------------------------------------


def test_primary_concept_preferred():
    j = _facts(
        320193,
        primary=[_unit_row(2024, "Q2", 1.53, "2024-05-02", "2024-03-30")],
        fallback=[_unit_row(2024, "Q2", 9.99, "2024-05-02", "2024-03-30")],
    )
    rows, subs = parse_company_facts(j, ticker="AAPL")
    assert len(rows) == 1
    assert rows[0].concept == PRIMARY_CONCEPT
    assert rows[0].val == 1.53
    assert rows[0].substitution_level == 1
    assert subs == []


def test_fallback_when_primary_missing_for_fp():
    j = _facts(
        1,
        primary=[],
        fallback=[_unit_row(2024, "Q2", 1.10, "2024-05-02", "2024-03-30")],
    )
    rows, subs = parse_company_facts(j, ticker="X")
    assert len(rows) == 1
    assert rows[0].concept == FALLBACK_CONCEPT
    assert rows[0].substitution_level == 2
    assert len(subs) == 1
    assert subs[0]["ticker"] == "X"
    assert subs[0]["fy"] == 2024
    assert subs[0]["fp"] == "Q2"


def test_fallback_not_used_to_supplement_primary_within_same_fy_fp():
    """Even if the fallback exists for a fy/fp where primary also exists,
    we DO NOT mix the two. The primary's restatement chain stands alone."""
    j = _facts(
        1,
        primary=[
            _unit_row(2024, "Q2", 1.00, "2024-05-02", "2024-03-30"),
            _unit_row(2024, "Q2", 1.05, "2024-08-01", "2024-03-30", form="10-Q/A"),
        ],
        fallback=[
            _unit_row(2024, "Q2", 9.99, "2024-05-02", "2024-03-30"),
        ],
    )
    rows, subs = parse_company_facts(j, ticker="X")
    # Both primary rows kept (restatement chain), fallback ignored.
    assert len(rows) == 2
    assert all(r.concept == PRIMARY_CONCEPT for r in rows)
    assert subs == []


def test_basic_concept_never_read():
    """Even if Basic is the ONLY available concept, the parser drops the firm-quarter."""
    j = _facts(
        1,
        basic=[_unit_row(2024, "Q2", 1.10, "2024-05-02", "2024-03-30")],
    )
    rows, subs = parse_company_facts(j, ticker="X")
    assert rows == []
    assert subs == []


# --- contract: substrate window -------------------------------------------


def test_pre_substrate_rows_dropped():
    j = _facts(
        1,
        primary=[
            _unit_row(2011, "Q4", 1.00, "2012-02-01", "2011-12-31"),  # period_end < 2012-01-01
            _unit_row(2012, "Q1", 1.10, "2012-05-01", "2012-03-31"),  # eligible
        ],
    )
    rows, subs = parse_company_facts(j, ticker="X")
    assert len(rows) == 1
    assert rows[0].period_end >= SUBSTRATE_START


# --- contract: fiscal alignment + valid fp --------------------------------


def test_invalid_fp_dropped():
    j = _facts(
        1,
        primary=[
            _unit_row(2024, "Q2", 1.0, "2024-05-02", "2024-03-30"),
            _unit_row(2024, "CY", 4.0, "2024-12-31", "2024-12-31"),  # calendar aggregate, banned
        ],
    )
    rows, _ = parse_company_facts(j, ticker="X")
    fps = {r.fp for r in rows}
    assert fps == {"Q2"}


def test_fy_fp_keys_preserved():
    j = _facts(
        1,
        primary=[
            _unit_row(2023, "Q1", 0.5, "2023-05-01", "2023-03-31"),
            _unit_row(2023, "Q2", 0.6, "2023-08-01", "2023-06-30"),
            _unit_row(2023, "Q3", 0.7, "2023-11-01", "2023-09-30"),
            _unit_row(2023, "FY", 2.5, "2024-02-01", "2023-12-31", form="10-K"),
        ],
    )
    rows, _ = parse_company_facts(j, ticker="X")
    by_key = {(r.fy, r.fp) for r in rows}
    assert by_key == {(2023, "Q1"), (2023, "Q2"), (2023, "Q3"), (2023, "FY")}


# --- contract: as-of-date discipline (restatement scenario) ---------------


def test_value_as_of_returns_original_then_amendment(tmp_path):
    """Original 10-Q on 2024-05-02 with val=1.00; 10-Q/A on 2024-08-01 with
    val=1.05. value_as_of must return 1.00 between May and August, then 1.05."""
    j = _facts(
        1,
        primary=[
            _unit_row(2024, "Q2", 1.00, "2024-05-02", "2024-06-30"),
            _unit_row(2024, "Q2", 1.05, "2024-08-01", "2024-06-30", form="10-Q/A"),
        ],
    )
    rows, _ = parse_company_facts(j, ticker="X")
    shard = write_cik_shard(rows, tmp_path, cik=1)

    # Before either filing: None
    assert value_as_of(shard, "X", date(2024, 6, 30),
                       datetime(2024, 5, 1, tzinfo=timezone.utc)) is None
    # Between original filing and amendment: original value
    v_between = value_as_of(shard, "X", date(2024, 6, 30),
                            datetime(2024, 7, 15, tzinfo=timezone.utc))
    assert v_between == 1.00
    # On the amendment date: amended value
    v_after = value_as_of(shard, "X", date(2024, 6, 30),
                          datetime(2024, 8, 1, tzinfo=timezone.utc))
    assert v_after == 1.05
    # Long after: still amended value
    v_later = value_as_of(shard, "X", date(2024, 6, 30),
                          datetime(2025, 1, 1, tzinfo=timezone.utc))
    assert v_later == 1.05


def test_value_as_of_unknown_period_returns_none(tmp_path):
    j = _facts(1, primary=[_unit_row(2024, "Q2", 1.00, "2024-05-02", "2024-06-30")])
    rows, _ = parse_company_facts(j, ticker="X")
    shard = write_cik_shard(rows, tmp_path, cik=1)
    # Wrong period_end
    assert value_as_of(shard, "X", date(2023, 12, 31),
                       datetime(2025, 1, 1, tzinfo=timezone.utc)) is None
    # Wrong ticker
    assert value_as_of(shard, "Y", date(2024, 6, 30),
                       datetime(2025, 1, 1, tzinfo=timezone.utc)) is None


# --- contract: substitution log integrity ---------------------------------


def test_substitution_log_only_for_step_2():
    j = _facts(
        1,
        primary=[_unit_row(2024, "Q2", 1.0, "2024-05-02", "2024-06-30")],
        fallback=[_unit_row(2024, "Q3", 1.2, "2024-08-01", "2024-09-30")],
    )
    rows, subs = parse_company_facts(j, ticker="X")
    # Q2 via primary, Q3 via fallback (substitution)
    assert {(r.fy, r.fp, r.substitution_level) for r in rows} == {
        (2024, "Q2", 1), (2024, "Q3", 2)
    }
    assert len(subs) == 1
    assert (subs[0]["fy"], subs[0]["fp"]) == (2024, "Q3")


# --- sanity: row ordering -------------------------------------------------


def test_rows_sorted_by_period_end_then_filed():
    j = _facts(
        1,
        primary=[
            _unit_row(2024, "Q2", 1.05, "2024-08-01", "2024-06-30", form="10-Q/A"),
            _unit_row(2024, "Q1", 0.95, "2024-05-01", "2024-03-31"),
            _unit_row(2024, "Q2", 1.00, "2024-05-02", "2024-06-30"),
        ],
    )
    rows, _ = parse_company_facts(j, ticker="X")
    period_ends = [r.period_end for r in rows]
    assert period_ends == sorted(period_ends)
    # Within same period_end, sorted by filed
    q2 = [r for r in rows if r.fp == "Q2"]
    assert [r.filed for r in q2] == sorted([r.filed for r in q2])
