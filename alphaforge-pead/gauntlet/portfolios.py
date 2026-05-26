"""Portfolio formation + IC computation for the PEAD gauntlet.

Two primary functions, both consuming the announcement-event panel
produced by `gauntlet.panel.build_panel_for_firm`:

  - `compute_ic(panel, horizon)` — Spearman rank correlation between SUE
    and fwd_return at the given horizon. The foundational predictive-
    power metric.

  - `form_long_short(panel, horizon, bucket)` — bucket firms by SUE
    quantile, return the per-event long-short payoff:
        payoff = fwd_return_K(top_bucket) - fwd_return_K(bottom_bucket)
    plus the daily long-short return series for downstream Sharpe / DSR.

The bucketing is **event-time cross-section** as pre-committed in
`PEAD_DESIGN.md` §3.1: within each calendar trading day, take all firms
whose announcement_ts falls on that day, rank by SUE, form quintile or
decile cuts. A day with only 1–2 announcements is dropped — quantile
cuts on tiny cross-sections are degenerate.

The minimum cross-section size to form a cut is pre-committed at:
  - quintile (top/bottom 20%): 5 firms minimum
  - decile (top/bottom 10%): 10 firms minimum

These are the natural lower bounds of the respective cuts; they are NOT
tunable.

THIS MODULE IS PHASE 1 CODE. Per `PEAD_DESIGN.md` §8 it does not run
against real data until `PEAD_PHASE0_CERTIFIED.md` is filed. Tests use
synthetic panels.
"""

from __future__ import annotations

import logging
import math
from typing import Literal, Optional

import numpy as np
import pandas as pd
from scipy import stats


log = logging.getLogger(__name__)


BUCKET_CONFIG = {
    "quintile": {"frac": 0.20, "min_size": 5},
    "decile":   {"frac": 0.10, "min_size": 10},
}


__all__ = [
    "BUCKET_CONFIG",
    "compute_ic",
    "form_long_short",
    "long_short_summary",
]


# --- IC -------------------------------------------------------------------


def compute_ic(panel: pd.DataFrame, horizon: int) -> dict:
    """Spearman IC between SUE and fwd_return at `horizon`, across all
    valid rows in the panel.

    Returns:
        dict with keys:
            ic         — Spearman rho (float, NaN if undefined)
            p_value    — two-sided p-value
            n_events   — number of (sue, fwd_return) pairs used
            horizon    — passed through

    NaN values in `sue` or `fwd_return_K` are dropped before the
    correlation. If fewer than 30 pairs survive, returns NaN IC with a
    log warning — too small a sample for the rank correlation to be
    meaningful.
    """
    col = f"fwd_return_{horizon}"
    if col not in panel.columns:
        raise ValueError(f"panel missing column {col}")

    sub = panel[["sue", col]].dropna()
    n = len(sub)
    if n < 30:
        log.warning("compute_ic: only %d valid events for K=%d; returning NaN IC", n, horizon)
        return {"ic": math.nan, "p_value": math.nan, "n_events": n, "horizon": horizon}

    rho, p = stats.spearmanr(sub["sue"].values, sub[col].values)
    return {
        "ic": float(rho) if not math.isnan(rho) else math.nan,
        "p_value": float(p) if not math.isnan(p) else math.nan,
        "n_events": int(n),
        "horizon": int(horizon),
    }


# --- long-short quantile portfolio --------------------------------------


def _assign_buckets(
    sue_values: np.ndarray, frac: float, min_size: int
) -> Optional[np.ndarray]:
    """Return an integer array of {-1, 0, +1} same length as `sue_values`:
    -1 = bottom quantile (short), +1 = top quantile (long), 0 = neutral.

    Returns None if the cross-section is too small or SUE has degenerate
    rank (e.g., all-identical values).
    """
    n = len(sue_values)
    if n < min_size:
        return None
    # rankdata uses 1..n; we want 0..n-1 for percentile math
    ranks = stats.rankdata(sue_values, method="average") - 1
    # Number of firms in each tail bucket
    k = max(1, int(round(n * frac)))
    out = np.zeros(n, dtype=np.int8)
    # Bottom k → -1
    out[ranks < k] = -1
    # Top k → +1
    out[ranks >= (n - k)] = 1
    # Degenerate: if every firm got the same rank, all ranks equal
    # (n-1)/2 and the bucketing is meaningless. Detect via unique ranks.
    if len(set(ranks)) <= 2:
        return None
    return out


