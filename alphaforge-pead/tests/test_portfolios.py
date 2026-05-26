"""Tests for the portfolio-formation + IC module.

Synthetic panels only — no real EDGAR or OHLCV data. Per PEAD_DESIGN.md
§8 the gauntlet does not run against real data until certification.

Coverage:
  - IC: positive correlation produces positive rho; sample-size guard
  - Bucket assignment: quintile and decile cuts, min-size enforcement,
    degenerate (all-tied) input
  - Long-short: equal-weighting within bucket, NaN fwd-return handling,
    days with one-sided buckets are dropped, weights sum correctly
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from gauntlet.portfolios import (
    BUCKET_CONFIG,
    _assign_buckets,
    compute_ic,
    form_long_short,
    long_short_summary,
)


# --- IC -------------------------------------------------------------------


def _synthetic_panel(n: int, ic_true: float, horizon: int = 21, seed: int = 0) -> pd.DataFrame:
    """Build a synthetic panel where SUE has *approximately* the specified
    Spearman correlation with fwd_return_{horizon}. Uses a simple
    additive noise construction; with seed control IC is deterministic."""
    rng = np.random.default_rng(seed)
    sue = rng.standard_normal(n)
    noise = rng.standard_normal(n)
    # Convex combination: fwd_return = a * sue + (1-a) * noise
    a = ic_true
    fwd = a * sue + math.sqrt(max(1 - a * a, 0)) * noise
    return pd.DataFrame({
        "cik": np.arange(n),
        "ticker": [f"T{i:04d}" for i in range(n)],
        "fy": 2024,
        "fp": "Q1",
        "announcement_ts": pd.Timestamp("2024-05-01", tz="UTC"),
        "sue": sue,
        f"fwd_return_{horizon}": fwd,
    })


def test_compute_ic_positive_correlation_recovers_positive_rho():
    panel = _synthetic_panel(n=500, ic_true=0.4, seed=1)
    r = compute_ic(panel, horizon=21)
    assert r["ic"] > 0.25
    assert r["n_events"] == 500


def test_compute_ic_negative_correlation_recovers_negative_rho():
    panel = _synthetic_panel(n=500, ic_true=-0.4, seed=2)
    r = compute_ic(panel, horizon=21)
    assert r["ic"] < -0.25


def test_compute_ic_small_sample_returns_nan():
    panel = _synthetic_panel(n=10, ic_true=0.5, seed=3)
    r = compute_ic(panel, horizon=21)
    assert math.isnan(r["ic"])
    assert r["n_events"] == 10


def test_compute_ic_drops_nan_rows():
    panel = _synthetic_panel(n=200, ic_true=0.3, seed=4)
    panel.loc[panel.index[:50], "sue"] = np.nan
    panel.loc[panel.index[50:100], "fwd_return_21"] = np.nan
    r = compute_ic(panel, horizon=21)
    # 50 with sue=NaN + 50 with fwd=NaN — they may overlap but at least
    # 100 unique invalid → ≤100 valid remain
    assert r["n_events"] <= 100


def test_compute_ic_raises_on_missing_horizon_column():
    panel = _synthetic_panel(n=100, ic_true=0.0, seed=5)
    with pytest.raises(ValueError):
        compute_ic(panel, horizon=999)


# --- bucket assignment ---------------------------------------------------


def test_assign_buckets_quintile_basic():
    sue = np.linspace(-1, 1, 10)
    out = _assign_buckets(sue, frac=0.20, min_size=5)
    assert out is not None
    # Bottom 2 → -1, top 2 → +1, middle 6 → 0
    assert int((out == -1).sum()) == 2
    assert int((out == 1).sum()) == 2
    assert int((out == 0).sum()) == 6
    # Bottom = lowest SUE values
    assert out[0] == -1
    assert out[-1] == 1


def test_assign_buckets_decile_basic():
    sue = np.linspace(-1, 1, 20)
    out = _assign_buckets(sue, frac=0.10, min_size=10)
    assert out is not None
    # 10% × 20 = 2 firms on each tail
    assert int((out == -1).sum()) == 2
    assert int((out == 1).sum()) == 2


def test_assign_buckets_below_min_size_returns_none():
    sue = np.array([0.5, -0.3, 0.1, -0.7])
    assert _assign_buckets(sue, frac=0.20, min_size=5) is None
    assert _assign_buckets(sue, frac=0.10, min_size=10) is None


def test_assign_buckets_all_identical_returns_none():
    sue = np.zeros(10)
    assert _assign_buckets(sue, frac=0.20, min_size=5) is None


def test_bucket_config_pre_committed_values():
    """Sanity guard against accidental tuning of the cut thresholds."""
    assert BUCKET_CONFIG["quintile"] == {"frac": 0.20, "min_size": 5}
    assert BUCKET_CONFIG["decile"] == {"frac": 0.10, "min_size": 10}


# --- form_long_short -----------------------------------------------------


def _multiday_panel(n_per_day: int, n_days: int, ic_true: float, seed: int = 0) -> pd.DataFrame:
    """Build a panel where each calendar day has n_per_day firms
    announcing simultaneously."""
    frames = []
    for d in range(n_days):
        df = _synthetic_panel(n=n_per_day, ic_true=ic_true, seed=seed + d)
        df["announcement_ts"] = pd.Timestamp("2024-01-01", tz="UTC") + pd.Timedelta(days=d)
        df["cik"] = df["cik"] + d * 10000
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def test_form_long_short_assigns_buckets_per_day():
    panel = _multiday_panel(n_per_day=20, n_days=5, ic_true=0.3, seed=10)
    events = form_long_short(panel, horizon=21, bucket="quintile")
    assert "bucket_side" in events.columns
    assert "weight" in events.columns
    # Each day should have 4 longs + 4 shorts (20 * 0.20 = 4)
    for day, group in events.groupby("announcement_day"):
        assert int((group["bucket_side"] == 1).sum()) == 4
        assert int((group["bucket_side"] == -1).sum()) == 4


def test_form_long_short_weights_within_bucket_are_equal():
    panel = _multiday_panel(n_per_day=20, n_days=3, ic_true=0.0, seed=20)
    events = form_long_short(panel, horizon=21, bucket="quintile")
    for day, group in events.groupby("announcement_day"):
        long_weights = group.loc[group["bucket_side"] == 1, "weight"].unique()
        short_weights = group.loc[group["bucket_side"] == -1, "weight"].unique()
        assert len(long_weights) == 1  # all equal
        assert len(short_weights) == 1
        # Positive weight for long, negative for short
        assert long_weights[0] > 0
        assert short_weights[0] < 0
        # Sum of long weights = +1; sum of short weights = -1
        assert math.isclose(group.loc[group["bucket_side"] == 1, "weight"].sum(), 1.0, abs_tol=1e-9)
        assert math.isclose(group.loc[group["bucket_side"] == -1, "weight"].sum(), -1.0, abs_tol=1e-9)


def test_form_long_short_drops_small_days():
    """A day with 4 firms (below quintile min_size=5) should be dropped."""
    big_day = _synthetic_panel(n=10, ic_true=0.0, seed=30)
    big_day["announcement_ts"] = pd.Timestamp("2024-01-01", tz="UTC")
    small_day = _synthetic_panel(n=4, ic_true=0.0, seed=31)
    small_day["announcement_ts"] = pd.Timestamp("2024-01-02", tz="UTC")
    small_day["cik"] = small_day["cik"] + 100
    panel = pd.concat([big_day, small_day], ignore_index=True)

    events = form_long_short(panel, horizon=21, bucket="quintile")
    days = set(events["announcement_day"])
    assert len(days) == 1  # only the 10-firm day survived


def test_form_long_short_drops_sue_nan_rows():
    panel = _multiday_panel(n_per_day=20, n_days=2, ic_true=0.0, seed=40)
    # Inject NaN SUEs into one day
    mask = pd.to_datetime(panel["announcement_ts"]).dt.date == pd.Timestamp("2024-01-01").date()
    panel.loc[mask, "sue"] = np.nan
    events = form_long_short(panel, horizon=21, bucket="quintile")
    # That day drops entirely (now n=0 valid SUEs, below min_size)
    days = set(events["announcement_day"])
    assert pd.Timestamp("2024-01-01").date() not in days


# --- long_short_summary --------------------------------------------------


def test_long_short_summary_aggregates_to_daily_returns():
    panel = _multiday_panel(n_per_day=20, n_days=10, ic_true=0.4, seed=50)
    events = form_long_short(panel, horizon=21, bucket="quintile")
    summary = long_short_summary(events, horizon=21)
    assert summary["n_days"] == 10
    assert summary["n_events"] == 200
    # With ic_true=0.4 and 10 days, mean should be clearly positive
    # (the synthetic construction gives top-quintile firms higher fwd_returns)
    assert summary["mean"] > 0
    # Sharpe should be defined
    assert math.isfinite(summary["sharpe_252"])


def test_long_short_summary_drops_days_with_one_sided_buckets():
    """If all firms in the long bucket have NaN fwd_return, that day's
    long side is empty and the day must be dropped."""
    panel = _multiday_panel(n_per_day=20, n_days=3, ic_true=0.0, seed=60)
    events = form_long_short(panel, horizon=21, bucket="quintile")
    # NaN out the long-side fwd_returns on day 0
    day0 = events["announcement_day"].unique()[0]
    long_mask = (events["announcement_day"] == day0) & (events["bucket_side"] == 1)
    events.loc[long_mask, "fwd_return_21"] = np.nan

    summary = long_short_summary(events, horizon=21)
    # day 0 should be dropped because the long side has no valid firms
    assert summary["n_days"] == 2
    assert day0 not in summary["daily_returns"].index


def test_long_short_summary_empty_input():
    empty = pd.DataFrame(columns=["sue", "fwd_return_21", "bucket_side", "weight", "announcement_day"])
    summary = long_short_summary(empty, horizon=21)
    assert summary["n_days"] == 0
    assert math.isnan(summary["mean"])
