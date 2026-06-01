"""Pre-2020 parser: legacy bhavcopy CSV (zipped) + MTO delivery DAT → unified Parquet.

Per `research/INDIA_DESIGN.md` §2.2. The two-source join is the load-bearing
piece — bhavcopy carries OHLCV, MTO carries delivery percentage. Joined on
(date, SYMBOL, SERIES) with TOTTRDQTY cross-check.

Critical pre-commits (frozen):
  1. SERIES=EQ filter is applied at ingestion time on BOTH inputs before join.
  2. TOTTRDQTY (bhavcopy) MUST equal QUANTITY_TRADED (MTO) for the join to be
     accepted. Mismatches are quarantined to `_disagreements.parquet`, NOT
     silently resolved.
  3. Output schema matches `ingest.schema.COLUMNS` exactly so downstream code
     does not branch on era.
"""
from __future__ import annotations

import io
import logging
import re
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

import pandas as pd

from .schema import COLUMNS, DTYPES, LEGACY_ERA

log = logging.getLogger("india.parser_legacy")

# Bhavcopy CSV column names (NSE has been consistent on these since 2004).
_BHAV_COLS_REQUIRED = (
    "SYMBOL", "SERIES", "OPEN", "HIGH", "LOW", "CLOSE", "LAST",
    "PREVCLOSE", "TOTTRDQTY", "TOTTRDVAL", "TIMESTAMP",
)

# MTO row layout. Data rows start with `20,` (record_type=20). The header
# block has record_type=10 and other metadata lines.
_MTO_HEADER_RECORD_TYPE = "10"
_MTO_DATA_RECORD_TYPE = "20"
_MTO_DATA_COL_COUNT = 7  # record_type, sr_no, symbol, series, qty_traded, deliv_qty, deliv_per

# TIMESTAMP in legacy bhavcopy looks like "1-APR-2008" or "01-APR-2008".
_TS_PATTERN = re.compile(r"^\d{1,2}-[A-Z]{3}-\d{4}$")


@dataclass
class ParseResult:
    """Output of parse_one_date. `agreed` is the joined data ready for the
    unified Parquet store; `disagreements` are rows where TOTTRDQTY ≠ MTO
    QUANTITY_TRADED and are quarantined for audit."""
    agreed: pd.DataFrame
    disagreements: pd.DataFrame
    bhavcopy_rows: int
    mto_rows: int
    eq_only_bhavcopy: int
    eq_only_mto: int
    join_rows: int


# ---------------------------------------------------------------------------
# Bhavcopy parsing
# ---------------------------------------------------------------------------

