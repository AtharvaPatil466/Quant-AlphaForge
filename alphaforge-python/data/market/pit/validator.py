"""Phase 1 validation utilities.

Two main exports:

    cross_check_against_changes_table(events, changes) -> dict
        Compares our snapshot-diff event log against Wikipedia's curated
        "Selected changes" table. Each row in the changes table should
        have a matching ADD and REMOVE in our event log within a small
        date tolerance.

    membership_on_date(events, baseline, date) -> set[str]
        Replays the event log forward from the baseline to compute the
        set of in-index tickers on any date.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable, Optional

import pandas as pd


# ── Cross-check ──────────────────────────────────────────────────────

def _within_tolerance(d1: str, d2: str, tol_days: int = 7) -> bool:
    """True if two ISO date strings are within tol_days of each other."""
    a = date.fromisoformat(d1)
    b = date.fromisoformat(d2)
    return abs((a - b).days) <= tol_days


def cross_check_against_changes_table(
    events: pd.DataFrame,
    changes: pd.DataFrame,
    tol_days: int = 7,
    min_year: int = 2010,
) -> dict:
    """For each row in the curated changes table at-or-after `min_year`,
    verify our event log contains a matching ADD and REMOVE within
    tol_days of the effective_date.

    Returns:
        {
            "n_changes_checked": int,
            "matched_add": int, "missing_add": list[dict],
            "matched_remove": int, "missing_remove": list[dict],
            "summary_text": str,
        }
    """
    in_window = changes[
        pd.to_datetime(changes["effective_date"]).dt.year >= min_year
    ].copy()

    adds = events[events["action"] == "ADD"].set_index("ticker")
    removes = events[events["action"] == "REMOVE"].set_index("ticker")

    # Build lookup: ticker -> list of effective_dates with that action
    add_dates: dict[str, list[str]] = {}
    for ticker, dt in events.loc[events["action"] == "ADD", ["ticker", "effective_date"]].itertuples(
        index=False
    ):
        add_dates.setdefault(str(ticker), []).append(str(dt))

    remove_dates: dict[str, list[str]] = {}
    for ticker, dt in events.loc[events["action"] == "REMOVE", ["ticker", "effective_date"]].itertuples(
        index=False
    ):
        remove_dates.setdefault(str(ticker), []).append(str(dt))

    matched_add = 0
    missing_add: list[dict] = []
    matched_remove = 0
    missing_remove: list[dict] = []

    for row in in_window.itertuples(index=False):
        eff = str(row.effective_date)
        # ADD side
        added_t = row.added_ticker
        if added_t:
            candidates = add_dates.get(str(added_t), [])
            if any(_within_tolerance(eff, c, tol_days) for c in candidates):
                matched_add += 1
            else:
                missing_add.append({
                    "effective_date": eff,
                    "ticker": added_t,
                    "security": row.added_security,
                    "in_log_dates": candidates[:5],
                })
        # REMOVE side
        removed_t = row.removed_ticker
        if removed_t:
            candidates = remove_dates.get(str(removed_t), [])
            if any(_within_tolerance(eff, c, tol_days) for c in candidates):
                matched_remove += 1
            else:
                missing_remove.append({
                    "effective_date": eff,
                    "ticker": removed_t,
                    "security": row.removed_security,
                    "in_log_dates": candidates[:5],
                })

    n = len(in_window)
    return {
        "n_changes_checked": n,
        "matched_add": matched_add,
        "missing_add_count": len(missing_add),
        "missing_add_examples": missing_add[:20],
        "matched_remove": matched_remove,
        "missing_remove_count": len(missing_remove),
        "missing_remove_examples": missing_remove[:20],
        "summary_text": (
            f"changes table cross-check ({min_year}+, ±{tol_days}d): "
            f"ADD {matched_add}/{n} ({matched_add/n*100:.1f}%); "
            f"REMOVE {matched_remove}/{n} ({matched_remove/n*100:.1f}%)"
        ),
    }


# ── Membership replayer ──────────────────────────────────────────────

def membership_on_date(
    events: pd.DataFrame,
    baseline: Optional[Iterable[str]],
    target_date: str,
) -> set[str]:
    """Replay the event log forward from `baseline` (set of tickers
    in the index on Phase-1 day-zero) to compute the in-index ticker
    set on `target_date` (ISO YYYY-MM-DD).

    Pass baseline=None to start from an empty set (only useful when
    asking for a date later than the first ADD events captured).
    """
    members = set(baseline) if baseline else set()

    # Apply events in chronological order, up through target_date.
    upto = events[events["effective_date"] <= target_date].sort_values("effective_date")
    for r in upto.itertuples(index=False):
        action = r.action
        ticker = str(r.ticker)
        cp = (str(r.counterparty_ticker)
              if pd.notna(r.counterparty_ticker) else None)
        if action == "ADD":
            members.add(ticker)
        elif action == "REMOVE":
            members.discard(ticker)
        elif action == "RENAME":
            # Rename: counterparty_ticker is the OLD ticker; ticker is the NEW.
            if cp:
                members.discard(cp)
            members.add(ticker)
        # MERGE / SPINOFF treated as REMOVE for membership purposes
        elif action in {"MERGE", "SPINOFF"}:
            members.discard(ticker)
    return members
