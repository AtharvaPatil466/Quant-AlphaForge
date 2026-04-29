"""Normalize raw local Phase 3 input files into the canonical repo contracts."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd

THIS_DIR = Path(__file__).resolve().parent
PROJECT_DIR = THIS_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from research.ff5_replication import load_characteristics_table
from research.risk_model import load_reference_factor_table


def _write_table(df: pd.DataFrame, out_path: str | Path) -> Path:
    out = Path(out_path).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.suffix.lower() == ".parquet":
        df.to_parquet(out, index=False)
    else:
        df.to_csv(out, index=False)
    return out


def stage_reference_table(in_path: str | Path, out_path: str | Path) -> Path:
    df = load_reference_factor_table(in_path).copy()
    duplicate_dates = int(df.index.duplicated().sum())
    if duplicate_dates:
        raise ValueError(f"reference factor table has {duplicate_dates} duplicate date rows")
    staged = df.reset_index().rename(columns={df.index.name or "index": "date"})
    staged["date"] = pd.to_datetime(staged["date"]).dt.strftime("%Y-%m-%d")
    return _write_table(staged, out_path)


def stage_characteristics_table(in_path: str | Path, out_path: str | Path) -> Path:
    df = load_characteristics_table(in_path).copy()
    duplicate_pairs = int(df.duplicated(subset=["date", "ticker"]).sum())
    if duplicate_pairs:
        raise ValueError(f"characteristics table has {duplicate_pairs} duplicate (date, ticker) rows")
    staged = df.copy()
    staged["date"] = pd.to_datetime(staged["date"]).dt.strftime("%Y-%m-%d")
    return _write_table(staged, out_path)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Normalize raw local Phase 3 reference-factor and characteristics files "
            "into the canonical schema used by the validators."
        )
    )
    p.add_argument("--reference-in", help="Raw local reference factor CSV/parquet")
    p.add_argument(
        "--reference-out",
        default="research/out/phase3_reference_staged.csv",
        help="Canonical output path for the staged reference factor table",
    )
    p.add_argument("--characteristics-in", help="Raw local characteristics CSV/parquet")
    p.add_argument(
        "--characteristics-out",
        default="research/out/phase3_characteristics_staged.csv",
        help="Canonical output path for the staged characteristics table",
    )
    args = p.parse_args()
    if not args.reference_in and not args.characteristics_in:
        p.error("at least one of --reference-in or --characteristics-in is required")
    return args


def main() -> int:
    args = parse_args()
    if args.reference_in:
        out = stage_reference_table(args.reference_in, args.reference_out)
        print(f"staged reference factor table -> {out}")
    if args.characteristics_in:
        out = stage_characteristics_table(args.characteristics_in, args.characteristics_out)
        print(f"staged characteristics table -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
