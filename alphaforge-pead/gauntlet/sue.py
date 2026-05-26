"""Standardized Unexpected Earnings (SUE) — seasonal random walk variant.

Implements the Bernard & Thomas (1989) SUE formulation pre-committed in
`research/PEAD_DESIGN.md` §1.

    SUE_{i, P} = (EPS(P) - EPS(P_prev_year)) /
                 std({EPS(k) - EPS(k_prev_year)}_{k in 8 prior quarters})

where P is identified by its `period_end` date (NOT by (fy, fp) — see
PEAD_DESIGN.md §2.2 addendum 2026-05-17: the SEC API's `fp` reflects the
filing-form's fiscal period, not the value's period, and is therefore
unsafe as a join key).

Seasonal predecessor lookup:
    Given a focal period_end `P`, the predecessor is the period_end
    `P'` such that (P - P') ∈ [350, 380] days. There must be EXACTLY
    ONE such predecessor in the firm's calendar; if zero (insufficient
    history) or more than one (data corruption — overlapping periods),
    SUE returns NaN.

The 8-prior-quarters denominator iterates over the 8 most recent
period_ends strictly less than P, each looked up via the same ±15-day
window for ITS seasonal predecessor.

This module is PURE. Input is a dict[date, float] of EPS values keyed
by period_end. Caller is responsible for as-of-date discipline (only
include values whose `filed` ≤ as_of_ts) and for filtering to
period_kind=="quarterly" (so 90-day periods only — no YTD-cumulative).
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Iterable, Optional


__all__ = [
    "SEASONAL_GAP_MIN_DAYS",
    "SEASONAL_GAP_MAX_DAYS",
    "seasonal_predecessor",
    "compute_sue",
    "compute_sue_panel",
]


# Tolerance window around 365 days for the "same fiscal quarter year ago"
# lookup. Accounts for 53-week fiscal years (where one quarter may span
# 14 weeks) and day-of-week effects on period boundaries.
SEASONAL_GAP_MIN_DAYS = 350
SEASONAL_GAP_MAX_DAYS = 380


def seasonal_predecessor(
    eps_by_period_end: dict[date, float], focal: date,
) -> Optional[date]:
    """Find the period_end ~1 year before `focal` in the firm's calendar.

    Returns the unique period_end P' such that
    `SEASONAL_GAP_MIN_DAYS ≤ (focal - P').days ≤ SEASONAL_GAP_MAX_DAYS`.
    Returns None if zero or >1 candidates match (ambiguous = error).
    """
    candidates = [
        p for p in eps_by_period_end
        if SEASONAL_GAP_MIN_DAYS <= (focal - p).days <= SEASONAL_GAP_MAX_DAYS
    ]
    if len(candidates) == 1:
        return candidates[0]
    return None


def _prior_quarters(
    eps_by_period_end: dict[date, float], focal: date, n: int,
) -> Optional[list[date]]:
    """Return the `n` most recent period_ends strictly less than `focal`,
    sorted in chronological (ascending) order. Returns None if fewer
    than `n` such period_ends exist."""
    priors = sorted(p for p in eps_by_period_end if p < focal)
    if len(priors) < n:
        return None
    return priors[-n:]


def compute_sue(
    eps_by_period_end: dict[date, float],
    focal: date,
    history_window: int = 8,
) -> float:
    """SUE for firm-quarter identified by period_end `focal`.

    Args:
        eps_by_period_end: mapping period_end -> diluted EPS, as known
            on the announcement date of the focal period. Caller is
            responsible for as-of-date discipline and quarterly-only
            filtering (period_kind=="quarterly").
        focal: the period_end of the focal quarter.
        history_window: pre-committed at 8 in PEAD_DESIGN.md §1.

    Returns:
        SUE as float, or NaN if undefined (missing data, ambiguous
        seasonal lookup, or zero denominator).
    """
    focal_val = eps_by_period_end.get(focal)
    if focal_val is None or not math.isfinite(focal_val):
        return math.nan

    pred = seasonal_predecessor(eps_by_period_end, focal)
    if pred is None:
        return math.nan
    pred_val = eps_by_period_end[pred]
    if not math.isfinite(pred_val):
        return math.nan
    numerator = focal_val - pred_val

    priors = _prior_quarters(eps_by_period_end, focal, history_window)
    if priors is None:
        return math.nan

    differences: list[float] = []
    for k in priors:
        k_pred = seasonal_predecessor(eps_by_period_end, k)
        if k_pred is None:
            return math.nan
        k_val = eps_by_period_end[k]
        k_pred_val = eps_by_period_end[k_pred]
        if not (math.isfinite(k_val) and math.isfinite(k_pred_val)):
            return math.nan
        differences.append(k_val - k_pred_val)

    if len(differences) < history_window:
        return math.nan

    mean = sum(differences) / len(differences)
    var = sum((d - mean) ** 2 for d in differences) / (len(differences) - 1)  # ddof=1
    if var <= 0:
        return math.nan
    denom = math.sqrt(var)
    if not math.isfinite(denom) or denom == 0:
        return math.nan
    return numerator / denom


def compute_sue_panel(
    eps_by_period_end: dict[date, float],
    focal_periods: Iterable[date],
    history_window: int = 8,
) -> dict[date, float]:
    """Convenience: compute SUE for a list of focal period_ends.

    Returns mapping period_end -> SUE (or NaN). Periods with undefined
    SUE remain in the result; callers filter NaN downstream.
    """
    return {
        p: compute_sue(eps_by_period_end, p, history_window=history_window)
        for p in focal_periods
    }
