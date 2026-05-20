"""Shared test fixtures for ingest parsers.

Schemas mirror the EXACT NSE published formats observed during the
2026-05-18 spike test (see /tmp/nse_spike/inspect_schemas.py output).
Do not modify these schemas to match parser expectations — modify the
parsers instead. This is the "test against reality, not expectations"
discipline.
"""
from __future__ import annotations

import io
import zipfile
from datetime import date
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Legacy bhavcopy CSV (zipped) fixtures
# ---------------------------------------------------------------------------

_LEGACY_BHAV_CSV = (
    "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP\n"
    "3IINFOTECH,EQ,101.0,102.0,97.3,99.90,100.35,98.9,108945,10827794.9,1-APR-2008\n"
    "3MINDIA,EQ,1785.0,1870.0,1751.0,1790.00,1790.00,1818.7,24,43382.3,1-APR-2008\n"
    "AARTIDRUGS,EQ,54.5,56.2,50.1,52.95,53.55,52.2,8747,459318.6,1-APR-2008\n"
    "DISAGREE,EQ,100.0,105.0,99.0,103.0,103.0,100.0,900,93000.0,1-APR-2008\n"
    "SOMEDEBT,GS,100.0,100.0,100.0,100.0,100.0,100.0,500,50000.0,1-APR-2008\n"
)


@pytest.fixture
def legacy_bhavcopy_zip(tmp_path: Path) -> Path:
    """A minimal but real-format legacy bhavcopy .zip for date(2008, 4, 1).
    Includes 4 EQ rows (one of which disagrees with MTO) and 1 non-EQ row."""
    path = tmp_path / "cm01APR2008bhav.csv.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("cm01APR2008bhav.csv", _LEGACY_BHAV_CSV)
    return path


# ---------------------------------------------------------------------------
# MTO .DAT fixtures
# ---------------------------------------------------------------------------

_MTO_DAT = (
    "Security Wise Delivery Position - Compulsory Rolling Settlement\n"
    "10,MTO,01042008,141555261,0001209\n"
    "Trade Date <01-APR-2008>,Settlement Type <N>,Settlement No <2008063>,Settlement Date <03-APR-2008>\n"
    "20,1,3IINFOTECH,EQ,108945,108945,100.00\n"
    "20,2,3MINDIA,EQ,24,24,100.00\n"
    "20,3,AARTIDRUGS,EQ,8747,5000,57.16\n"
    "20,4,DISAGREE,EQ,1000,500,50.00\n"   # QTY differs from bhav (900 vs 1000)
    "20,5,SOMEDEBT,GS,500,500,100.00\n"
)


@pytest.fixture
def mto_dat(tmp_path: Path) -> Path:
    path = tmp_path / "MTO_01042008.DAT"
    path.write_text(_MTO_DAT)
    return path


@pytest.fixture
def mto_dat_malformed(tmp_path: Path) -> Path:
    """MTO file with a malformed data row that should be skipped, not error."""
    text = (
        "Security Wise Delivery Position\n"
        "10,MTO,01042008,141555261,0001209\n"
        "20,1,3IINFOTECH,EQ,108945,108945,100.00\n"
        "20,malformed,row\n"   # too few columns — skipped
        "20,2,3MINDIA,EQ,24,24,100.00\n"
    )
    path = tmp_path / "MTO_01042008_bad.DAT"
    path.write_text(text)
    return path


# ---------------------------------------------------------------------------
# Unified CSV fixtures (post-2020)
# ---------------------------------------------------------------------------

_UNIFIED_CSV = (
    " SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE,"
    " LAST_PRICE, CLOSE_PRICE, AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS,"
    " NO_OF_TRADES, DELIV_QTY, DELIV_PER\n"
    "RELIANCE,EQ,08-Jan-2024,2500.0,2510.0,2530.0,2495.0,2520.0,2525.0,2515.5,1000000,25155.0,5000,800000,80.00\n"
    "TCS,EQ,08-Jan-2024,3500.0,3510.0,3530.0,3495.0,3520.0,3525.0,3515.5,500000,17577.5,3000,400000,80.00\n"
    "AARTIDRUGS,EQ,08-Jan-2024,500.0,505.0,510.0,499.0,508.0,507.0,505.0,10000,50.5,100,7500,75.00\n"
    "SOMEDEBT,GS,08-Jan-2024,100.0,100.0,100.0,100.0,100.0,100.0,100.0,500,0.5,5,500,-\n"
)
# NB: column names have leading whitespace, mirroring real NSE behavior.


@pytest.fixture
def unified_csv(tmp_path: Path) -> Path:
    path = tmp_path / "sec_bhavdata_full_08012024.csv"
    path.write_text(_UNIFIED_CSV)
    return path
