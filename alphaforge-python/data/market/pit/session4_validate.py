"""Session 4 — validate the event log.

Runs three independent checks:
  1. Wikipedia "Selected changes" table cross-check (curated change log
     parsed from the latest revision; semi-independent of our snapshot
     differ).
  2. Year-end membership replay — the reconstructed membership at every
     year-end 2010-2025 should be ~500 tickers (S&P 500 always sits
     between 498 and 510 in practice).
  3. Bootstrap a baseline membership from the first reliable snapshot,
     so the replayer has a starting set.

Outputs:
    artifacts/_session4_audit.json              — all results
    artifacts/_baseline_2010-01-10.parquet      — baseline membership

Run:
    .venv/bin/python -m data.market.pit.session4_validate
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .changes_parser import parse_changes_table
from .validator import cross_check_against_changes_table, membership_on_date

ART = Path(__file__).resolve().parent / "artifacts"


def _bootstrap_baseline_from_first_snapshot() -> tuple[set[str], dict]:
    """Use the earliest successfully-parsed snapshot as the baseline.

    We can't use Siblis without paid access; instead the first parseable
    snapshot from 2010-01-10 onward serves as the baseline. Every
    subsequent ADD/REMOVE is applied against it.
    """
    candidates = pd.read_parquet(ART / "_candidate_revisions.parquet")
    candidates = candidates.sort_values("timestamp")

    from .parser import parse_constituent_table
    from .cik import fetch_edgar_tickers, lookup_cik

    edgar = fetch_edgar_tickers()
    for r in candidates.itertuples(index=False):
        sn_path = ART / "snapshots" / f"{r.revid}.json"
        if not sn_path.exists():
            continue
        try:
            wt = json.loads(sn_path.read_text())["wikitext"]
            df = parse_constituent_table(wt)
        except Exception:
            continue
        if len(df) < 480:
            continue
        # Post-fill CIKs for completeness
        null_m = df["cik"].isna()
        df.loc[null_m, "cik"] = df.loc[null_m, "ticker"].apply(
            lambda t: lookup_cik(t, edgar) if isinstance(t, str) else None
        )
        baseline_tickers = set(df["ticker"].dropna().astype(str))
        meta = {
            "source_revision_id": int(r.revid),
            "timestamp": str(r.timestamp),
            "n_tickers": len(baseline_tickers),
        }
        df["source"] = "wikipedia_baseline"
        df["source_revision_id"] = str(r.revid)
        df["baseline_timestamp"] = str(r.timestamp)
        out_path = ART / "_baseline_2010-01-10.parquet"
        df.to_parquet(out_path, index=False)
        meta["baseline_path"] = str(out_path.name)
        return baseline_tickers, meta
    raise RuntimeError("no parseable baseline snapshot found")


def _yearend_membership_audit(events: pd.DataFrame, baseline: set[str]) -> list[dict]:
    """Replay the event log to each year-end and report the in-index count."""
    out: list[dict] = []
    for year in range(2010, 2026):
        ye = f"{year}-12-31"
        members = membership_on_date(events, baseline, ye)
        out.append({
            "year_end": ye,
            "n_members": len(members),
            "in_band": 495 <= len(members) <= 510,  # S&P 500 typical range
        })
    return out


def main() -> int:
    print("session 4 — validate the event log")
    print()

    # ── 1. Bootstrap baseline ──
    print("[1/4] bootstrapping baseline from earliest reliable snapshot")
    baseline, baseline_meta = _bootstrap_baseline_from_first_snapshot()
    print(f"      baseline: {baseline_meta['n_tickers']} tickers from rev {baseline_meta['source_revision_id']} @ {baseline_meta['timestamp']}")
    print()

    # ── 2. Load event log ──
    print("[2/4] loading event log")
    events = pd.read_parquet(ART / "_event_log.parquet")
    print(f"      events: {len(events):,}")
    print()

    # ── 3. Wikipedia changes-table cross-check ──
    print("[3/4] Wikipedia 'Selected changes' table cross-check")
    cand = pd.read_parquet(ART / "_candidate_revisions.parquet").sort_values("timestamp")
    latest_rid = int(cand.iloc[-1]["revid"])
    wt = json.loads((ART / "snapshots" / f"{latest_rid}.json").read_text())["wikitext"]
    changes = parse_changes_table(wt)
    print(f"      changes table: {len(changes)} rows ({changes['effective_date'].min()} → {changes['effective_date'].max()})")

    # Tolerance is 21 days: Wikipedia editors update the changes table on
    # their own schedule, often 1-3 weeks after the actual effective date.
    # Our log pegs effective_date to the revision timestamp where the
    # change first appeared in the constituents table — also editor-paced.
    cc = cross_check_against_changes_table(events, changes, tol_days=21, min_year=2010)
    print(f"      {cc['summary_text']}")
    print(f"      missing ADDs:    {cc['missing_add_count']}")
    print(f"      missing REMOVEs: {cc['missing_remove_count']}")
    if cc["missing_add_examples"]:
        print("      first 5 missing ADDs:")
        for m in cc["missing_add_examples"][:5]:
            print(f"        {m['effective_date']} {m['ticker']} ({m['security']!s:<25.25}) — log has dates: {m['in_log_dates']}")
    if cc["missing_remove_examples"]:
        print("      first 5 missing REMOVEs:")
        for m in cc["missing_remove_examples"][:5]:
            print(f"        {m['effective_date']} {m['ticker']} ({m['security']!s:<25.25}) — log has dates: {m['in_log_dates']}")
    print()

    # ── 4. Year-end membership audit ──
    print("[4/4] year-end membership replay")
    yend = _yearend_membership_audit(events, baseline)
    in_band = sum(1 for r in yend if r["in_band"])
    print(f"      year-ends in [495, 510] band: {in_band} / {len(yend)}")
    for r in yend:
        flag = "✓" if r["in_band"] else "✗"
        print(f"        {flag} {r['year_end']}: {r['n_members']} members")
    print()

    # ── audit ──
    audit = {
        "session": "Phase 1 Session 4 — validation",
        "built_at": datetime.now(timezone.utc).isoformat(),
        "baseline": baseline_meta,
        "event_log_size": int(len(events)),
        "changes_table": {
            "source_revision_id": latest_rid,
            "n_rows": int(len(changes)),
            "min_date": str(changes["effective_date"].min()),
            "max_date": str(changes["effective_date"].max()),
        },
        "cross_check": cc,
        "yearend_membership": yend,
        "yearend_in_band_count": int(in_band),
    }
    audit_path = ART / "_session4_audit.json"
    audit_path.write_text(json.dumps(audit, indent=2, default=str))
    print(f"audit: {audit_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
