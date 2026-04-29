"""CIK-based differ — turn a chronological sequence of parsed snapshots
into a membership event log.

Per PIT_UNIVERSE_DESIGN.md §5.3:
  - ADD     : ticker in S_i but not S_{i-1} (no CIK match in prior)
  - REMOVE  : ticker in S_{i-1} but not S_i (no CIK match in current)
  - RENAME  : same CIK present in both, but ticker changed

Action precedence (§4.1) — MERGE > REMOVE > RENAME > ADD — is applied
per (cik, effective_date). MERGE/SPINOFF are not detected by the differ
in this session; they come in as REMOVE events and get upgraded by
hand-curated overrides in a later session.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from typing import Iterable, Optional

import pandas as pd


@dataclass(frozen=True)
class ParsedSnapshot:
    revid: int
    timestamp: pd.Timestamp        # UTC
    comment: str
    df: pd.DataFrame               # parsed by parser.parse_constituent_table


def _signature(df: pd.DataFrame) -> frozenset:
    """Identity signature of a snapshot for fast change-detection.

    Keyed on (cik, ticker) tuples — CIK alone would miss pure ticker
    renames; ticker alone would miss the CIK-resolved RENAME path.
    """
    rows = df[["cik", "ticker"]].dropna(subset=["ticker"])
    return frozenset(
        (str(r.cik) if pd.notna(r.cik) else None, str(r.ticker))
        for r in rows.itertuples(index=False)
    )


def _row_lookup(df: pd.DataFrame) -> dict[tuple[Optional[str], str], dict]:
    """Build a lookup keyed by (cik, ticker) -> full row dict."""
    out: dict[tuple[Optional[str], str], dict] = {}
    for r in df.dropna(subset=["ticker"]).itertuples(index=False):
        key = (str(r.cik) if pd.notna(r.cik) else None, str(r.ticker))
        out[key] = {
            "ticker": str(r.ticker),
            "cik": str(r.cik) if pd.notna(r.cik) else None,
            "company_name": str(r.company_name) if pd.notna(r.company_name) else None,
            "gics_sector": str(r.gics_sector) if pd.notna(r.gics_sector) else None,
            "gics_sub_industry": str(r.gics_sub_industry) if pd.notna(r.gics_sub_industry) else None,
            "headquarters": str(r.headquarters) if pd.notna(r.headquarters) else None,
            "date_added_text": str(r.date_added_text) if pd.notna(r.date_added_text) else None,
            "founded_text": str(r.founded_text) if pd.notna(r.founded_text) else None,
        }
    return out


def _by_cik(rows: dict[tuple[Optional[str], str], dict]) -> dict[str, list[dict]]:
    """Group rows by CIK (skipping null-CIK rows)."""
    out: dict[str, list[dict]] = {}
    for (cik, _ticker), row in rows.items():
        if cik:
            out.setdefault(cik, []).append(row)
    return out


def _by_ticker(rows: dict[tuple[Optional[str], str], dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for (_cik, ticker), row in rows.items():
        out.setdefault(ticker, []).append(row)
    return out


def _det_event_id(prev_rev: int, curr_rev: int, cik: Optional[str], ticker: str, action: str) -> str:
    """Deterministic event_id so re-running produces stable IDs."""
    h = hashlib.sha1(
        f"{prev_rev}|{curr_rev}|{cik or ''}|{ticker}|{action}".encode()
    ).hexdigest()[:16]
    return f"evt_{h}"


# Action precedence per §4.1 — higher value wins.
_PRECEDENCE = {"ADD": 1, "RENAME": 2, "REMOVE": 3, "MERGE": 4, "SPINOFF": 4}


def _diff_pair(prev: ParsedSnapshot, curr: ParsedSnapshot) -> list[dict]:
    """Diff one pair of consecutive snapshots, returning event rows."""
    prev_rows = _row_lookup(prev.df)
    curr_rows = _row_lookup(curr.df)

    prev_by_cik = _by_cik(prev_rows)
    curr_by_cik = _by_cik(curr_rows)
    prev_by_tkr = _by_ticker(prev_rows)
    curr_by_tkr = _by_ticker(curr_rows)

    # Effective date defaults to current revision timestamp (per §5.4
    # session-1 lesson: blank cells in the first-touch revision are
    # common). We store both the source revision timestamp and (where
    # available) the in-table date_added_text.
    eff_date = curr.timestamp.normalize().date().isoformat()

    events: list[dict] = []

    # 1) RENAME: same CIK, different ticker
    seen_renamed_ciks: set[str] = set()
    for cik, curr_rows_list in curr_by_cik.items():
        prev_rows_list = prev_by_cik.get(cik)
        if not prev_rows_list:
            continue
        prev_tickers = {r["ticker"] for r in prev_rows_list}
        curr_tickers = {r["ticker"] for r in curr_rows_list}
        added = curr_tickers - prev_tickers
        removed = prev_tickers - curr_tickers
        if added and removed:
            # Pure rename: same CIK, old ticker gone, new ticker in.
            # If multiple options, pair them deterministically.
            for new_ticker, old_ticker in zip(sorted(added), sorted(removed)):
                events.append({
                    "event_id": _det_event_id(prev.revid, curr.revid, cik, new_ticker, "RENAME"),
                    "effective_date": eff_date,
                    "announcement_date": None,
                    "ticker": new_ticker,
                    "cik": cik,
                    "company_name": next(
                        (r["company_name"] for r in curr_rows_list if r["ticker"] == new_ticker),
                        None,
                    ),
                    "action": "RENAME",
                    "counterparty_ticker": old_ticker,
                    "source": "wikipedia",
                    "source_revision_id": str(curr.revid),
                    "notes": f"CIK {cik} ticker change {old_ticker} → {new_ticker}",
                })
            seen_renamed_ciks.add(cik)

    # 2) ADD: ticker in current, not in previous, AND CIK not seen as
    #    a rename above (otherwise we double-count).
    for (cik, ticker), row in curr_rows.items():
        if (cik, ticker) in prev_rows:
            continue
        if cik and cik in seen_renamed_ciks:
            continue
        # Not a rename — genuinely new.
        events.append({
            "event_id": _det_event_id(prev.revid, curr.revid, cik, ticker, "ADD"),
            "effective_date": eff_date,
            "announcement_date": None,
            "ticker": ticker,
            "cik": cik,
            "company_name": row["company_name"],
            "action": "ADD",
            "counterparty_ticker": None,
            "source": "wikipedia",
            "source_revision_id": str(curr.revid),
            "notes": (
                f"in-table date_added: {row['date_added_text']}"
                if row["date_added_text"] else
                "first-touch revision; date_added cell blank, effective_date inferred from revision timestamp"
            ),
        })

    # 3) REMOVE: ticker in previous, not in current, AND CIK not seen as
    #    a rename above.
    for (cik, ticker), row in prev_rows.items():
        if (cik, ticker) in curr_rows:
            continue
        if cik and cik in seen_renamed_ciks:
            continue
        events.append({
            "event_id": _det_event_id(prev.revid, curr.revid, cik, ticker, "REMOVE"),
            "effective_date": eff_date,
            "announcement_date": None,
            "ticker": ticker,
            "cik": cik,
            "company_name": row["company_name"],
            "action": "REMOVE",
            "counterparty_ticker": None,
            "source": "wikipedia",
            "source_revision_id": str(curr.revid),
            "notes": f"comment: {curr.comment[:120]!r}" if curr.comment else None,
        })

    return events


def _resolve_precedence(events: list[dict]) -> list[dict]:
    """Apply action precedence per §4.1 to collapse collisions on
    (ticker, effective_date)."""
    keyed: dict[tuple[str, str], dict] = {}
    for e in events:
        k = (e["ticker"], e["effective_date"])
        if k not in keyed:
            keyed[k] = e
            continue
        existing = keyed[k]
        if _PRECEDENCE[e["action"]] > _PRECEDENCE[existing["action"]]:
            # Merge notes from the loser into the winner.
            merged_notes = "; ".join(
                filter(None, [e.get("notes"), f"superseded {existing['action']}: {existing.get('notes')}"])
            )
            e2 = dict(e)
            e2["notes"] = merged_notes or e2.get("notes")
            keyed[k] = e2
        else:
            existing["notes"] = "; ".join(
                filter(None, [existing.get("notes"), f"superseded {e['action']}: {e.get('notes')}"])
            )
    return list(keyed.values())


# A real S&P index event is 1-3 changes per revision, occasionally up to
# ~5 in a quarterly rebalance. Any single transition emitting more
# events than this is overwhelmingly likely to be parser noise (mid-edit
# vandalism, format-era misalignment, transient ref/template breakage).
MAX_PLAUSIBLE_EVENTS_PER_PAIR = 8


def diff_snapshot_sequence(snapshots: list[ParsedSnapshot]) -> pd.DataFrame:
    """Walk a chronological list of parsed snapshots and produce events.

    Skips consecutive pairs whose signatures are identical (cheap O(1)
    comparison) — this is what makes the hybrid filter's permissiveness
    affordable.

    Suspect-pair guard: if a transition would emit more than
    MAX_PLAUSIBLE_EVENTS_PER_PAIR events, the pair is rejected as parser
    noise. `prev` is NOT advanced, so the next non-skipped revision is
    diffed against the same trusted baseline. This converts parser
    glitches into "no-event windows" instead of phantom REMOVE/ADD pairs.
    """
    if len(snapshots) < 2:
        return pd.DataFrame(columns=[
            "event_id", "effective_date", "announcement_date", "ticker", "cik",
            "company_name", "action", "counterparty_ticker", "source",
            "source_revision_id", "notes",
        ])

    all_events: list[dict] = []
    skipped_unchanged = 0
    skipped_suspect = 0
    diffed = 0
    suspect_log: list[dict] = []

    prev = snapshots[0]
    prev_sig = _signature(prev.df)

    for curr in snapshots[1:]:
        curr_sig = _signature(curr.df)
        if curr_sig == prev_sig:
            skipped_unchanged += 1
            continue

        candidate_events = _diff_pair(prev, curr)
        if len(candidate_events) > MAX_PLAUSIBLE_EVENTS_PER_PAIR:
            skipped_suspect += 1
            suspect_log.append({
                "prev_revid": prev.revid,
                "curr_revid": curr.revid,
                "curr_timestamp": str(curr.timestamp),
                "candidate_event_count": len(candidate_events),
                "comment": curr.comment[:100],
            })
            # ADVANCE prev — otherwise drift against a stale baseline
            # would make every subsequent transition look suspect. We
            # accept losing a small number of real changes near the noise
            # in exchange for resilience against accumulating drift.
            prev = curr
            prev_sig = curr_sig
            continue

        all_events.extend(candidate_events)
        diffed += 1
        prev = curr
        prev_sig = curr_sig

    print(f"  differ: {diffed} change-pairs accepted, "
          f"{skipped_unchanged} no-change, {skipped_suspect} suspect")
    if suspect_log:
        # Persist the suspect log alongside the event log so it can be
        # audited / used to drive parser improvements.
        from pathlib import Path
        sus_path = Path(__file__).resolve().parent / "artifacts" / "_suspect_pairs.csv"
        pd.DataFrame(suspect_log).to_csv(sus_path, index=False)
        print(f"  suspect pair log: {sus_path}")

    resolved = _resolve_precedence(all_events)
    df = pd.DataFrame(resolved)
    if not df.empty:
        df = df.sort_values(["effective_date", "action", "ticker"]).reset_index(drop=True)
    return df