def form_long_short(
    panel: pd.DataFrame,
    horizon: int,
    bucket: Literal["quintile", "decile"] = "quintile",
) -> pd.DataFrame:
    """Form per-event long-short positions on the announcement panel.

    For each announcement_ts (treated as a daily cross-section), rank
    firms by SUE, assign top/bottom quantile cuts, attach per-event
    long-short payoffs.

    Returns a DataFrame with the original columns plus:
        bucket_side : int in {-1, 0, +1}
        weight      : float — equal within bucket on each cross-section
    Rows with bucket_side == 0 are kept for audit but ignored downstream.

    Cross-sections too small for the cut are dropped (with a log line);
    rows from those days have NO output rows in the returned frame.
    """
    if bucket not in BUCKET_CONFIG:
        raise ValueError(f"unknown bucket {bucket!r}; expected one of {list(BUCKET_CONFIG)}")
    cfg = BUCKET_CONFIG[bucket]
    col = f"fwd_return_{horizon}"
    if col not in panel.columns:
        raise ValueError(f"panel missing column {col}")

    # Drop rows where SUE is NaN — they cannot be ranked.
    sub = panel.dropna(subset=["sue"]).copy()

    # Group by trading-day-of-announcement
    sub["announcement_day"] = pd.to_datetime(sub["announcement_ts"]).dt.date

    out_chunks = []
    dropped_days = 0
    for day, group in sub.groupby("announcement_day"):
        sue_vals = group["sue"].values
        buckets = _assign_buckets(sue_vals, frac=cfg["frac"], min_size=cfg["min_size"])
        if buckets is None:
            dropped_days += 1
            continue
        g = group.copy()
        g["bucket_side"] = buckets
        # Equal-weight within each bucket
        long_count = int((buckets == 1).sum())
        short_count = int((buckets == -1).sum())
        weights = np.zeros(len(g), dtype=float)
        if long_count:
            weights[buckets == 1] = 1.0 / long_count
        if short_count:
            weights[buckets == -1] = -1.0 / short_count
        g["weight"] = weights
        out_chunks.append(g)

    if dropped_days:
        log.info("form_long_short: dropped %d cross-sections too small for %s cut",
                 dropped_days, bucket)

    if not out_chunks:
        return pd.DataFrame(columns=list(panel.columns) + ["bucket_side", "weight", "announcement_day"])
    return pd.concat(out_chunks, ignore_index=True)


def long_short_summary(events: pd.DataFrame, horizon: int) -> dict:
    """Aggregate per-event long-short payoffs into per-day returns.

    For each announcement_day, the day's long-short return is:
        sum(weight_i * fwd_return_K_i)
    where weights from `form_long_short` already encode equal-weight
    within bucket and sign.

    NaN fwd_returns drop ONLY the firm-event, not the whole day — but if
    a bucket becomes empty after NaN-drop, the day is dropped.

    Returns:
        dict with:
            daily_returns : pd.Series indexed by date — the long-short P&L
            n_days        : int
            n_events      : int — total firm-events used
            mean          : float
            std           : float
            sharpe_252    : float — annualized (sqrt-252 scaling)
    """
    col = f"fwd_return_{horizon}"
    if col not in events.columns:
        raise ValueError(f"events missing column {col}")
    if "bucket_side" not in events.columns:
        raise ValueError("events missing bucket_side — call form_long_short first")

    valid = events.dropna(subset=[col]).copy()
    valid["contrib"] = valid["weight"] * valid[col]

    # Per-day check: both sides must have at least one valid firm
    def _day_has_both_sides(g: pd.DataFrame) -> bool:
        return ((g["bucket_side"] == 1).any() and (g["bucket_side"] == -1).any())

    keep_days = valid.groupby("announcement_day").filter(_day_has_both_sides)
    daily = keep_days.groupby("announcement_day")["contrib"].sum().sort_index()

    if len(daily) == 0:
        return {
            "daily_returns": daily,
            "n_days": 0, "n_events": 0,
            "mean": math.nan, "std": math.nan, "sharpe_252": math.nan,
        }

    mean = float(daily.mean())
    std = float(daily.std(ddof=1)) if len(daily) > 1 else math.nan
    sharpe = (mean / std) * math.sqrt(252) if std and std > 0 and math.isfinite(std) else math.nan
    return {
        "daily_returns": daily,
        "n_days": int(len(daily)),
        "n_events": int(len(keep_days)),
        "mean": mean,
        "std": std,
        "sharpe_252": float(sharpe) if math.isfinite(sharpe) else math.nan,
    }
