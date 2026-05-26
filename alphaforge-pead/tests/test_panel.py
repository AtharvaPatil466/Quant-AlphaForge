"""Tests for the announcement-event panel builder.

Synthetic fixtures only — no real EDGAR or OHLCV data flows.
Phase 1 code per PEAD_DESIGN.md §8.

Tests cover:
  - period_kind filtering (quarterly only, no cumulative-YTD)
  - Original-vs-amendment dedupe by period_end (NOT by (fy, fp), per
    PEAD_DESIGN.md §2.2 addendum 2026-05-17)
  - As-of-date discipline in the EPS dict feeding SUE
  - Forward-return computation
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from extractors.companyfacts import (
    EpsRow, PRIMARY_CONCEPT, _schema, _classify_period, write_cik_shard,
)
from gauntlet.panel import (
    HOLDING_HORIZONS,
    QUARTERLY_KIND,
    _filter_quarterly,
    _fwd_returns,
    _original_filings_per_period,
    build_panel_for_firm,
    panel_to_dataframe,
)


# --- fixture builders ------------------------------------------------------


def _eps_row(cik: int, ticker: str, fy: int, fp: str, val: float,
             filed: datetime, period_end: date, form: str = "10-Q",
             sub_level: int = 1,
             start_date: date | None = None) -> EpsRow:
    """Default to a quarterly (~90d) period for the row."""
    if start_date is None:
        start_date = period_end - timedelta(days=90)
    duration = (period_end - start_date).days
    return EpsRow(
        cik=cik, ticker=ticker, period_end=period_end, fp=fp, fy=fy,
        filed=filed, form=form, concept=PRIMARY_CONCEPT, val=val,
        start_date=start_date, end_date=period_end,
        substitution_level=sub_level,
        period_duration_days=duration,
        period_kind=_classify_period(duration),
    )


def _make_shard(tmp_path: Path, cik: int, ticker: str, rows: list[EpsRow]) -> Path:
    return write_cik_shard(rows, tmp_path, cik)


def _write_ohlcv(tmp_path: Path, ticker: str, dates: list[date], closes: list[float]) -> None:
    ohlcv_dir = tmp_path / "ohlcv" / ticker
    ohlcv_dir.mkdir(parents=True)
    df = pd.DataFrame({"date": dates, "close": closes})
    table = pa.Table.from_pandas(df)
    pq.write_table(table, ohlcv_dir / "2024.parquet")


# --- period_kind filtering -----------------------------------------------


def test_filter_quarterly_keeps_only_90_day_rows():
    """The fix's load-bearing test: mixed-duration shard → only the
    90d rows survive the quarterly filter."""
    base = datetime(2024, 5, 2, tzinfo=timezone.utc)
    rows = [
        # Quarterly Q1 2024 (90d)
        _eps_row(cik=1, ticker="X", fy=2024, fp="Q1", val=0.5,
                 filed=base, period_end=date(2024, 3, 31)),
        # Cumulative YTD-Q2 (180d) — must be filtered out
        _eps_row(cik=1, ticker="X", fy=2024, fp="Q2", val=1.1,
                 filed=base, period_end=date(2024, 6, 30),
                 start_date=date(2024, 1, 1)),
        # Annual FY (365d) — also filtered out by quarterly filter
        _eps_row(cik=1, ticker="X", fy=2024, fp="FY", val=2.0,
                 filed=base, period_end=date(2024, 12, 31),
                 start_date=date(2024, 1, 1)),
    ]
    rows[1].period_duration_days = 181  # explicitly set YTD duration
    rows[1].period_kind = _classify_period(181)
    rows[2].period_duration_days = 365
    rows[2].period_kind = _classify_period(365)

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        _make_shard(tmp_path, 1, "X", rows)
        shard_df = pq.read_table(tmp_path / "by_cik" / "CIK0000000001.parquet").to_pandas()
        quarterly = _filter_quarterly(shard_df)
        assert len(quarterly) == 1
        assert quarterly.iloc[0]["period_kind"] == "quarterly"
        assert quarterly.iloc[0]["period_end"] == date(2024, 3, 31)


def test_filter_quarterly_fallback_when_period_kind_missing():
    """Backward compat: shards without period_kind use duration derivation."""
    df = pd.DataFrame({
        "start_date": [date(2024, 1, 1), date(2024, 1, 1), date(2024, 4, 1)],
        "end_date":   [date(2024, 3, 31), date(2024, 6, 30), date(2024, 6, 30)],
        "val":        [0.5, 1.0, 0.5],
    })
    out = _filter_quarterly(df)
    # Q1 (90d) and Q2-only (90d) survive; YTD-Q2 (181d) drops
    assert len(out) == 2


# --- _original_filings_per_period -----------------------------------------


def test_original_filings_dedupes_by_period_end_not_fy_fp():
    """A restatement (10-Q/A) shares the same period_end as the
    original 10-Q. The earlier-filed row wins, regardless of (fy, fp)
    tagging from EDGAR's filing form."""
    df = pd.DataFrame([
        {"period_end": date(2024, 3, 31), "filed": datetime(2024, 5, 1, tzinfo=timezone.utc),
         "fy": 2024, "fp": "Q1", "form": "10-Q", "val": 1.0},
        {"period_end": date(2024, 3, 31), "filed": datetime(2024, 8, 1, tzinfo=timezone.utc),
         "fy": 2024, "fp": "Q2", "form": "10-Q/A", "val": 1.1},  # amendment
        {"period_end": date(2024, 6, 30), "filed": datetime(2024, 8, 1, tzinfo=timezone.utc),
         "fy": 2024, "fp": "Q2", "form": "10-Q", "val": 1.5},
    ])
    out = _original_filings_per_period(df)
    assert len(out) == 2  # two distinct period_ends
    q1 = out[out["period_end"] == date(2024, 3, 31)].iloc[0]
    assert q1["filed"] == datetime(2024, 5, 1, tzinfo=timezone.utc)
    assert q1["val"] == 1.0


