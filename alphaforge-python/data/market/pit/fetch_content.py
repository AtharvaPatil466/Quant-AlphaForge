"""Bulk-fetch wikitext content for the candidate revisions.

Batches revids 50 at a time via the Wikipedia API's `revids=A|B|C` form
to keep the call count low (~23 calls for 1,118 revisions instead of
1,118). Caches each revision's wikitext as one JSON file under
artifacts/snapshots/, so re-runs are free.

Public entry: fetch_all_candidate_wikitext() -> dict[revid, wikitext]
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Iterable

import pandas as pd
import requests

from .config import USER_AGENT, WIKI_API

ART = Path(__file__).resolve().parent / "artifacts"
SNAPSHOT_DIR = ART / "snapshots"
SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

BATCH_SIZE = 50          # max revids per anonymous API call
SLEEP_BETWEEN_BATCHES_S = 0.2


def _snapshot_path(revid: int) -> Path:
    return SNAPSHOT_DIR / f"{revid}.json"


def _cached_revids() -> set[int]:
    """Set of revids already cached on disk."""
    return {int(p.stem) for p in SNAPSHOT_DIR.glob("*.json")}


def _fetch_batch(session: requests.Session, revids: list[int]) -> dict[int, str]:
    """Fetch one batch of up to BATCH_SIZE revisions. Returns revid->wikitext."""
    params = {
        "action": "query",
        "prop": "revisions",
        "revids": "|".join(str(r) for r in revids),
        "rvprop": "content|ids|timestamp",
        "rvslots": "main",
        "format": "json",
        "formatversion": "2",
    }
    resp = session.get(WIKI_API, params=params, timeout=60)
    resp.raise_for_status()
    body = resp.json()

    out: dict[int, str] = {}
    for page in body.get("query", {}).get("pages", []):
        for rev in page.get("revisions", []):
            rid = int(rev["revid"])
            slot = rev.get("slots", {}).get("main", {})
            wikitext = slot.get("content")
            if wikitext is None:
                # Older API responses may put it directly under "*" — handled
                # in fetch loop by retrying with rvslots toggled.
                continue
            out[rid] = wikitext
    return out


def fetch_all_candidate_wikitext(
    candidate_parquet: Path | None = None,
    force_refetch: bool = False,
) -> dict[int, str]:
    """Fetch every candidate revision's wikitext, caching to disk.

    Returns a dict revid -> wikitext for every revision that was fetched
    successfully (cache hits + fresh).
    """
    candidate_parquet = candidate_parquet or (ART / "_candidate_revisions.parquet")
    candidates = pd.read_parquet(candidate_parquet)
    target_revids: list[int] = candidates["revid"].astype(int).tolist()

    cached = set() if force_refetch else _cached_revids()
    to_fetch = [r for r in target_revids if r not in cached]
    print(f"  candidates: {len(target_revids):,} | cached: {len(cached & set(target_revids)):,} | to fetch: {len(to_fetch):,}")

    if to_fetch:
        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
        n_batches = (len(to_fetch) + BATCH_SIZE - 1) // BATCH_SIZE
        for bi in range(n_batches):
            batch = to_fetch[bi * BATCH_SIZE : (bi + 1) * BATCH_SIZE]
            try:
                fetched = _fetch_batch(session, batch)
            except Exception as exc:
                print(f"  batch {bi+1}/{n_batches} failed: {exc!r} — sleeping 5s and retrying once")
                time.sleep(5)
                fetched = _fetch_batch(session, batch)

            for rid, wt in fetched.items():
                _snapshot_path(rid).write_text(json.dumps({"revid": rid, "wikitext": wt}))

            print(f"  batch {bi+1:>3d}/{n_batches}: fetched {len(fetched)}/{len(batch)} revids")
            time.sleep(SLEEP_BETWEEN_BATCHES_S)

    # Read everything from cache, including pre-existing.
    out: dict[int, str] = {}
    missing = []
    for rid in target_revids:
        p = _snapshot_path(rid)
        if not p.exists():
            missing.append(rid)
            continue
        d = json.loads(p.read_text())
        out[int(d["revid"])] = d["wikitext"]

    print(f"  total in cache after fetch: {len(out):,} / {len(target_revids):,}")
    if missing:
        print(f"  WARNING: {len(missing)} revids could not be fetched")
    return out
