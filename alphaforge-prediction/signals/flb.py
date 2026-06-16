"""Pre-committed favorite-longshot-bias trial enumeration (substrate #10).

This module encodes the FROZEN trial set of
`research/PREDICTION_MARKETS_DESIGN.md` §4 and §16-ADDENDUM. It performs **no
calibration statistics** — those are the canonical `afgauntlet.binary`
primitives, consumed by `research/run_phase1.py`. What lives here is the
deterministic enumeration whose *count* is `N_trials` (the multiple-testing
deflation denominator, §4 + §10) and the calendar-midpoint IS/OOS split (§3).

Design facts encoded (do NOT change without a fresh contract — §14 rule 3):

  - **Price buckets (7):** (0,5], (5,15], (15,35], (35,65], (65,85], (85,95],
    (95,100) cents, as fractional edges ``[0, .05, .15, .35, .65, .85, .95, 1]``.
  - **Categories (§4 grouping):** crypto-short-horizon, sports, economics,
    weather, politics/other — plus the §16-ADDENDUM "exotics" MVE class, which
    is reported **separately, never pooled** with the non-MVE §4 groups.
  - **Extreme buckets carry the directional FLB hypothesis.** Longshot buckets
    (upper edge ≤ 0.15) expect realized YES frequency **below** implied
    (overpriced longshots → negative calibration gap). Favorite buckets (lower
    edge ≥ 0.85) expect realized **above** implied (underpriced favorites →
    positive gap). Interior buckets carry no directional hypothesis and are
    enumerated for the reliability curve only (not counted as FLB trials).
  - **Trial count for deflation (§4):** ``N_trials`` = the number of evaluated
    directional FLB cells = (extreme bucket × category) cells that are actually
    present in the data, plus the pooled-per-category extreme cells. The exact
    set present is data-dependent (empty cells are not "evaluated"); the
    orchestrator records the realized count and asserts it against the
    enumeration before reading any statistic.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

# ─── Price buckets (§4, frozen) ───────────────────────────────────────────────
# Fractional edges for the 7 cent buckets. ``reliability_curve`` treats the first
# bucket as closed-on-the-left (events at exactly 0 included) and every other as
# (lo, hi]; this matches afgauntlet.binary.reliability_curve exactly.
BUCKET_EDGES: tuple[float, ...] = (0.0, 0.05, 0.15, 0.35, 0.65, 0.85, 0.95, 1.0)

# Human labels aligned to the edges above (len == len(EDGES) - 1).
BUCKET_LABELS: tuple[str, ...] = (
    "(0,5]", "(5,15]", "(15,35]", "(35,65]", "(65,85]", "(85,95]", "(95,100)",
)

# Extreme-region thresholds (§5 G1). A bucket is a LONGSHOT cell if its upper
# edge ≤ this; a FAVORITE cell if its lower edge ≥ this.
LONGSHOT_UPPER: float = 0.15   # buckets (0,5] and (5,15]
FAVORITE_LOWER: float = 0.85   # buckets (85,95] and (95,100)


class Direction(str, Enum):
    """FLB hypothesis direction for a bucket (matches afgauntlet gate strings)."""

    LONGSHOT = "negative"   # realized < implied  → fade overpriced longshots
    FAVORITE = "positive"   # realized > implied  → back underpriced favorites
    INTERIOR = "none"       # no directional FLB hypothesis (curve-only)


# ─── Category grouping (§4 + §16-ADDENDUM) ────────────────────────────────────
# The five pre-committed §4 groups, plus the ADDENDUM "exotics" MVE class that is
# reported separately. The free Kalshi host's first certified pull is 100%
# "Exotics" (sub-minute crypto/sports MVE); §16 mandates these are NOT pooled
# with the classic non-MVE event groups.
CAT_CRYPTO: str = "crypto-short-horizon"
CAT_SPORTS: str = "sports"
CAT_ECONOMICS: str = "economics"
CAT_WEATHER: str = "weather"
CAT_POLITICS_OTHER: str = "politics/other"
CAT_EXOTICS: str = "exotics"   # §16 MVE class — reported separately

#: §4 grouping, in pre-committed order. ``exotics`` is appended as the
#: ADDENDUM MVE class. The orchestrator reports exotics separately (§16).
CATEGORY_GROUPS: tuple[str, ...] = (
    CAT_CRYPTO, CAT_SPORTS, CAT_ECONOMICS, CAT_WEATHER, CAT_POLITICS_OTHER,
    CAT_EXOTICS,
)

#: Categories that are MVE (§16) and must never be pooled with non-MVE groups.
MVE_GROUPS: frozenset[str] = frozenset({CAT_EXOTICS})

# Raw-Kalshi-category → §4 group. Lower-cased substring match; the order is
# deliberate (most-specific first). Anything unmatched falls to politics/other,
# EXCEPT the literal "exotics" MVE bucket the free host emits.
_RAW_CATEGORY_RULES: tuple[tuple[str, str], ...] = (
    ("exotic", CAT_EXOTICS),       # §16 free-host MVE label
    ("crypto", CAT_CRYPTO),
    ("bitcoin", CAT_CRYPTO),
    ("ethereum", CAT_CRYPTO),
    ("sport", CAT_SPORTS),
    ("econom", CAT_ECONOMICS),
    ("financ", CAT_ECONOMICS),
    ("inflation", CAT_ECONOMICS),
    ("weather", CAT_WEATHER),
    ("climate", CAT_WEATHER),
    ("politic", CAT_POLITICS_OTHER),
    ("election", CAT_POLITICS_OTHER),
)


def map_category(raw: str | None) -> str:
    """Map a raw Kalshi event category to its pre-committed §4 group.

    Substring-matched, case-insensitive. Unknown/blank categories fall to
    ``politics/other`` (the §4 catch-all). The free-host ``"Exotics"`` MVE label
    maps to ``exotics`` so §16 separate-reporting can find it.
    """
    s = (raw or "").strip().lower()
    if not s:
        return CAT_POLITICS_OTHER
    for needle, group in _RAW_CATEGORY_RULES:
        if needle in s:
            return group
    return CAT_POLITICS_OTHER


# ─── Trial cells ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TrialCell:
    """One pre-committed directional FLB trial = (price-bucket × category).

    ``scope`` is ``"pooled"`` (all categories together, per-bucket) or
    ``"per-category"`` (one §4 group). ``category`` is "" for pooled cells.
    Only **extreme** buckets (longshot ≤15c / favorite ≥85c) carry a directional
    hypothesis and are enumerated as trials; interior buckets are not.
    """

    bucket_index: int
    bucket_label: str
    bin_lo: float
    bin_hi: float
    direction: str          # Direction value ("negative"/"positive")
    scope: str              # "pooled" | "per-category"
    category: str           # "" for pooled, else a CATEGORY_GROUPS member
    is_mve: bool            # True iff category ∈ MVE_GROUPS (§16 separate report)

    @property
    def cell_id(self) -> str:
        cat = self.category if self.category else "ALL"
        return f"{self.scope}:{cat}:{self.bucket_label}"

    def to_dict(self) -> dict:
        return {
            "cell_id": self.cell_id,
            "bucket_index": self.bucket_index,
            "bucket_label": self.bucket_label,
            "bin_lo": self.bin_lo,
            "bin_hi": self.bin_hi,
            "direction": self.direction,
            "scope": self.scope,
            "category": self.category,
            "is_mve": self.is_mve,
        }


def _extreme_buckets() -> list[tuple[int, str, float, float, str]]:
    """Return the extreme (directional) buckets as
    ``(index, label, lo, hi, direction)``.

    Longshot buckets: upper edge ≤ LONGSHOT_UPPER → negative-direction.
    Favorite buckets: lower edge ≥ FAVORITE_LOWER → positive-direction.
    """
    out: list[tuple[int, str, float, float, str]] = []
    for i in range(len(BUCKET_LABELS)):
        lo, hi = BUCKET_EDGES[i], BUCKET_EDGES[i + 1]
        label = BUCKET_LABELS[i]
        if hi <= LONGSHOT_UPPER:
            out.append((i, label, lo, hi, Direction.LONGSHOT.value))
        elif lo >= FAVORITE_LOWER:
            out.append((i, label, lo, hi, Direction.FAVORITE.value))
    return out


def present_categories(df: pd.DataFrame) -> list[str]:
    """The §4 groups actually present in ``df`` (mapped), in CATEGORY_GROUPS order.

    Used so per-category trials are only enumerated for groups that have data —
    an empty (bucket × category) cell is never "evaluated" and so does not enter
    the deflation denominator (§4: ``N_trials`` = number of *evaluated* cells).
    """
    if df.empty or "category" not in df.columns:
        return []
    mapped = {map_category(c) for c in df["category"].astype("object").tolist()}
    return [g for g in CATEGORY_GROUPS if g in mapped]


def enumerate_trials(df: pd.DataFrame) -> list[TrialCell]:
    """Enumerate the pre-committed directional FLB trial set for ``df``.

    Returns the list of :class:`TrialCell` actually evaluable on the data:

      - **Pooled** extreme cells: each extreme bucket, all NON-MVE categories
        pooled (§16: MVE is never pooled with non-MVE). Enumerated iff ≥1 non-MVE
        category is present.
      - **Per-category** extreme cells: each extreme bucket × each present §4
        group (including MVE groups, which stand alone). A cell is enumerated iff
        that group is present in the data (empty cells are not trials).

    The **count** of the returned list is ``N_trials`` for deflation (§4 / §10).
    Deterministic and order-stable: pooled cells first (bucket order), then
    per-category cells (category order, then bucket order).
    """
    extremes = _extreme_buckets()
    present = present_categories(df)
    non_mve_present = [g for g in present if g not in MVE_GROUPS]

    cells: list[TrialCell] = []

    # Pooled non-MVE extreme cells (only if any non-MVE category exists).
    if non_mve_present:
        for idx, label, lo, hi, direction in extremes:
            cells.append(TrialCell(
                bucket_index=idx, bucket_label=label, bin_lo=lo, bin_hi=hi,
                direction=direction, scope="pooled", category="", is_mve=False,
            ))

    # Per-category extreme cells, in CATEGORY_GROUPS order.
    for group in present:
        is_mve = group in MVE_GROUPS
        for idx, label, lo, hi, direction in extremes:
            cells.append(TrialCell(
                bucket_index=idx, bucket_label=label, bin_lo=lo, bin_hi=hi,
                direction=direction, scope="per-category", category=group,
                is_mve=is_mve,
            ))
    return cells


def n_trials(df: pd.DataFrame) -> int:
    """``N_trials`` = number of evaluated directional FLB cells (§4)."""
    return len(enumerate_trials(df))


# ─── IS / OOS calendar-midpoint split (§3) ────────────────────────────────────

@dataclass(frozen=True)
class CalendarSplit:
    """Result of the §3 calendar-midpoint split by ``close_time``."""

    midpoint_ns: int
    is_mask: np.ndarray   # bool, True = in-sample (close_time < midpoint)
    oos_mask: np.ndarray  # bool, True = out-of-sample (close_time >= midpoint)
    n_is: int
    n_oos: int

    def to_dict(self) -> dict:
        from ingest import schema as S
        return {
            "midpoint_ns": int(self.midpoint_ns),
            "midpoint_iso": S.ns_to_iso(int(self.midpoint_ns)),
            "n_is": int(self.n_is),
            "n_oos": int(self.n_oos),
        }


def calendar_midpoint_split(df: pd.DataFrame) -> CalendarSplit:
    """Split ``df`` into IS/OOS halves at the calendar midpoint of ``close_time``.

    Per §3: "first half = IS/design, second half = OOS/validation. A contract is
    assigned to a half by its ``close_time``." The midpoint is the arithmetic
    mean of the min/max ``close_time`` (calendar time, not the row-count
    median). Rows with ``close_time < midpoint`` are IS; ``>= midpoint`` are OOS.
    """
    if df.empty:
        empty = np.zeros(0, dtype=bool)
        return CalendarSplit(0, empty, empty, 0, 0)
    close = df["close_time"].astype("int64").to_numpy()
    lo, hi = int(close.min()), int(close.max())
    midpoint = (lo + hi) // 2
    is_mask = close < midpoint
    oos_mask = ~is_mask
    return CalendarSplit(
        midpoint_ns=midpoint,
        is_mask=is_mask,
        oos_mask=oos_mask,
        n_is=int(is_mask.sum()),
        n_oos=int(oos_mask.sum()),
    )


# ─── Helpers consumed by the orchestrator ─────────────────────────────────────

def region_for_cell(cell: TrialCell) -> tuple[float, float]:
    """The (lo, hi) calibration region for a cell's bucket.

    Returned as the open-left/closed-right region accepted by the afgauntlet
    gate constructors (``p > lo`` & ``p <= hi``). For the first bucket the lower
    bound is nudged below zero so events at exactly 0 are included, matching
    ``reliability_curve``'s closed-left first bucket.
    """
    lo = cell.bin_lo
    if cell.bucket_index == 0:
        lo = -1e-9
    return lo, cell.bin_hi


def select_frame(df: pd.DataFrame, cell: TrialCell) -> pd.DataFrame:
    """Subset ``df`` to a cell's category scope (price filtering happens in the gate).

    Pooled cells select all NON-MVE rows (§16). Per-category cells select rows
    whose mapped §4 group equals the cell's category.
    """
    if "category" not in df.columns:
        return df.iloc[0:0]
    mapped = df["category"].astype("object").map(map_category)
    if cell.scope == "pooled":
        keep = ~mapped.isin(list(MVE_GROUPS))
    else:
        keep = mapped == cell.category
    return df.loc[keep.to_numpy()]


def predicted_outcomes(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Extract ``(implied_prob, outcome01)`` arrays from a resolved frame.

    ``outcome01`` is 1.0 for a YES resolution, 0.0 for NO, derived from the
    ``result`` column (settlement-consistent by the Phase 0 validator).
    """
    if df.empty:
        return np.zeros(0), np.zeros(0)
    p = df["implied_prob"].astype(float).to_numpy()
    y = (df["result"].astype("string").str.lower() == "yes").astype(float).to_numpy()
    return p, y


def iter_buckets(edges: Sequence[float] = BUCKET_EDGES) -> Iterable[tuple[int, str, float, float]]:
    """Yield ``(index, label, lo, hi)`` for each price bucket."""
    for i in range(len(edges) - 1):
        yield i, BUCKET_LABELS[i], float(edges[i]), float(edges[i + 1])