def load_legacy_bhavcopy(zip_path: Path) -> pd.DataFrame:
    """Read a legacy bhavcopy .zip file. Returns ALL rows, all series."""
    if not zip_path.exists():
        raise FileNotFoundError(zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        if not names:
            raise ValueError(f"empty zip: {zip_path}")
        with zf.open(names[0]) as fp:
            df = pd.read_csv(fp)
    # NSE has at times included trailing whitespace in column names.
    df.columns = [c.strip() for c in df.columns]
    missing = [c for c in _BHAV_COLS_REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(
            f"{zip_path}: bhavcopy missing required columns: {missing}; "
            f"got {list(df.columns)}"
        )
    # SYMBOL / SERIES can have stray whitespace.
    df["SYMBOL"] = df["SYMBOL"].astype(str).str.strip()
    df["SERIES"] = df["SERIES"].astype(str).str.strip()
    return df


# ---------------------------------------------------------------------------
# MTO parsing
# ---------------------------------------------------------------------------

def load_mto(mto_path: Path) -> pd.DataFrame:
    """Read an MTO .DAT file. Returns delivery rows (record_type=20) only.

    Columns returned: SR_NO, SYMBOL, SERIES, QUANTITY_TRADED, DELIV_QTY, DELIV_PER.
    """
    if not mto_path.exists():
        raise FileNotFoundError(mto_path)
    text = mto_path.read_text(encoding="utf-8", errors="ignore")
    rows: list[list[str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        if not parts:
            continue
        if parts[0] != _MTO_DATA_RECORD_TYPE:
            continue  # skip header / metadata lines
        if len(parts) != _MTO_DATA_COL_COUNT:
            log.debug("mto: skipping malformed data row (cols=%d): %r",
                      len(parts), raw[:80])
            continue
        rows.append(parts)
    if not rows:
        raise ValueError(f"{mto_path}: no data rows (record_type=20)")
    df = pd.DataFrame(rows, columns=[
        "RECORD_TYPE", "SR_NO", "SYMBOL", "SERIES",
        "QUANTITY_TRADED", "DELIV_QTY", "DELIV_PER",
    ])
    df["SYMBOL"] = df["SYMBOL"].astype(str).str.strip()
    df["SERIES"] = df["SERIES"].astype(str).str.strip()
    # Numeric coercion. Anything non-numeric becomes NaN; downstream filter
    # to SERIES=EQ should leave only clean rows.
    df["QUANTITY_TRADED"] = pd.to_numeric(df["QUANTITY_TRADED"], errors="coerce")
    df["DELIV_QTY"] = pd.to_numeric(df["DELIV_QTY"], errors="coerce")
    df["DELIV_PER"] = pd.to_numeric(df["DELIV_PER"], errors="coerce")
    return df


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

def _parse_legacy_timestamp(value: str) -> date:
    """Convert '1-APR-2008' or '01-APR-2008' to a date object."""
    value = value.strip()
    if not _TS_PATTERN.match(value):
        raise ValueError(f"unrecognized legacy TIMESTAMP: {value!r}")
    return datetime.strptime(value, "%d-%b-%Y").date()


# ---------------------------------------------------------------------------
# Join + cross-check
# ---------------------------------------------------------------------------

def parse_one_date(zip_path: Path, mto_path: Path) -> ParseResult:
    """Parse a single trading date.

    Both files MUST exist. EQ filter is applied to both inputs before join.
    The cross-check `bhav.TOTTRDQTY == mto.QUANTITY_TRADED` is enforced;
    mismatches are quarantined.
    """
    bhav = load_legacy_bhavcopy(zip_path)
    mto = load_mto(mto_path)

    bhavcopy_rows = len(bhav)
    mto_rows = len(mto)

    bhav_eq = bhav[bhav["SERIES"] == "EQ"].copy()
    mto_eq = mto[mto["SERIES"] == "EQ"].copy()

    eq_only_bhavcopy = len(bhav_eq)
    eq_only_mto = len(mto_eq)

    # Resolve date from the bhavcopy TIMESTAMP. All rows on a given file
    # share the same trade date, so .iloc[0] is safe after EQ filter.
    if bhav_eq.empty:
        raise ValueError(f"{zip_path}: no EQ-series rows")
    trade_date = _parse_legacy_timestamp(bhav_eq["TIMESTAMP"].iloc[0])

    # Inner join on (SYMBOL, SERIES). Both sides are EQ-filtered already.
    joined = bhav_eq.merge(
        mto_eq[["SYMBOL", "SERIES", "QUANTITY_TRADED", "DELIV_QTY", "DELIV_PER"]],
        on=["SYMBOL", "SERIES"],
        how="inner",
        validate="one_to_one",
    )

    # Cross-check TOTTRDQTY == QUANTITY_TRADED.
    qty_match = joined["TOTTRDQTY"] == joined["QUANTITY_TRADED"]
    agreed = joined[qty_match].copy()
    disagreements = joined[~qty_match].copy()

    # Build the canonical unified-schema DataFrame from the agreed rows.
    agreed_out = pd.DataFrame({
        "date": pd.to_datetime(trade_date),
        "symbol": agreed["SYMBOL"].astype("string"),
        "series": agreed["SERIES"].astype("string"),
        "open": agreed["OPEN"].astype("float64"),
        "high": agreed["HIGH"].astype("float64"),
        "low": agreed["LOW"].astype("float64"),
        "close": agreed["CLOSE"].astype("float64"),
        "last": agreed["LAST"].astype("float64"),
        "prev_close": agreed["PREVCLOSE"].astype("float64"),
        "volume": agreed["TOTTRDQTY"].astype("int64"),
        "value": agreed["TOTTRDVAL"].astype("float64"),
        "num_trades": pd.array([pd.NA] * len(agreed), dtype="Int64"),
        "deliv_qty": agreed["DELIV_QTY"].astype("int64"),
        "deliv_pct": agreed["DELIV_PER"].astype("float64"),
        "source_era": pd.array([LEGACY_ERA] * len(agreed), dtype="string"),
    })[list(COLUMNS)]

    disagreements_out = pd.DataFrame({
        "date": pd.to_datetime(trade_date),
        "symbol": disagreements["SYMBOL"].astype("string"),
        "series": disagreements["SERIES"].astype("string"),
        "bhavcopy_volume": disagreements["TOTTRDQTY"].astype("int64"),
        "mto_quantity_traded": disagreements["QUANTITY_TRADED"].astype("int64"),
        "delta": (disagreements["TOTTRDQTY"]
                  - disagreements["QUANTITY_TRADED"]).astype("int64"),
        "source_era": pd.array([LEGACY_ERA] * len(disagreements), dtype="string"),
    })

    return ParseResult(
        agreed=agreed_out,
        disagreements=disagreements_out,
        bhavcopy_rows=bhavcopy_rows,
        mto_rows=mto_rows,
        eq_only_bhavcopy=eq_only_bhavcopy,
        eq_only_mto=eq_only_mto,
        join_rows=len(joined),
    )


def parse_year(zip_dir: Path, mto_dir: Path,
               out_path: Path,
               disagreements_path: Path | None = None) -> dict:
    """Parse every (bhavcopy, MTO) pair under the directories and write one
    year of unified Parquet. Returns aggregate stats."""
    # Pair files by date. Bhavcopy filenames: cm{DD}{MMM}{YYYY}bhav.csv.zip.
    # MTO filenames: MTO_{DDMMYYYY}.DAT.
    bhav_files = {
        _date_from_bhav_name(p.name): p for p in zip_dir.rglob("cm*.csv.zip")
    }
    mto_files = {
        _date_from_mto_name(p.name): p for p in mto_dir.rglob("MTO_*.DAT")
    }
    paired = sorted(set(bhav_files) & set(mto_files))

    agreed_frames: list[pd.DataFrame] = []
    disagreements_frames: list[pd.DataFrame] = []
    stats = {"dates": 0, "agreed_rows": 0, "disagreement_rows": 0,
             "missing_mto": 0, "missing_bhav": 0,
             "unexpected_errors": 0, "unexpected_error_dates": []}
    for d in paired:
        try:
            r = parse_one_date(bhav_files[d], mto_files[d])
        except ValueError as e:
            # Legitimate empty/holiday/format-of-this-file conditions (empty
            # zip, no EQ rows, unrecognized timestamp). Skip, as before.
            log.warning("skipping %s: %r", d.isoformat(), e)
            continue
        except Exception as e:
            # An UNEXPECTED error (schema/encoding change, corrupt file, etc.)
            # must NOT be silently swallowed: a format change cannot be allowed
            # to masquerade as a missing/holiday date and let Phase-0 coverage
            # pass on silently-dropped data. Count it, record the offending
            # date, and hard-fail the build below.
            stats["unexpected_errors"] += 1
            stats["unexpected_error_dates"].append(d.isoformat())
            log.error("unexpected parse error on %s: %r", d.isoformat(), e)
            continue
        agreed_frames.append(r.agreed)
        if not r.disagreements.empty:
            disagreements_frames.append(r.disagreements)
        stats["dates"] += 1
        stats["agreed_rows"] += len(r.agreed)
        stats["disagreement_rows"] += len(r.disagreements)
    stats["missing_mto"] = len(set(bhav_files) - set(mto_files))
    stats["missing_bhav"] = len(set(mto_files) - set(bhav_files))

    if stats["unexpected_errors"]:
        raise RuntimeError(
            f"{stats['unexpected_errors']} unexpected parse error(s) in "
            f"{zip_dir} / {mto_dir}; offending dates: "
            f"{stats['unexpected_error_dates']}. Refusing to write Parquet — a "
            f"format/encoding change must not be silently dropped as if it were "
            f"a missing/holiday date."
        )
    if agreed_frames:
        out = pd.concat(agreed_frames, ignore_index=True)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out.to_parquet(out_path, index=False)
    if disagreements_frames and disagreements_path is not None:
        d = pd.concat(disagreements_frames, ignore_index=True)
        disagreements_path.parent.mkdir(parents=True, exist_ok=True)
        d.to_parquet(disagreements_path, index=False)
    return stats


# ---------------------------------------------------------------------------
# Filename → date helpers
# ---------------------------------------------------------------------------

_MONTH_LOOKUP = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
     "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], start=1)}


def _date_from_bhav_name(name: str) -> date:
    """cm08JAN2024bhav.csv.zip → date(2024, 1, 8)."""
    # name is like "cm08JAN2024bhav.csv.zip"
    if not (name.startswith("cm") and name.endswith("bhav.csv.zip")):
        raise ValueError(f"unexpected bhavcopy filename: {name!r}")
    core = name[2:-len("bhav.csv.zip")]  # "08JAN2024"
    return date(int(core[5:9]), _MONTH_LOOKUP[core[2:5]], int(core[:2]))


def _date_from_mto_name(name: str) -> date:
    """MTO_08012024.DAT → date(2024, 1, 8)."""
    if not (name.startswith("MTO_") and name.endswith(".DAT")):
        raise ValueError(f"unexpected MTO filename: {name!r}")
    core = name[4:-len(".DAT")]  # "08012024"
    return date(int(core[4:8]), int(core[2:4]), int(core[:2]))