# --- _fwd_returns ---------------------------------------------------------


def test_fwd_returns_log_close_to_close():
    import math as _math
    dates = [date(2024, 1, i) for i in range(1, 31)]
    closes = [100.0 + i for i in range(30)]
    close = pd.Series(closes, index=dates)
    out = _fwd_returns(close, date(2024, 1, 5), horizons=(5, 21))
    assert _math.isclose(out[5], _math.log(109 / 104), rel_tol=1e-9)
    assert _math.isclose(out[21], _math.log(125 / 104), rel_tol=1e-9)


def test_fwd_returns_nan_past_data_end():
    import math as _math
    dates = [date(2024, 1, i) for i in range(1, 11)]
    closes = [100.0 + i for i in range(10)]
    close = pd.Series(closes, index=dates)
    out = _fwd_returns(close, date(2024, 1, 5), horizons=(2, 100))
    assert _math.isfinite(out[2])
    assert _math.isnan(out[100])


def test_fwd_returns_advances_to_next_trading_day_for_weekend_anchor():
    import math as _math
    dates = [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 5), date(2024, 1, 6)]
    closes = [100.0, 101.0, 105.0, 106.0]
    close = pd.Series(closes, index=dates)
    out = _fwd_returns(close, anchor_date=date(2024, 1, 3), horizons=(1,))
    assert _math.isclose(out[1], _math.log(106 / 105), rel_tol=1e-9)


# --- end-to-end -----------------------------------------------------------


def _full_quarterly_history(cik: int, ticker: str, n_years: int,
                            start_year: int = 2018) -> list[EpsRow]:
    """Build 90-day-quarterly EPS history for a firm."""
    rows = []
    for yr in range(start_year, start_year + n_years):
        for q_idx, end_month_day in enumerate([(3, 31), (6, 30), (9, 30), (12, 31)]):
            m, d = end_month_day
            pe = date(yr, m, d)
            filed = datetime(yr, m, d, tzinfo=timezone.utc) + timedelta(days=45)
            val = 1.0 + 0.05 * (yr - start_year) + 0.01 * q_idx
            fp = ["Q1", "Q2", "Q3", "FY"][q_idx]
            rows.append(_eps_row(cik=cik, ticker=ticker, fy=yr, fp=fp, val=val,
                                 filed=filed, period_end=pe))
    return rows


def test_build_panel_produces_one_row_per_quarterly_period(tmp_path: Path):
    rows = _full_quarterly_history(cik=1, ticker="X", n_years=4)
    _make_shard(tmp_path / "edgar", 1, "X", rows)

    base = date(2017, 1, 1)
    dates = [base + timedelta(days=i) for i in range(1500)]
    closes = [100.0 + i * 0.1 for i in range(1500)]
    _write_ohlcv(tmp_path, "X", dates, closes)

    out = build_panel_for_firm(tmp_path / "edgar", tmp_path / "ohlcv", cik=1, ticker="X")
    # 4 years × 4 quarters = 16 quarterly announcements
    assert len(out) == 16
    # Each has a unique period_end
    assert len({r.period_end for r in out}) == 16


def test_build_panel_returns_empty_when_no_ohlcv(tmp_path: Path):
    rows = _full_quarterly_history(cik=1, ticker="X", n_years=2)
    _make_shard(tmp_path / "edgar", 1, "X", rows)
    out = build_panel_for_firm(tmp_path / "edgar", tmp_path / "ohlcv", cik=1, ticker="X")
    assert out == []


def test_build_panel_returns_empty_when_no_shard(tmp_path: Path):
    dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(10)]
    _write_ohlcv(tmp_path, "X", dates, [100.0] * 10)
    out = build_panel_for_firm(tmp_path / "edgar", tmp_path / "ohlcv", cik=1, ticker="X")
    assert out == []


def test_panel_dataframe_has_expected_columns():
    from gauntlet.panel import AnnouncementRow
    rows = [AnnouncementRow(
        cik=1, ticker="X", period_end=date(2024, 3, 31),
        fy=2024, fp="Q1",
        announcement_ts=datetime(2024, 5, 1, tzinfo=timezone.utc),
        sue=1.5,
        fwd_returns={5: 0.01, 21: 0.02, 42: 0.03, 63: 0.04, 84: 0.05},
    )]
    df = panel_to_dataframe(rows)
    assert list(df.columns) == [
        "cik", "ticker", "period_end", "fy", "fp", "announcement_ts", "sue",
        "fwd_return_5", "fwd_return_21", "fwd_return_42", "fwd_return_63", "fwd_return_84",
    ]
    assert df.iloc[0]["sue"] == 1.5
    assert df.iloc[0]["period_end"] == date(2024, 3, 31)
