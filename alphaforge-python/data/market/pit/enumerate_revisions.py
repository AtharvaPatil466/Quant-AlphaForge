"""Session 2 — enumerate every revision of the S&P 500 article 2010-01-01..today.

Pulls revision metadata only (no wikitext content). Paginates via
rvcontinue. Writes:

    artifacts/_revisions_full.parquet           — every revision, ascending by ts
    artifacts/_byte_delta_histogram.csv         — for empirical threshold calibration
    artifacts/_candidate_revisions.parquet      — filtered by MIN_BYTE_DELTA
    artifacts/_session2_audit.json              — provenance + summary stats

Per PIT_UNIVERSE_DESIGN.md §5.2: this is the empirical-calibration pass.
The histogram output is required reading before locking MIN_BYTE_DELTA.

Run:
    .venv/bin/python -m data.market.pit.enumerate_revisions
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

from .config import (
    MEMBERSHIP_COMMENT_RE, MIN_BYTE_DELTA, USER_AGENT, WIKI_API, WIKI_PAGE,
)

ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"
START_TS = "2010-01-01T00:00:00Z"
# rvend is exclusive of the past; today's date in UTC.
END_TS = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# Polite throttle. The Wikipedia API tolerates much higher rates for
# read traffic but 100ms × ~16 calls = 1.6s total — costless to be polite.
SLEEP_BETWEEN_CALLS_S = 0.1


def fetch_all_revisions() -> list[dict]:
    """Walk every revision of WIKI_PAGE in ascending order from START_TS to END_TS.

    Returns a list of dicts with keys: revid, parentid, timestamp, size, comment.
    """
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})

    out: list[dict] = []
    rvcontinue: str | None = None
    page_count = 0

    while True:
        params = {
            "action": "query",
            "prop": "revisions",
            "titles": WIKI_PAGE,
            "rvprop": "ids|timestamp|size|comment",
            "rvlimit": "max",  # 500 for anonymous, 5000 for authed bots
            "rvstart": START_TS,
            "rvend": END_TS,
            "rvdir": "newer",
            "format": "json",
            "formatversion": "2",
        }
        if rvcontinue:
            params["rvcontinue"] = rvcontinue

        resp = session.get(WIKI_API, params=params, timeout=30)
        resp.raise_for_status()
        body = resp.json()

        pages = body.get("query", {}).get("pages", [])
        if not pages:
            raise RuntimeError(f"unexpected API response: {body!r}")
        revs = pages[0].get("revisions", [])
        out.extend(revs)
        page_count += 1
        print(f"  page {page_count:3d}: +{len(revs):4d} revs (running total {len(out):,})")

        cont = body.get("continue")
        if not cont or "rvcontinue" not in cont:
            break
        rvcontinue = cont["rvcontinue"]
        time.sleep(SLEEP_BETWEEN_CALLS_S)

    return out


def main() -> int:
    print(f"enumerating revisions {START_TS} → {END_TS}")
    print(f"page: {WIKI_PAGE!r}")
    print()

    revs = fetch_all_revisions()
    if not revs:
        print("no revisions returned — abort")
        return 1

    df = pd.DataFrame(revs)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)

    # byte_delta = abs(size_t - size_{t-1}); first row is NaN.
    df["byte_delta"] = df["size"].diff().abs()

    # ---- write the full list ----
    full_path = ARTIFACT_DIR / "_revisions_full.parquet"
    # Parquet doesn't love mixed-type columns; ensure comment is a str.
    df["comment"] = df["comment"].fillna("").astype(str)
    df.to_parquet(full_path, index=False)

    # ---- byte-delta histogram for empirical calibration ----
    bins = [0, 10, 25, 50, 75, 100, 150, 200, 300, 500, 1000, 2500, 5000, 10000, 1_000_000]
    bin_labels = [
        f"[{bins[i]},{bins[i+1]})" for i in range(len(bins) - 1)
    ]
    df_nonnull = df.dropna(subset=["byte_delta"])
    hist = pd.cut(
        df_nonnull["byte_delta"], bins=bins, labels=bin_labels, right=False,
    ).value_counts().sort_index().rename("count")
    hist_pct = (hist / len(df_nonnull) * 100).round(2).rename("pct")
    hist_df = pd.concat([hist, hist_pct], axis=1).reset_index().rename(
        columns={"index": "bin"}
    )
    hist_path = ARTIFACT_DIR / "_byte_delta_histogram.csv"
    hist_df.to_csv(hist_path, index=False)

    # ---- candidate revisions: byte_delta >= MIN_BYTE_DELTA OR comment match ----
    bd_pass = df["byte_delta"].fillna(0) >= MIN_BYTE_DELTA
    cm_pass = df["comment"].apply(
        lambda c: bool(MEMBERSHIP_COMMENT_RE.search(c)) if isinstance(c, str) else False
    )
    df["candidate_reason_bytedelta"] = bd_pass
    df["candidate_reason_comment"] = cm_pass
    candidates = df[bd_pass | cm_pass].copy()
    candidates_path = ARTIFACT_DIR / "_candidate_revisions.parquet"
    candidates.to_parquet(candidates_path, index=False)

    # Quick sanity: confirm known events are caught.
    tesla_in_full = bool((df["revid"] == 995546256).any())
    tesla_in_candidates = bool((candidates["revid"] == 995546256).any())
    fb_meta_in_full = bool((df["revid"] == 1092243288).any())
    fb_meta_in_candidates = bool((candidates["revid"] == 1092243288).any())

    # ---- summary stats ----
    bd = df_nonnull["byte_delta"]
    summary_stats = {
        "total_revisions": int(len(df)),
        "first_revision_ts": str(df["timestamp"].iloc[0]),
        "last_revision_ts": str(df["timestamp"].iloc[-1]),
        "byte_delta": {
            "count_with_delta": int(len(bd)),
            "min": float(bd.min()),
            "p25": float(bd.quantile(0.25)),
            "median": float(bd.median()),
            "p75": float(bd.quantile(0.75)),
            "p90": float(bd.quantile(0.90)),
            "p95": float(bd.quantile(0.95)),
            "p99": float(bd.quantile(0.99)),
            "max": float(bd.max()),
        },
        "candidate_count_at_current_threshold": int(len(candidates)),
        "candidate_pct_at_current_threshold": round(len(candidates) / len(df) * 100, 2),
        "candidate_breakdown": {
            "bytedelta_only": int((bd_pass & ~cm_pass).sum()),
            "comment_only": int((~bd_pass & cm_pass).sum()),
            "both": int((bd_pass & cm_pass).sum()),
        },
        "known_events_in_candidate_set": {
            "tesla_add_995546256": tesla_in_candidates,
            "fb_meta_rename_1092243288": fb_meta_in_candidates,
        },
        "known_events_in_full_list": {
            "tesla_add_995546256": tesla_in_full,
            "fb_meta_rename_1092243288": fb_meta_in_full,
        },
    }

    audit = {
        "session": "Phase 1 Session 2 — revision enumeration + byte-delta calibration",
        "built_at": datetime.now(timezone.utc).isoformat(),
        "config": {
            "MIN_BYTE_DELTA": MIN_BYTE_DELTA,
            "page": WIKI_PAGE,
            "start_ts": START_TS,
            "end_ts": END_TS,
        },
        "outputs": {
            "full_revisions_parquet": str(full_path.name),
            "byte_delta_histogram_csv": str(hist_path.name),
            "candidate_revisions_parquet": str(candidates_path.name),
        },
        "summary": summary_stats,
        "histogram": hist_df.to_dict(orient="records"),
    }
    audit_path = ARTIFACT_DIR / "_session2_audit.json"
    audit_path.write_text(json.dumps(audit, indent=2, default=str))

    # ---- console summary ----
    print()
    print(f"total revisions:                 {len(df):,}")
    print(f"window:                          {df['timestamp'].iloc[0]} → {df['timestamp'].iloc[-1]}")
    print()
    print(f"byte_delta percentiles:")
    print(f"  min                            {bd.min():.0f}")
    print(f"  median                         {bd.median():.0f}")
    print(f"  p75                            {bd.quantile(0.75):.0f}")
    print(f"  p90                            {bd.quantile(0.90):.0f}")
    print(f"  p95                            {bd.quantile(0.95):.0f}")
    print(f"  p99                            {bd.quantile(0.99):.0f}")
    print(f"  max                            {bd.max():.0f}")
    print()
    print(f"candidates (delta>={MIN_BYTE_DELTA} OR comment-keyword): "
          f"{len(candidates):,} / {len(df):,} ({len(candidates)/len(df)*100:.1f}%)")
    print(f"  bytedelta-only:                {int((bd_pass & ~cm_pass).sum()):>4d}")
    print(f"  comment-only:                  {int((~bd_pass & cm_pass).sum()):>4d}")
    print(f"  both signals:                  {int((bd_pass & cm_pass).sum()):>4d}")
    print()
    print(f"known events captured?")
    print(f"  TSLA addition  (rev 995546256, bd=96):       {tesla_in_candidates}")
    print(f"  FB→META rename (rev 1092243288, bd=4):       {fb_meta_in_candidates}")
    print()
    print(f"artifacts:")
    print(f"  {full_path}")
    print(f"  {hist_path}")
    print(f"  {candidates_path}")
    print(f"  {audit_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
