"""Session 1 atom — build one verified, CIK-enriched constituent snapshot
from Wikipedia revision 995546256 (the Tesla 2020-12-21 addition).

Per PIT_UNIVERSE_DESIGN.md §9 — this is the smallest end-to-end pass,
designed to surface format and identity gotchas before generalizing to
the full revision walker.

Output:
    artifacts/_session1_2020-12-21.parquet      (the snapshot)
    artifacts/_session1_2020-12-21_audit.json   (provenance + verification)

Run:
    .venv/bin/python -m data.market.pit.session1_build_atom
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .cik import fetch_edgar_tickers, lookup_cik
from .parser import parse_constituent_table

ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"
SOURCE_REV_ID = "995546256"
SOURCE_REV_TIMESTAMP = "2020-12-21T17:10:08Z"
SOURCE_REV_COMMENT = "TSLA added to SP500"

# Verification fixture — names whose CIK we can hand-verify against EDGAR
# right now. If any disagree it's a parser/normalization bug, not source
# drift, because EDGAR is the authoritative current registry.
VERIFICATION_CIKS = {
    "AAPL": "0000320193",
    "MSFT": "0000789019",
    "TSLA": "0001318605",
    "GOOGL": "0001652044",
    "META": "0001326801",
    "JPM":  "0000019617",
    "BRK.B": "0001067983",   # share-class punctuation test
}


def main() -> int:
    raw_json_path = ARTIFACT_DIR / f"_session1_rev{SOURCE_REV_ID}.json"
    if not raw_json_path.exists():
        raise SystemExit(f"missing raw revision: {raw_json_path}")

    raw = json.loads(raw_json_path.read_text())
    page = list(raw["query"]["pages"].values())[0]
    wikitext = page["revisions"][0]["slots"]["main"]["*"]

    df = parse_constituent_table(wikitext)
    edgar_table = fetch_edgar_tickers()

    # Re-resolve CIK from EDGAR for every ticker, in addition to the
    # in-table CIK. Mismatches are flagged but the in-table value wins
    # as the historical record (EDGAR keys current tickers only).
    df["cik_edgar"] = df["ticker"].map(lambda t: lookup_cik(t, edgar_table))
    df["cik_match"] = (df["cik"] == df["cik_edgar"])

    # Attach provenance to every row.
    df["source"] = "wikipedia"
    df["source_revision_id"] = SOURCE_REV_ID
    df["source_revision_ts"] = SOURCE_REV_TIMESTAMP

    out_path = ARTIFACT_DIR / "_session1_2020-12-21.parquet"
    df.to_parquet(out_path, index=False)

    # ---- verification report ----
    fixture_results: list[dict] = []
    for ticker, expected_cik in VERIFICATION_CIKS.items():
        row = df[df["ticker"] == ticker]
        observed_cik = (
            row["cik"].iloc[0] if len(row) and row["cik"].notna().any() else None
        )
        edgar_cik = lookup_cik(ticker, edgar_table)
        fixture_results.append({
            "ticker": ticker,
            "expected_cik": expected_cik,
            "observed_in_table_cik": observed_cik,
            "edgar_cik": edgar_cik,
            "in_table_matches_expected": observed_cik == expected_cik,
            "edgar_matches_expected": edgar_cik == expected_cik,
            "in_snapshot": bool(len(row)),
        })

    # TSLA-specific assertion (the headline verification).
    tsla_row = df[df["ticker"] == "TSLA"]
    tsla_present = bool(len(tsla_row))
    tsla_cik_correct = tsla_present and tsla_row["cik"].iloc[0] == "0001318605"

    # CIK match between Wikipedia table and EDGAR across the universe.
    cik_universe_match_rate = float(df["cik_match"].mean())
    cik_mismatches = (
        df[~df["cik_match"]][["ticker", "cik", "cik_edgar"]]
        .head(20).to_dict(orient="records")
    )
    null_cik_count = int(df["cik"].isna().sum())

    audit = {
        "session": "Phase 1 Session 1 — atom build",
        "built_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "page": "List of S&P 500 companies",
            "revision_id": SOURCE_REV_ID,
            "revision_ts": SOURCE_REV_TIMESTAMP,
            "revision_comment": SOURCE_REV_COMMENT,
            "raw_json": str(raw_json_path.name),
        },
        "snapshot": {
            "rows": int(len(df)),
            "unique_tickers": int(df["ticker"].nunique()),
            "non_null_cik": int(df["cik"].notna().sum()),
            "null_cik": null_cik_count,
            "non_null_sector": int(df["gics_sector"].notna().sum()),
            "non_null_date_added": int(
                (df["date_added_text"].notna() & (df["date_added_text"] != "")).sum()
            ),
        },
        "verification": {
            "tesla_headline": {
                "tsla_in_snapshot": tsla_present,
                "tsla_cik_correct": tsla_cik_correct,
                "tsla_date_added_text": (
                    str(tsla_row["date_added_text"].iloc[0]) if tsla_present else None
                ),
                "note_on_date_added_blank": (
                    "Source-data limitation: the editor who added TSLA in "
                    "this revision left the date_added cell blank. The "
                    "differ in later sessions must fall back to the "
                    "revision timestamp when the cell is empty for a "
                    "newly-added ticker."
                ),
            },
            "fixture": fixture_results,
            "cik_universe": {
                "wikipedia_vs_edgar_match_rate": cik_universe_match_rate,
                "first_20_mismatches": cik_mismatches,
            },
        },
        "artifact": {
            "parquet": str(out_path.name),
            "schema": list(df.columns),
        },
    }

    audit_path = ARTIFACT_DIR / "_session1_2020-12-21_audit.json"
    audit_path.write_text(json.dumps(audit, indent=2, default=str))

    # ---- console summary ----
    print(f"snapshot rows:                {len(df)}")
    print(f"unique tickers:               {df['ticker'].nunique()}")
    print(f"non-null in-table CIK:        {df['cik'].notna().sum()} / {len(df)}")
    print(f"in-table vs EDGAR CIK match:  {cik_universe_match_rate:.1%}")
    print(f"TSLA in snapshot:             {tsla_present}")
    print(f"TSLA CIK correct:             {tsla_cik_correct}")
    print(f"parquet artifact:             {out_path}")
    print(f"audit log:                    {audit_path}")

    if not (tsla_present and tsla_cik_correct):
        print("FAIL: Tesla headline verification did not pass.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
