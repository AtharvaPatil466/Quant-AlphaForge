"""Tests for ingest.parser_unified — post-2020 unified bhavcopy."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest import parser_unified as U  # noqa: E402
from ingest.schema import COLUMNS, UNIFIED_ERA  # noqa: E402


def test_load_unified_strips_column_whitespace(unified_csv: Path):
    df = U.load_unified(unified_csv)
    # NSE ships this file with leading whitespace in column names.
    # The loader MUST strip — otherwise downstream lookups by name fail.
    assert "SYMBOL" in df.columns
    assert " SYMBOL" not in df.columns


def test_load_unified_rejects_missing_columns(tmp_path: Path):
    bad = tmp_path / "bad.csv"
    bad.write_text("FOO,BAR\n1,2\n")
    with pytest.raises(ValueError, match="missing required columns"):
        U.load_unified(bad)


def test_parse_unified_date_recognized_format():
    assert U._parse_unified_date("08-Jan-2024") == date(2024, 1, 8)


def test_parse_unified_date_rejects_unknown():
    with pytest.raises(ValueError):
        U._parse_unified_date("2024-01-08")


# ---------------------------------------------------------------------------
# parse_one_date
# ---------------------------------------------------------------------------

def test_parse_one_date_filters_to_eq(unified_csv: Path):
    r = U.parse_one_date(unified_csv)
    assert r.raw_rows == 4   # 3 EQ + 1 GS in fixture
    assert r.eq_rows == 3
    assert (r.df["series"] == "EQ").all()


def test_parse_one_date_returns_unified_schema(unified_csv: Path):
    r = U.parse_one_date(unified_csv)
    assert tuple(r.df.columns) == COLUMNS
    assert (r.df["source_era"] == UNIFIED_ERA).all()


def test_parse_one_date_converts_turnover_lacs_to_rupees(unified_csv: Path):
    r = U.parse_one_date(unified_csv)
    # RELIANCE: TURNOVER_LACS=25155.0 → value = 25155 * 100_000 = 2,515,500,000 INR.
    row = r.df[r.df["symbol"] == "RELIANCE"].iloc[0]
    assert row["value"] == pytest.approx(25155.0 * 100_000)


def test_parse_one_date_preserves_delivery_pct(unified_csv: Path):
    r = U.parse_one_date(unified_csv)
    # AARTIDRUGS row: DELIV_PER=75.00, DELIV_QTY=7500.
    row = r.df[r.df["symbol"] == "AARTIDRUGS"].iloc[0]
    assert row["deliv_pct"] == pytest.approx(75.0)
    assert row["deliv_qty"] == 7500


def test_parse_one_date_num_trades_populated(unified_csv: Path):
    r = U.parse_one_date(unified_csv)
    # Unlike legacy era, unified era HAS num_trades.
    assert r.df["num_trades"].notna().all()
    row = r.df[r.df["symbol"] == "RELIANCE"].iloc[0]
    assert row["num_trades"] == 5000


def test_parse_one_date_excludes_non_eq_deliv_pct_dash(unified_csv: Path):
    """The fixture's SOMEDEBT row has DELIV_PER='-'. After EQ filter it's
    gone entirely. This is what guarantees the 100% DELIV_PER coverage figure
    quoted in the spike test (spike-test finding 2)."""
    r = U.parse_one_date(unified_csv)
    assert "SOMEDEBT" not in set(r.df["symbol"])
    # All surviving rows have numeric deliv_pct.
    assert r.df["deliv_pct"].notna().all()
    assert (r.df["deliv_pct"] > 0).all()


def test_parse_one_date_extracts_date_from_date1_column(unified_csv: Path):
    r = U.parse_one_date(unified_csv)
    assert (r.df["date"] == pd.Timestamp("2024-01-08")).all()


# ---------------------------------------------------------------------------
# parse_year
# ---------------------------------------------------------------------------

def test_parse_year_writes_parquet(tmp_path: Path, unified_csv: Path):
    target_dir = tmp_path / "unified" / "2024" / "01"
    target_dir.mkdir(parents=True)
    (target_dir / unified_csv.name).write_text(unified_csv.read_text())

    out_path = tmp_path / "out" / "2024.parquet"
    stats = U.parse_year(unified_dir=tmp_path / "unified", out_path=out_path)
    assert stats["files"] == 1
    assert stats["rows"] == 3
    assert out_path.exists()
    df = pd.read_parquet(out_path)
    assert tuple(df.columns) == COLUMNS
    assert len(df) == 3
