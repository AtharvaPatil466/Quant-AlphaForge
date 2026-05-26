"""VIX regime characterization — Phase 1C (per VIX_DESIGN.md §8.3).

NOT a pass test — this is the *characterization* of the IS regime mix
used to inform Phase 2 position-sizing. The §8.3 buckets:

    VIX < 15        → low_vol
    15 ≤ VIX < 25   → normal
    25 ≤ VIX < 35   → elevated
    VIX ≥ 35        → crisis

Output: per-bucket fraction-of-days, mean VIX, mean daily VIX log change,
and per-year bucket breakdown.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .vrp import IS_END, IS_START


BUCKETS: tuple[tuple[str, float, float], ...] = (
    ("low_vol", 0.0, 15.0),
    ("normal", 15.0, 25.0),
    ("elevated", 25.0, 35.0),
    ("crisis", 35.0, float("inf")),
)


def _bucket(vix_value: float) -> str:
    for name, lo, hi in BUCKETS:
        if lo <= vix_value < hi:
            return name
    return "unknown"


@dataclass
class RegimeBucketStats:
    name: str
    lower: float
    upper: float
    n_days: int
    fraction: float
    mean_vix: float


@dataclass
class RegimeReport:
    is_window: tuple[pd.Timestamp, pd.Timestamp]
    n_days_total: int
    buckets: list[RegimeBucketStats] = field(default_factory=list)
    per_year_fraction_crisis: dict[int, float] = field(default_factory=dict)
    per_year_fraction_elevated: dict[int, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "is_start": str(self.is_window[0].date()),
            "is_end": str(self.is_window[1].date()),
            "n_days_total": self.n_days_total,
            "buckets": [
                {
                    "name": b.name, "lower": b.lower, "upper": b.upper,
                    "n_days": b.n_days, "fraction": b.fraction,
                    "mean_vix": b.mean_vix,
                }
                for b in self.buckets
            ],
            "per_year_fraction_crisis": {str(k): v
                                         for k, v in self.per_year_fraction_crisis.items()},
            "per_year_fraction_elevated": {str(k): v
                                           for k, v in self.per_year_fraction_elevated.items()},
        }


def characterize(
    vix: pd.Series,
    is_start: pd.Timestamp = IS_START,
    is_end: pd.Timestamp = IS_END,
) -> RegimeReport:
    """Bucket the IS VIX series. Returns counts, fractions, per-year crisis %."""
    s = vix.dropna()
    s = s[(s.index >= is_start) & (s.index <= is_end)]
    n = len(s)
    bucket_rows: list[RegimeBucketStats] = []
    if n == 0:
        return RegimeReport(
            is_window=(is_start, is_end),
            n_days_total=0,
            buckets=[RegimeBucketStats(name=name, lower=lo, upper=hi,
                                       n_days=0, fraction=0.0, mean_vix=float("nan"))
                     for name, lo, hi in BUCKETS],
        )
    for name, lo, hi in BUCKETS:
        mask = (s >= lo) & (s < hi)
        cnt = int(mask.sum())
        mean = float(s[mask].mean()) if cnt else float("nan")
        bucket_rows.append(RegimeBucketStats(
            name=name, lower=lo, upper=hi,
            n_days=cnt, fraction=cnt / n, mean_vix=mean,
        ))
    # Per-year crisis fraction.
    yearly_crisis: dict[int, float] = {}
    yearly_elev: dict[int, float] = {}
    by_year = s.groupby(s.index.year)
    for y, sub in by_year:
        if len(sub) == 0:
            continue
        crisis = int(((sub >= 35.0)).sum()) / len(sub)
        elev = int(((sub >= 25.0) & (sub < 35.0)).sum()) / len(sub)
        yearly_crisis[int(y)] = float(crisis)
        yearly_elev[int(y)] = float(elev)
    return RegimeReport(
        is_window=(is_start, is_end),
        n_days_total=n,
        buckets=bucket_rows,
        per_year_fraction_crisis=yearly_crisis,
        per_year_fraction_elevated=yearly_elev,
    )
