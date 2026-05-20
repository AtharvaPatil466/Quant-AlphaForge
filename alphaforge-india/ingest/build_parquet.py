"""Phase 0 Parquet pipeline builder.

Converts downloaded raw legacy, MTO, and unified CSV/DAT files into
yearly Parquet files matching the `schema.COLUMNS` format.

Outputs:
  - `data/processed/bhavcopy/{YYYY}.parquet`
  - `data/processed/_non_eq/{YYYY}.parquet` (quarantined non-EQ rows)
  - `data/processed/_holidays.jsonl`
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

from ingest.parser_legacy import parse_year as parse_legacy_year
from ingest.parser_unified import parse_year as parse_unified_year

log = logging.getLogger("india.build_parquet")

def build_pipeline(data_root: Path) -> dict:
    stats = {}
    processed_dir = data_root / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Process Legacy + MTO era (2004-2019)
    log.info("Processing Legacy + MTO era...")
    for year in range(2004, 2020):
        legacy_dir = data_root / "bhavcopy" / str(year)
        mto_dir = data_root / "mto" / str(year)
        
        if not legacy_dir.exists() and not mto_dir.exists():
            continue
            
        out_path = processed_dir / "bhavcopy" / f"{year}.parquet"
        disagreements_path = processed_dir / "_disagreements" / f"{year}.parquet"
        
        log.info(f"Parsing legacy year {year}...")
        year_stats = parse_legacy_year(
            zip_dir=legacy_dir, 
            mto_dir=mto_dir, 
            out_path=out_path,
            disagreements_path=disagreements_path
        )
        stats[str(year)] = year_stats
        
    # 2. Process Unified era (2020-present)
    log.info("Processing Unified era...")
    for year in range(2020, date.today().year + 1):
        unified_dir = data_root / "unified" / str(year)
        
        if not unified_dir.exists():
            continue
            
        out_path = processed_dir / "bhavcopy" / f"{year}.parquet"
        
        log.info(f"Parsing unified year {year}...")
        year_stats = parse_unified_year(
            unified_dir=unified_dir,
            out_path=out_path,
            holiday_path=processed_dir / "_holidays.jsonl"
        )
        stats[str(year)] = year_stats
        
    # Write summary
    stats_path = processed_dir / "_download_stats.json"
    with open(stats_path, "w") as f:
        json.dump(stats, f, indent=2)
        
    return stats


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Build unified Parquet files from raw downloads.")
    p.add_argument("--data-root", type=Path, default=Path("data"), help="Data root directory")
    args = p.parse_args(argv)
    
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    
    log.info(f"Starting Parquet build pipeline from {args.data_root}")
    stats = build_pipeline(args.data_root)
    log.info("Pipeline complete. Summary written to data/processed/_download_stats.json")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
