"""Post-2020 parser: sec_bhavdata_full CSV → unified Parquet.

Per `research/INDIA_DESIGN.md` §2.2. Single-source read — the unified file
already contains both OHLCV and delivery quantity/percentage inline. The
SERIES=EQ filter is still applied at ingestion time; non-EQ rows have
DELIV_PER set to the literal string "-" and would corrupt downstream
numeric coercion otherwise.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from .schema import COLUMNS, UNIFIED_ERA

log = logging.getLogger("india.parser_unified")

# Required columns in the unified format.
_UNIFIED_COLS_REQUIRED = (
    "SYMBOL", "SERIES", "DATE1",
    "PREV_CLOSE", "OPEN_PRICE", "HIGH_PRICE", "LOW_PRICE",
    "LAST_PRICE", "CLOSE_PRICE", "AVG_PRICE",
    "TTL_TRD_QNTY", "TURNOVER_LACS", "NO_OF_TRADES",
    "DELIV_QTY", "DELIV_PER",
)

# DATE1 format observed in unified files: "08-Jan-2024" (3-letter month, mixed case).
_DATE_FORMATS = ("%d-%b-%Y", "%d-%B-%Y")

# TURNOVER_LACS is in lakhs of rupees. 1 lakh = 100,000.
_LAKH = 100_000.0


@dataclass
class UnifiedParseResult:
    df: pd.DataFrame
    raw_rows: int
    eq_rows: int


def load_unified(csv_path: Path) -> pd.DataFrame:
    """Read one sec_bhavdata_full CSV. Returns ALL rows, all series."""
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)
    df = pd.read_csv(csv_path)
    # NSE has shipped this file with leading whitespace in some column names.
    df.columns = [c.strip() for c in df.columns]
    missing = [c for c in _UNIFIED_COLS_REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(
            f"{csv_path}: unified file missing required columns: {missing}; "
            f"got {list(df.columns)}"
        )
    df["SYMBOL"] = df["SYMBOL"].astype(str).str.strip()
    df["SERIES"] = df["SERIES"].astype(str).str.strip()
    return df


def _parse_unified_date(value: str) -> date:
    value = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return pd.to_datetime(value, format=fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognized unified DATE1 format: {value!r}")


def parse_one_date(csv_path: Path) -> UnifiedParseResult:
    raw = load_unified(csv_path)
    raw_rows = len(raw)

    eq = raw[raw["SERIES"] == "EQ"].copy()
    if eq.empty:
        raise ValueError(f"{csv_path}: no EQ-series rows")
    eq_rows = len(eq)

    trade_date = _parse_unified_date(eq["DATE1"].iloc[0])

    # Numeric coercion. After EQ filter, DELIV_PER should be fully numeric;
    # any stragglers (NaN) survive coercion and propagate downstream.
    deliv_pct = pd.to_numeric(eq["DELIV_PER"], errors="coerce")
    deliv_qty = pd.to_numeric(eq["DELIV_QTY"], errors="coerce")

    out = pd.DataFrame({
        "date": pd.to_datetime(trade_date),
        "symbol": eq["SYMBOL"].astype("string"),
        "series": eq["SERIES"].astype("string"),
        "open": eq["OPEN_PRICE"].astype("float64"),
        "high": eq["HIGH_PRICE"].astype("float64"),
        "low": eq["LOW_PRICE"].astype("float64"),
        "close": eq["CLOSE_PRICE"].astype("float64"),
        "last": eq["LAST_PRICE"].astype("float64"),
        "prev_close": eq["PREV_CLOSE"].astype("float64"),
        "volume": eq["TTL_TRD_QNTY"].astype("int64"),
        "value": (eq["TURNOVER_LACS"].astype("float64") * _LAKH),
        "num_trades": eq["NO_OF_TRADES"].astype("Int64"),
        "deliv_qty": deliv_qty.fillna(0).astype("int64"),
        "deliv_pct": deliv_pct.astype("float64"),
        "source_era": pd.array([UNIFIED_ERA] * eq_rows, dtype="string"),
    })[list(COLUMNS)]

    return UnifiedParseResult(df=out, raw_rows=raw_rows, eq_rows=eq_rows)


def parse_year(unified_dir: Path, out_path: Path) -> dict:
    """Parse every unified CSV under `unified_dir` and write one year of
    unified Parquet."""
    files = sorted(unified_dir.rglob("sec_bhavdata_full_*.csv"))
    frames: list[pd.DataFrame] = []
    stats = {"files": 0, "rows": 0}
    for f in files:
        try:
            r = parse_one_date(f)
        except Exception as e:
            log.warning("skipping %s: %r", f.name, e)
            continue
        frames.append(r.df)
        stats["files"] += 1
        stats["rows"] += len(r.df)
    if frames:
        out = pd.concat(frames, ignore_index=True)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out.to_parquet(out_path, index=False)
    return stats
