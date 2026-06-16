"""Unit tests for signals.flb — trial enumeration + IS/OOS split (substrate #10).

Guards the FROZEN pre-committed trial set (`PREDICTION_MARKETS_DESIGN.md` §4):
an accidental change to the bucket × category grid would silently corrupt the
multiple-testing deflation denominator, so the enumeration count is pinned.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ingest import schema as S
from signals import flb


# ---------------------------------------------------------------------------
# Synthetic resolved-contract panel builder (canonical schema).
# ---------------------------------------------------------------------------

def make_panel(prices, results, *, category="Crypto",
               close_start_ns=1_000_000_000_000_000_000,
               close_step_ns=60_000_000_000) -> pd.DataFrame:
    """Build a canonical resolved-contract frame from price/result lists.

    ``close_time`` increments by ``close_step_ns`` per row so the calendar split
    has spread. ``entry_snapshot_ts`` is one step before ``close_time``.
    ``category`` may be a scalar (broadcast) or a per-row list.
    """
    n = len(prices)
    cats = [category] * n if isinstance(category, str) else list(category)
    rows = []
    for i in range(n):
        ct = close_start_ns + i * close_step_ns
        res = results[i]
        rows.append({
            "ticker": f"T{i}", "event_ticker": f"E{i}", "series_ticker": "S",
            "category": cats[i], "market_type": "binary",
            "open_time": ct - 10 * close_step_ns, "close_time": ct,
            "settlement_ts": ct + close_step_ns,
            "result": res, "settlement_value": 1.0 if res == "yes" else 0.0,
            "entry_price": float(prices[i]), "implied_prob": float(prices[i]),
            "entry_snapshot_ts": ct - close_step_ns,
            "yes_bid": max(prices[i] - 0.01, 0.0),
            "yes_ask": min(prices[i] + 0.01, 1.0),
            "volume_fp": 100.0,
        })
    return pd.DataFrame(rows)[list(S.COLUMNS)].astype(S.DTYPES)


# ---------------------------------------------------------------------------
# Bucket / direction constants.
# ---------------------------------------------------------------------------

def test_bucket_edges_match_design():
    assert flb.BUCKET_EDGES == (0.0, 0.05, 0.15, 0.35, 0.65, 0.85, 0.95, 1.0)
    assert len(flb.BUCKET_LABELS) == len(flb.BUCKET_EDGES) - 1


def test_extreme_buckets_directions():
    extremes = flb._extreme_buckets()
    labels = {lab: d for _, lab, _, _, d in extremes}
    # Longshots ≤15c → negative; favorites ≥85c → positive; interior absent.
    assert labels["(0,5]"] == flb.Direction.LONGSHOT.value
    assert labels["(5,15]"] == flb.Direction.LONGSHOT.value
    assert labels["(85,95]"] == flb.Direction.FAVORITE.value
    assert labels["(95,100)"] == flb.Direction.FAVORITE.value
    assert "(15,35]" not in labels and "(35,65]" not in labels


# ---------------------------------------------------------------------------
# Category mapping.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("Crypto", flb.CAT_CRYPTO),
    ("Bitcoin price", flb.CAT_CRYPTO),
    ("Sports", flb.CAT_SPORTS),
    ("Economics", flb.CAT_ECONOMICS),
    ("Financials", flb.CAT_ECONOMICS),
    ("Weather", flb.CAT_WEATHER),
    ("Politics", flb.CAT_POLITICS_OTHER),
    ("Exotics", flb.CAT_EXOTICS),
    ("", flb.CAT_POLITICS_OTHER),
    (None, flb.CAT_POLITICS_OTHER),
    ("something unknown", flb.CAT_POLITICS_OTHER),
])
def test_map_category(raw, expected):
    assert flb.map_category(raw) == expected


def test_exotics_is_mve():
    assert flb.CAT_EXOTICS in flb.MVE_GROUPS
    assert flb.CAT_CRYPTO not in flb.MVE_GROUPS


# ---------------------------------------------------------------------------
# Trial enumeration — the pinned counts (frozen trial set).
# ---------------------------------------------------------------------------

def test_enumerate_single_non_mve_category():
    # One non-MVE category → pooled (4) + per-category (4) = 8 extreme cells.
    df = make_panel([0.02, 0.10, 0.90, 0.97], ["no"] * 4, category="Crypto")
    cells = flb.enumerate_trials(df)
    assert len(cells) == 8
    scopes = {c.scope for c in cells}
    assert scopes == {"pooled", "per-category"}
    # No cell is MVE.
    assert not any(c.is_mve for c in cells)


def test_enumerate_only_mve_no_pooled():
    # All-MVE data → NO pooled cells (§16 never pools MVE) + 4 per-category.
    df = make_panel([0.02, 0.10, 0.90, 0.97], ["no"] * 4, category="Exotics")
    cells = flb.enumerate_trials(df)
    assert len(cells) == 4
    assert all(c.scope == "per-category" and c.is_mve for c in cells)


def test_enumerate_two_non_mve_categories():
    # 2 non-MVE categories → pooled (4) + per-category (4 × 2) = 12.
    df = make_panel([0.02, 0.10, 0.90, 0.97] * 2,
                    ["no"] * 8,
                    category=["Crypto"] * 4 + ["Sports"] * 4)
    cells = flb.enumerate_trials(df)
    assert len(cells) == 12
    cats = {c.category for c in cells if c.scope == "per-category"}
    assert cats == {flb.CAT_CRYPTO, flb.CAT_SPORTS}


def test_enumerate_mixed_mve_and_non_mve():
    # 1 non-MVE (Crypto) + 1 MVE (Exotics):
    #   pooled non-MVE (4) + per-cat Crypto (4) + per-cat Exotics (4) = 12.
    df = make_panel([0.02, 0.10, 0.90, 0.97] * 2,
                    ["no"] * 8,
                    category=["Crypto"] * 4 + ["Exotics"] * 4)
    cells = flb.enumerate_trials(df)
    assert len(cells) == 12
    # Pooled cells must exclude MVE: pooled count is 4 (extreme buckets).
    pooled = [c for c in cells if c.scope == "pooled"]
    assert len(pooled) == 4 and all(not c.is_mve for c in pooled)


def test_n_trials_matches_enumerate():
    df = make_panel([0.02, 0.10, 0.90, 0.97], ["no"] * 4, category="Crypto")
    assert flb.n_trials(df) == len(flb.enumerate_trials(df))


def test_enumeration_order_stable():
    df = make_panel([0.02, 0.10, 0.90, 0.97], ["no"] * 4, category="Crypto")
    ids_a = [c.cell_id for c in flb.enumerate_trials(df)]
    ids_b = [c.cell_id for c in flb.enumerate_trials(df)]
    assert ids_a == ids_b
    # Pooled cells come first.
    assert ids_a[0].startswith("pooled:")


def test_enumerate_empty_frame():
    assert flb.enumerate_trials(S.empty_frame()) == []
    assert flb.n_trials(S.empty_frame()) == 0


# ---------------------------------------------------------------------------
# IS / OOS calendar-midpoint split.
# ---------------------------------------------------------------------------

def test_calendar_midpoint_split_basic():
    df = make_panel([0.5] * 10, ["yes"] * 10)
    split = flb.calendar_midpoint_split(df)
    assert split.n_is + split.n_oos == 10
    # Midpoint is the calendar midpoint of close_time min/max.
    close = df["close_time"].astype("int64").to_numpy()
    assert split.midpoint_ns == (int(close.min()) + int(close.max())) // 2


def test_calendar_split_assigns_by_close_time():
    df = make_panel([0.5] * 4, ["yes"] * 4)
    split = flb.calendar_midpoint_split(df)
    close = df["close_time"].astype("int64").to_numpy()
    for i in range(4):
        if close[i] < split.midpoint_ns:
            assert split.is_mask[i]
        else:
            assert split.oos_mask[i]


def test_calendar_split_empty():
    split = flb.calendar_midpoint_split(S.empty_frame())
    assert split.n_is == 0 and split.n_oos == 0


# ---------------------------------------------------------------------------
# select_frame / region / predicted_outcomes.
# ---------------------------------------------------------------------------

def test_select_frame_pooled_excludes_mve():
    df = make_panel([0.02, 0.02], ["no", "no"], category=["Crypto", "Exotics"])
    pooled_cell = next(c for c in flb.enumerate_trials(df) if c.scope == "pooled")
    sub = flb.select_frame(df, pooled_cell)
    cats = set(sub["category"].astype(str))
    assert "Exotics" not in cats and "Crypto" in cats


def test_select_frame_per_category():
    df = make_panel([0.02, 0.02], ["no", "no"], category=["Crypto", "Sports"])
    crypto_cell = next(c for c in flb.enumerate_trials(df)
                       if c.scope == "per-category" and c.category == flb.CAT_CRYPTO)
    sub = flb.select_frame(df, crypto_cell)
    assert set(sub["category"].astype(str)) == {"Crypto"}


def test_region_for_first_bucket_includes_zero():
    df = make_panel([0.0], ["no"], category="Crypto")
    cell = next(c for c in flb.enumerate_trials(df)
                if c.bucket_index == 0 and c.scope == "per-category")
    lo, hi = flb.region_for_cell(cell)
    assert lo < 0.0 <= hi  # 0c price is includable


def test_predicted_outcomes():
    df = make_panel([0.1, 0.9], ["no", "yes"], category="Crypto")
    p, y = flb.predicted_outcomes(df)
    assert list(p) == [0.1, 0.9]
    assert list(y) == [0.0, 1.0]
