"""Session 3 — orchestrate fetch + parse + diff to produce the event log.

Outputs:
    artifacts/_event_log.parquet            — chronological event log
    artifacts/_session3_audit.json          — provenance + named-event verification
    artifacts/_parse_failures.csv           — revisions that didn't parse, with reason

Per PIT_UNIVERSE_DESIGN.md §5.3.

Run:
    .venv/bin/python -m data.market.pit.session3_build_events
"""

from __future__ import annotations

import json
import traceback
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .cik import fetch_edgar_tickers, lookup_cik
from .differ import ParsedSnapshot, diff_snapshot_sequence
from .fetch_content import fetch_all_candidate_wikitext
from .parser import parse_constituent_table

ART = Path(__file__).resolve().parent / "artifacts"

# Named-event sanity fixture. Each entry: (label, ticker, expected_action,
# expected_effective_date_window). The differ pegs effective_date to the
# revision-day, so we accept a small bracket.
NAMED_EVENTS = [
    ("TSLA add",          "TSLA", "ADD",    "2020-12-21", "2020-12-22"),
    ("FB→META rename",    "META", "RENAME", "2022-06-08", "2022-06-12"),
    ("TWTR delist",       "TWTR", "REMOVE", "2022-10-29", "2022-11-05"),
    # GE was NOT removed — it had two spinoffs (GEHC, GEV) that joined
    # the index as separate names. The original GE (now "GE Aerospace")
    # remains. So we verify the *spinoffs* instead, which exercise the
    # ADD path on a non-trivial pre-existing-CIK case.
    ("GEHC spinoff add",  "GEHC", "ADD",    "2023-01-03", "2023-01-06"),
    ("GEV spinoff add",   "GEV",  "ADD",    "2024-04-01", "2024-04-05"),
    # NLOK → GEN exercises the CIK-identity path through the Norton
    # /Avast/Gen Digital merger.  CIK 849399 should be preserved across
    # the rename.
    ("SYMC→NLOK rename",  "NLOK", "RENAME", "2019-11-04", "2019-11-15"),
]


def _parse_all(wikitext_by_revid: dict[int, str], rev_meta: pd.DataFrame,
               edgar_table: dict[str, str]
               ) -> tuple[list[ParsedSnapshot], list[dict]]:
    """Parse every fetched revision. Return (parsed snapshots ascending,
    list of failure rows). Post-fills CIK from EDGAR for any snapshot row
    whose in-table CIK is null (older format eras lack the CIK column)."""
    meta_by_revid = rev_meta.set_index("revid")
    parsed: list[ParsedSnapshot] = []
    failures: list[dict] = []

    for rid, wt in wikitext_by_revid.items():
        try:
            df = parse_constituent_table(wt)
        except Exception as exc:
            failures.append({
                "revid": int(rid),
                "error": f"{type(exc).__name__}: {exc}",
                "tb_first": traceback.format_exc().splitlines()[-1] if traceback.format_exc() else "",
            })
            continue
        if rid not in meta_by_revid.index:
            failures.append({"revid": int(rid), "error": "no metadata for revid", "tb_first": ""})
            continue

        # Post-fill CIK from EDGAR where missing (older eras have no CIK column).
        # We do not OVERWRITE in-table CIKs — those are the historical record.
        if "cik" in df.columns:
            null_mask = df["cik"].isna() | (df["cik"] == "")
            if null_mask.any():
                df.loc[null_mask, "cik"] = df.loc[null_mask, "ticker"].apply(
                    lambda t: lookup_cik(t, edgar_table) if isinstance(t, str) else None
                )

        m = meta_by_revid.loc[rid]
        parsed.append(ParsedSnapshot(
            revid=int(rid),
            timestamp=pd.to_datetime(m["timestamp"], utc=True),
            comment=str(m.get("comment", "") or ""),
            df=df,
        ))

    parsed.sort(key=lambda p: p.timestamp)
    return parsed, failures


def _verify_named_events(events: pd.DataFrame) -> list[dict]:
    out = []
    for label, ticker, action, win_start, win_end in NAMED_EVENTS:
        mask = (
            (events["ticker"] == ticker)
            & (events["action"] == action)
            & (events["effective_date"] >= win_start)
            & (events["effective_date"] <= win_end)
        )
        hits = events[mask]
        out.append({
            "label": label,
            "ticker": ticker,
            "expected_action": action,
            "expected_window": [win_start, win_end],
            "matches": int(len(hits)),
            "first_match": (
                hits.iloc[0][["effective_date", "action", "counterparty_ticker", "source_revision_id"]]
                .to_dict() if len(hits) else None
            ),
        })
    return out


def main() -> int:
    print("session 3 — fetch + parse + diff")
    print()

    print("[1/4] fetching wikitext for all candidate revisions")
    wt = fetch_all_candidate_wikitext()
    print(f"      fetched: {len(wt):,} wikitexts")
    print()

    print("[2/4] loading revision metadata")
    rev_meta = pd.read_parquet(ART / "_revisions_full.parquet")
    print(f"      total revisions in metadata: {len(rev_meta):,}")
    print()

    print("[3/4] parsing snapshots (CIK post-fill from EDGAR for older eras)")
    edgar = fetch_edgar_tickers()
    parsed, failures = _parse_all(wt, rev_meta, edgar)
    print(f"      parsed OK: {len(parsed):,}")
    print(f"      parse failures: {len(failures):,}")
    if failures:
        fdf = pd.DataFrame(failures)
        fdf.to_csv(ART / "_parse_failures.csv", index=False)
        # Count by error type
        err_kinds = fdf["error"].apply(lambda s: s.split(":", 1)[0])
        print("      failure breakdown:")
        for kind, n in err_kinds.value_counts().head(5).items():
            print(f"        {kind}: {n}")
    print()

    print("[4/4] diffing parsed snapshots")
    events = diff_snapshot_sequence(parsed)
    print(f"      total events emitted: {len(events):,}")

    if not events.empty:
        events_path = ART / "_event_log.parquet"
        events.to_parquet(events_path, index=False)

        action_counts = events["action"].value_counts().to_dict()
        named_results = _verify_named_events(events)
        print()
        print("event action breakdown:")
        for a, n in action_counts.items():
            print(f"  {a}: {n}")
        print()
        print("named-event verification:")
        for r in named_results:
            ok = "✓" if r["matches"] >= 1 else "✗"
            print(f"  {ok} {r['label']:18s} matches={r['matches']}  "
                  f"first={r['first_match']}")
    else:
        named_results = []
        action_counts = {}

    audit = {
        "session": "Phase 1 Session 3 — fetch + parse + diff",
        "built_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "candidate_revisions_parquet": "_candidate_revisions.parquet",
            "metadata_parquet": "_revisions_full.parquet",
        },
        "outputs": {
            "event_log_parquet": "_event_log.parquet" if not events.empty else None,
            "parse_failures_csv": "_parse_failures.csv" if failures else None,
        },
        "summary": {
            "candidate_revisions_fetched": len(wt),
            "parsed_ok": len(parsed),
            "parse_failures": len(failures),
            "events_emitted": int(len(events)),
            "action_breakdown": action_counts,
        },
        "named_event_verification": named_results,
    }
    audit_path = ART / "_session3_audit.json"
    audit_path.write_text(json.dumps(audit, indent=2, default=str))
    print()
    print(f"audit log: {audit_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
