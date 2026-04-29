"""Phase 3 validation runner: compare local FF5+UMD replicas to a local reference file."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

THIS_DIR = Path(__file__).resolve().parent
PROJECT_DIR = THIS_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from data.market.pit import load_pit_field_panel
from research.ff5_replication import build_ff5_umd_replica, load_characteristics_table
from research.risk_model import factor_replication_correlation, load_reference_factor_table


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Validate the local PIT-based FF5+UMD replica against a local daily reference factor file. "
            "Expected file contracts are documented in research/PHASE3_DATA_CONTRACT.md."
        )
    )
    p.add_argument("--reference", required=True, help="Local CSV/parquet with daily MKT/SMB/HML/RMW/CMA/UMD")
    p.add_argument("--characteristics", required=True, help="Local CSV/parquet with date,ticker,market_cap,book_to_market,profitability,investment")
    p.add_argument("--start", default="2016-01-04")
    p.add_argument("--end", default="2025-12-31")
    p.add_argument("--min-rows", type=int, default=252 * 3)
    p.add_argument("--out-json", default="research/out/phase3_ff5_validation.json")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    close_pt = load_pit_field_panel(
        field="Adj Close",
        start_date=args.start,
        end_date=args.end,
        min_rows=args.min_rows,
    )
    close = close_pt.panel
    valid = close.notna().sum(axis=0) >= args.min_rows
    close = close.loc[:, valid]

    chars = load_characteristics_table(args.characteristics)
    reference = load_reference_factor_table(args.reference)
    replica = build_ff5_umd_replica(close, chars)
    corr = factor_replication_correlation(replica, reference)

    payload = {
        "config": {
            "start": args.start,
            "end": args.end,
            "min_rows": args.min_rows,
            "n_tickers": int(close.shape[1]),
            "n_days": int(close.shape[0]),
        },
        "correlations": corr.reset_index().to_dict(orient="records"),
    }
    out = Path(args.out_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2))

    print(corr.to_string())
    if corr.empty or (corr["correlation"] < 0.85).any():
        print("\nFAIL: at least one factor correlation is below 0.85.")
        return 1
    print("\nPASS: all factor correlations exceed 0.85.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
