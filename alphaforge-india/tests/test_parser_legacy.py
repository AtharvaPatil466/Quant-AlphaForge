"""Tests for ingest.parser_legacy — legacy bhavcopy + MTO join."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest import parser_legacy as L  # noqa: E402
from ingest.schema import COLUMNS, LEGACY_ERA  # noqa: E402


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def test_load_legacy_bhavcopy_returns_all_rows(legacy_bhavcopy_zip: Path):
    df = L.load_legacy_bhavcopy(legacy_bhavcopy_zip)
    assert len(df) == 5  # 4 EQ + 1 GS in fixture
    assert "SYMBOL" in df.columns
    assert "TIMESTAMP" in df.columns


def test_load_mto_filters_to_data_records(mto_dat: Path):
    df = L.load_mto(mto_dat)
    # Header lines (record_type != 20) must be excluded.
    assert (df["RECORD_TYPE"] == "20").all()
    assert len(df) == 5  # 4 EQ + 1 GS data rows
    assert {"SYMBOL", "SERIES", "QUANTITY_TRADED", "DELIV_QTY", "DELIV_PER"}.issubset(df.columns)


def test_load_mto_skips_malformed_rows(mto_dat_malformed: Path):
    df = L.load_mto(mto_dat_malformed)
    # 2 well-formed rows, 1 malformed skipped silently.
    assert len(df) == 2
    assert set(df["SYMBOL"]) == {"3IINFOTECH", "3MINDIA"}


def test_load_legacy_bhavcopy_rejects_missing_columns(tmp_path: Path):
    import zipfile
    bad = tmp_path / "bad.csv.zip"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("inner.csv", "FOO,BAR\n1,2\n")
    with pytest.raises(ValueError, match="missing required columns"):
        L.load_legacy_bhavcopy(bad)


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

def test_parse_legacy_timestamp_single_digit_day():
    assert L._parse_legacy_timestamp("1-APR-2008") == date(2008, 4, 1)


def test_parse_legacy_timestamp_two_digit_day():
    assert L._parse_legacy_timestamp("01-APR-2008") == date(2008, 4, 1)


def test_parse_legacy_timestamp_rejects_unknown_format():
    with pytest.raises(ValueError):
        L._parse_legacy_timestamp("2008-04-01")


# ---------------------------------------------------------------------------
# parse_one_date — the load-bearing function
# ---------------------------------------------------------------------------

def test_parse_one_date_filters_to_eq_only(legacy_bhavcopy_zip: Path, mto_dat: Path):
    r = L.parse_one_date(legacy_bhavcopy_zip, mto_dat)
    # Fixture has 4 EQ + 1 GS in each side. After EQ filter + inner join +
    # disagreement quarantine: 3 agreed, 1 disagreement, 0 GS in either output.
    assert (r.agreed["series"] == "EQ").all()
    assert "GS" not in set(r.agreed["series"].astype(str))


def test_parse_one_date_quarantines_qty_mismatches(
    legacy_bhavcopy_zip: Path, mto_dat: Path
):
    r = L.parse_one_date(legacy_bhavcopy_zip, mto_dat)
    # The DISAGREE row had bhav TOTTRDQTY=900, MTO QUANTITY_TRADED=1000.
    assert len(r.disagreements) == 1
    row = r.disagreements.iloc[0]
    assert row["symbol"] == "DISAGREE"
    assert row["bhavcopy_volume"] == 900
    assert row["mto_quantity_traded"] == 1000
    assert row["delta"] == -100


def test_parse_one_date_agreed_has_unified_schema(
    legacy_bhavcopy_zip: Path, mto_dat: Path
):
    r = L.parse_one_date(legacy_bhavcopy_zip, mto_dat)
    assert tuple(r.agreed.columns) == COLUMNS
    # source_era is the legacy tag.
    assert (r.agreed["source_era"] == LEGACY_ERA).all()
    # num_trades is missing in legacy era — NaN/NA.
    assert r.agreed["num_trades"].isna().all()


def test_parse_one_date_preserves_delivery_pct_correctly(
    legacy_bhavcopy_zip: Path, mto_dat: Path
):
    r = L.parse_one_date(legacy_bhavcopy_zip, mto_dat)
    # AARTIDRUGS: TOTTRDQTY=8747, DELIV_QTY=5000, DELIV_PER=57.16.
    row = r.agreed[r.agreed["symbol"] == "AARTIDRUGS"].iloc[0]
    assert row["volume"] == 8747
    assert row["deliv_qty"] == 5000
    assert row["deliv_pct"] == pytest.approx(57.16)


def test_parse_one_date_date_is_extracted_from_bhavcopy_timestamp(
    legacy_bhavcopy_zip: Path, mto_dat: Path
):
    r = L.parse_one_date(legacy_bhavcopy_zip, mto_dat)
    assert (r.agreed["date"] == pd.Timestamp("2008-04-01")).all()


def test_parse_one_date_stats_reflect_inputs(
    legacy_bhavcopy_zip: Path, mto_dat: Path
):
    r = L.parse_one_date(legacy_bhavcopy_zip, mto_dat)
    assert r.bhavcopy_rows == 5
    assert r.mto_rows == 5
    assert r.eq_only_bhavcopy == 4
    assert r.eq_only_mto == 4
    assert r.join_rows == 4  # 4 EQ symbols common to both


# ---------------------------------------------------------------------------
# Filename → date helpers
# ---------------------------------------------------------------------------

def test_date_from_bhav_name():
    assert L._date_from_bhav_name("cm08JAN2024bhav.csv.zip") == date(2024, 1, 8)
    assert L._date_from_bhav_name("cm01APR2008bhav.csv.zip") == date(2008, 4, 1)


def test_date_from_bhav_name_rejects_unknown():
    with pytest.raises(ValueError):
        L._date_from_bhav_name("not-a-bhavcopy.zip")


def test_date_from_mto_name():
    assert L._date_from_mto_name("MTO_08012024.DAT") == date(2024, 1, 8)
    assert L._date_from_mto_name("MTO_01042008.DAT") == date(2008, 4, 1)


# ---------------------------------------------------------------------------
# parse_year — full directory orchestration
# ---------------------------------------------------------------------------

def test_parse_year_writes_parquet_and_disagreements(
    tmp_path: Path, legacy_bhavcopy_zip: Path, mto_dat: Path
):
    # Stage the fixtures under era-correct layouts.
    zip_dir = tmp_path / "bhavcopy" / "2008" / "04"
    zip_dir.mkdir(parents=True)
    target_zip = zip_dir / legacy_bhavcopy_zip.name
    target_zip.write_bytes(legacy_bhavcopy_zip.read_bytes())

    mto_dir = tmp_path / "mto" / "2008" / "04"
    mto_dir.mkdir(parents=True)
    target_mto = mto_dir / mto_dat.name
    target_mto.write_text(mto_dat.read_text())

    out_path = tmp_path / "out" / "2008.parquet"
    dis_path = tmp_path / "out" / "_disagreements" / "2008.parquet"
    stats = L.parse_year(
        zip_dir=tmp_path / "bhavcopy",
        mto_dir=tmp_path / "mto",
        out_path=out_path,
        disagreements_path=dis_path,
    )

    assert stats["dates"] == 1
    assert stats["agreed_rows"] == 3  # 4 EQ joined − 1 disagreement = 3
    assert stats["disagreement_rows"] == 1
    assert out_path.exists()
    assert dis_path.exists()

    # Validate Parquet roundtrip.
    df = pd.read_parquet(out_path)
    assert tuple(df.columns) == COLUMNS
    assert len(df) == 3
