"""Sanity-check locally staged Phase 3 input files before the full FF5 gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

import pandas as pd

THIS_DIR = Path(__file__).resolve().parent
PROJECT_DIR = THIS_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from research.ff5_replication import REQUIRED_CHARACTERISTIC_COLUMNS, load_characteristics_table
from research.risk_model import REFERENCE_FACTOR_COLUMNS, load_reference_factor_table


def _stringify_timestamp(value: pd.Timestamp | None) -> str | None:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def summarize_reference_factor_table(df: pd.DataFrame) -> dict[str, Any]:
    duplicate_dates = int(df.index.duplicated().sum())
    missing_fraction = {col: float(df[col].isna().mean()) for col in REFERENCE_FACTOR_COLUMNS}
    non_null_rows = int(df.dropna(how="all").shape[0])
    suspicious_scale = [col for col in REFERENCE_FACTOR_COLUMNS if float(df[col].abs().max(skipna=True) or 0.0) > 1.0]
    return {
        "n_rows": int(len(df)),
        "non_null_rows": non_null_rows,
        "start_date": _stringify_timestamp(df.index.min() if len(df.index) else None),
        "end_date": _stringify_timestamp(df.index.max() if len(df.index) else None),
        "duplicate_dates": duplicate_dates,
        "missing_fraction": missing_fraction,
        "suspicious_scale_columns": suspicious_scale,
        "warnings": [
            "duplicate dates present" if duplicate_dates else None,
            "one or more factor columns look like percent units, not decimal returns" if suspicious_scale else None,
            "reference table is entirely empty after load" if non_null_rows == 0 else None,
        ],
    }


def summarize_characteristics_table(df: pd.DataFrame) -> dict[str, Any]:
    duplicate_pairs = int(df.duplicated(subset=["date", "ticker"]).sum())
    missing_fraction = {col: float(df[col].isna().mean()) for col in REQUIRED_CHARACTERISTIC_COLUMNS[1:]}
    per_date = df.groupby("date")["ticker"].nunique() if not df.empty else pd.Series(dtype=float)
    return {
        "n_rows": int(len(df)),
        "n_dates": int(df["date"].nunique()),
        "n_tickers": int(df["ticker"].nunique()),
        "start_date": _stringify_timestamp(df["date"].min() if not df.empty else None),
        "end_date": _stringify_timestamp(df["date"].max() if not df.empty else None),
        "duplicate_date_ticker_pairs": duplicate_pairs,
        "rows_per_date_min": int(per_date.min()) if len(per_date) else 0,
        "rows_per_date_max": int(per_date.max()) if len(per_date) else 0,
        "missing_fraction": missing_fraction,
        "warnings": [
            "duplicate (date, ticker) rows present" if duplicate_pairs else None,
            "characteristics table is empty after load" if df.empty else None,
        ],
    }


def _clean_warnings(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    out["warnings"] = [w for w in payload.get("warnings", []) if w]
    return out


def _print_summary(label: str, payload: dict[str, Any]) -> None:
    print(f"[{label}]")
    for key, value in payload.items():
        if key == "warnings":
            continue
        if isinstance(value, dict):
            print(f"{key}:")
            for subkey, subvalue in value.items():
                print(f"  {subkey}: {subvalue}")
        else:
            print(f"{key}: {value}")
    warnings = payload.get("warnings", [])
    if warnings:
        print("warnings:")
        for warning in warnings:
            print(f"  - {warning}")
    print()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Sanity-check locally staged Phase 3 input files before running "
            "research/phase3_validate_ff5.py."
        )
    )
    p.add_argument("--reference", help="Local daily reference factor CSV/parquet")
    p.add_argument("--characteristics", help="Local monthly characteristics CSV/parquet")
    p.add_argument("--out-json", help="Optional JSON output path")
    args = p.parse_args()
    if not args.reference and not args.characteristics:
        p.error("at least one of --reference or --characteristics is required")
    return args


def main() -> int:
    args = parse_args()
    report: dict[str, Any] = {}
    exit_code = 0

    if args.reference:
        reference = load_reference_factor_table(args.reference)
        summary = _clean_warnings(summarize_reference_factor_table(reference))
        report["reference"] = summary
        _print_summary("reference", summary)
        if summary["duplicate_dates"] > 0 or summary["non_null_rows"] == 0:
            exit_code = 1

    if args.characteristics:
        chars = load_characteristics_table(args.characteristics)
        summary = _clean_warnings(summarize_characteristics_table(chars))
        report["characteristics"] = summary
        _print_summary("characteristics", summary)
        if summary["duplicate_date_ticker_pairs"] > 0 or summary["n_rows"] == 0:
            exit_code = 1

    if args.out_json:
        out = Path(args.out_json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2))

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
