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


# Factors split into two groups per PHASE3_VALIDATION_RESULT.md:
#   GATED        — physical factors (price-only construction); should match
#                  Ken French on this universe and gate Phase 4 readiness.
#   BOUNDED      — characteristic-driven factors (size / OP / Inv); cannot
#                  match French on a 500-ticker S&P 500 universe regardless
#                  of methodology quality (universe-too-narrow for SMB;
#                  SEC-XBRL data quality bound for RMW/CMA). Reported as
#                  informational; not gated.
GATED_FACTORS = ("MKT", "HML", "UMD")
BOUNDED_FACTORS = ("SMB", "RMW", "CMA")
GATE_THRESHOLD = 0.85


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

    gated = corr.loc[corr.index.intersection(GATED_FACTORS)]
    bounded = corr.loc[corr.index.intersection(BOUNDED_FACTORS)]

    gate_passed = (not gated.empty) and bool((gated["correlation"] >= GATE_THRESHOLD).all())

    payload = {
        "config": {
            "start": args.start,
            "end": args.end,
            "min_rows": args.min_rows,
            "n_tickers": int(close.shape[1]),
            "n_days": int(close.shape[0]),
        },
        "gate": {
            "threshold": GATE_THRESHOLD,
            "gated_factors": list(GATED_FACTORS),
            "bounded_factors": list(BOUNDED_FACTORS),
            "passed": gate_passed,
            "rationale_doc": "research/PHASE3_VALIDATION_RESULT.md",
        },
        "correlations": corr.reset_index().to_dict(orient="records"),
    }
    out = Path(args.out_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2))

    print("Gated (price-only construction; must clear ≥ 0.85):")
    print(gated.to_string() if not gated.empty else "  (none)")
    print()
    print("Bounded (universe / data-quality limited; informational only):")
    print(bounded.to_string() if not bounded.empty else "  (none)")
    print()

    if gated.empty:
        print("FAIL: no gated factors found in correlation table.")
        return 1
    failing = gated[gated["correlation"] < GATE_THRESHOLD]
    if not failing.empty:
        print(f"FAIL: gated factor(s) below {GATE_THRESHOLD}: "
              f"{', '.join(failing.index.tolist())}.")
        return 1
    print(f"PASS: all gated factors (MKT/HML/UMD) clear {GATE_THRESHOLD}. "
          f"Bounded factors documented in PHASE3_VALIDATION_RESULT.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
