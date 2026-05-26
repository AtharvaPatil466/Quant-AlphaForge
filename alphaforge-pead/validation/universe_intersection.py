"""Universe intersection report — Phase 0 eligibility gate.

Computes the intersection from `research/PEAD_DESIGN.md` §2.4:

    PIT membership   ∩   XBRL availability   ∩   OHLCV coverage
                          ∩   ≥8 quarters of clean Diluted-continuing EPS

For each firm, we count how many `(fy, fp)` quarters survive after the
substrate window filter (≥ 2012-01-01) and the concept-hierarchy rules.
A firm is eligible if it has ≥8 such quarters AND its OHLCV parquet
exists at `data/quarantine/market/{TICKER}/`.

The output is `research/PEAD_UNIVERSE_INTERSECTION.md` — a markdown
report with per-bucket counts and a substitution-rate summary. This
file is one of the four artifacts required to file `PEAD_PHASE0_CERTIFIED.md`.

Usage:
    python3 -m validation.universe_intersection \\
        --pit-root ../alphaforge-python/data/market/pit/artifacts \\
        --edgar-root data/edgar_eps/ \\
        --ohlcv-root ../data/quarantine/market/ \\
        --out research/PEAD_UNIVERSE_INTERSECTION.md
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pyarrow.parquet as pq


log = logging.getLogger(__name__)


MIN_QUARTERS_PER_FIRM = 8  # PEAD_DESIGN.md §2.4


@dataclass
class FirmEligibility:
    cik: int
    ticker: str
    pit_member: bool = False
    has_xbrl: bool = False
    has_ohlcv: bool = False
    n_quarters: int = 0
    n_primary: int = 0
    n_fallback: int = 0

    @property
    def eligible(self) -> bool:
        return (
            self.pit_member
            and self.has_xbrl
            and self.has_ohlcv
            and self.n_quarters >= MIN_QUARTERS_PER_FIRM
        )


def load_pit_pairs(pit_root: Path) -> dict[int, str]:
    """Return {cik: ticker} from baseline + event log."""
    pairs: dict[int, str] = {}
    for fname in ("_baseline_2010-01-10.parquet", "_event_log.parquet"):
        p = pit_root / fname
        if not p.exists():
            continue
        df = pq.read_table(p).to_pandas()
        for _, row in df.iterrows():
            cik = row.get("cik")
            ticker = row.get("ticker")
            if cik is None or ticker is None:
                continue
            try:
                pairs[int(cik)] = str(ticker).upper()
            except (ValueError, TypeError):
                continue
    return pairs


def assess_firm(cik: int, ticker: str, edgar_root: Path, ohlcv_root: Path) -> FirmEligibility:
    fe = FirmEligibility(cik=cik, ticker=ticker, pit_member=True)

    shard = edgar_root / "by_cik" / f"CIK{cik:010d}.parquet"
    if shard.exists():
        fe.has_xbrl = True
        df = pq.read_table(shard).to_pandas()
        # 2026-05-17 (PEAD_DESIGN.md §2.2 addendum): count quarters by
        # distinct period_end among rows where period_kind == "quarterly".
        # Pre-fix this counted (fy, fp) tuples, which over-counted because
        # EDGAR tags multiple period_ends with the same fp on 10-K filings.
        if not df.empty:
            if "period_kind" in df.columns:
                q = df[df["period_kind"] == "quarterly"]
            else:
                import pandas as pd
                durations = (pd.to_datetime(df["end_date"]) - pd.to_datetime(df["start_date"])).dt.days
                q = df[(durations >= 85) & (durations <= 95)]
            if not q.empty:
                latest = q.sort_values("filed").groupby("period_end").tail(1)
                fe.n_quarters = len(latest)
                fe.n_primary = int((latest["substitution_level"] == 1).sum())
                fe.n_fallback = int((latest["substitution_level"] == 2).sum())

    ohlcv_dir = ohlcv_root / ticker
    if ohlcv_dir.exists() and any(ohlcv_dir.glob("*.parquet")):
        fe.has_ohlcv = True

    return fe


def build_report(pit_root: Path, edgar_root: Path, ohlcv_root: Path) -> dict:
    pairs = load_pit_pairs(pit_root)
    log.info("PIT universe: %d firms", len(pairs))

    firms: list[FirmEligibility] = []
    for cik, ticker in sorted(pairs.items()):
        firms.append(assess_firm(cik, ticker, edgar_root, ohlcv_root))

    total = len(firms)
    has_xbrl = sum(1 for f in firms if f.has_xbrl)
    has_ohlcv = sum(1 for f in firms if f.has_ohlcv)
    has_both = sum(1 for f in firms if f.has_xbrl and f.has_ohlcv)
    has_min_quarters = sum(1 for f in firms if f.n_quarters >= MIN_QUARTERS_PER_FIRM)
    eligible = [f for f in firms if f.eligible]

    total_eligible_quarters = sum(f.n_quarters for f in eligible)
    total_primary = sum(f.n_primary for f in eligible)
    total_fallback = sum(f.n_fallback for f in eligible)
    sub_rate = total_fallback / max(total_eligible_quarters, 1)

    # Reason buckets (mutually exclusive in order of evaluation)
    reasons: Counter = Counter()
    for f in firms:
        if not f.has_xbrl:
            reasons["no_xbrl_coverage"] += 1
        elif not f.has_ohlcv:
            reasons["no_ohlcv_coverage"] += 1
        elif f.n_quarters < MIN_QUARTERS_PER_FIRM:
            reasons[f"under_min_quarters({MIN_QUARTERS_PER_FIRM})"] += 1
        else:
            reasons["eligible"] += 1

    return {
        "pit_universe": total,
        "has_xbrl": has_xbrl,
        "has_ohlcv": has_ohlcv,
        "has_both": has_both,
        "has_min_quarters": has_min_quarters,
        "eligible_firms": len(eligible),
        "eligible_firm_quarters": total_eligible_quarters,
        "substitution": {
            "primary": total_primary,
            "fallback": total_fallback,
            "rate": sub_rate,
        },
        "exclusion_reasons": dict(reasons),
        "min_quarters_required": MIN_QUARTERS_PER_FIRM,
        # First 20 eligible firms — sanity sample for the markdown report
        "eligible_sample": [
            {"cik": f.cik, "ticker": f.ticker, "n_quarters": f.n_quarters}
            for f in eligible[:20]
        ],
    }


def render_markdown(report: dict) -> str:
    s = report["substitution"]
    rsn = report["exclusion_reasons"]
    lines = [
        "# PEAD Universe Intersection Report",
        "",
        "Eligibility filter from `research/PEAD_DESIGN.md` §2.4:",
        "",
        f"- PIT membership × XBRL availability × OHLCV coverage × ≥{report['min_quarters_required']} quarters",
        "",
        "## Headline counts",
        "",
        "| Filter | Firm count |",
        "|---|---:|",
        f"| PIT universe (total) | {report['pit_universe']} |",
        f"| Has XBRL coverage (Company Facts JSON returned) | {report['has_xbrl']} |",
        f"| Has OHLCV parquet on disk | {report['has_ohlcv']} |",
        f"| Has BOTH XBRL and OHLCV | {report['has_both']} |",
        f"| Has ≥{report['min_quarters_required']} quarters of clean Diluted-continuing EPS | {report['has_min_quarters']} |",
        f"| **Eligible (all four filters)** | **{report['eligible_firms']}** |",
        "",
        f"**Total eligible firm-quarters: {report['eligible_firm_quarters']:,}.**",
        "",
        "## Exclusion-reason breakdown",
        "",
        "Mutually exclusive, evaluated in order: no_xbrl_coverage → no_ohlcv_coverage → under_min_quarters → eligible.",
        "",
        "| Reason | Count |",
        "|---|---:|",
    ]
    for k, v in rsn.items():
        lines.append(f"| {k} | {v} |")
    lines += [
        "",
        "## Substitution rate (Diluted-continuing → Diluted fallback)",
        "",
        f"- Primary concept rows: {s['primary']:,}",
        f"- Fallback concept rows: {s['fallback']:,}",
        f"- Substitution rate: **{s['rate']*100:.2f}%**",
        "",
        f"(Pre-committed acceptable bound: <15%. See `PEAD_DESIGN.md` §2.3.)",
        "",
        "## Eligible sample (first 20)",
        "",
        "| CIK | Ticker | Quarters |",
        "|---|---|---:|",
    ]
    for row in report["eligible_sample"]:
        lines.append(f"| {row['cik']:010d} | {row['ticker']} | {row['n_quarters']} |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pit-root", type=Path,
                        default=Path("../alphaforge-python/data/market/pit/artifacts"))
    parser.add_argument("--edgar-root", type=Path, default=Path("data/edgar_eps"))
    parser.add_argument("--ohlcv-root", type=Path,
                        default=Path("../data/quarantine/market"))
    parser.add_argument("--out", type=Path,
                        default=Path("research/PEAD_UNIVERSE_INTERSECTION.md"))
    parser.add_argument("--json", type=Path,
                        default=Path("research/PEAD_UNIVERSE_INTERSECTION.json"))
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")

    report = build_report(args.pit_root, args.edgar_root, args.ohlcv_root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render_markdown(report))
    args.json.write_text(json.dumps(report, indent=2, default=str))
    log.info("wrote %s and %s", args.out, args.json)
    log.info("eligible firms: %d / %d  | eligible quarters: %d  | substitution rate: %.2f%%",
             report["eligible_firms"], report["pit_universe"],
             report["eligible_firm_quarters"], report["substitution"]["rate"]*100)

    # Return 0 if eligibility is reasonable, 1 otherwise (downstream gate)
    return 0 if report["eligible_firms"] >= 100 else 1


if __name__ == "__main__":
    sys.exit(main())
