"""Unit tests for ingest.schema — coercers, ns timestamps, parquet round-trip."""
from __future__ import annotations

import math

import pytest

from ingest import schema as S


# ---------------------------------------------------------------------------
# Defensive coercers (every Kalshi numeric arrives as a string)
# ---------------------------------------------------------------------------

def test_to_float_parses_string_numerics():
    assert S.to_float("0.8670") == pytest.approx(0.867)
    assert S.to_float("47398.43") == pytest.approx(47398.43)
    assert S.to_float(0.5) == 0.5


def test_to_float_defaults_on_garbage():
    assert math.isnan(S.to_float(None))
    assert math.isnan(S.to_float(""))
    assert math.isnan(S.to_float("not-a-number"))
    assert S.to_float(None, default=0.0) == 0.0
    assert math.isnan(S.to_float("inf"))   # non-finite -> default(nan)


# ---------------------------------------------------------------------------
# ISO <-> ns
# ---------------------------------------------------------------------------

def test_iso_to_ns_round_trip():
    iso = "2026-06-16T07:15:00Z"
    ns = S.iso_to_ns(iso)
    assert ns > 0
    # round-trips back to the same instant (second precision).
    assert S.ns_to_iso(ns).startswith("2026-06-16T07:15:00")


def test_iso_to_ns_preserves_subsecond():
    ns = S.iso_to_ns("2026-06-16T08:05:13.379965Z")
    # 379_965 microseconds → ns component present.
    assert ns % 1_000_000_000 != 0


def test_iso_to_ns_missing_sentinel():
    assert S.iso_to_ns(None) == S.NS_MISSING
    assert S.iso_to_ns("") == S.NS_MISSING
    assert S.iso_to_ns("garbage") == S.NS_MISSING
    assert S.ns_to_iso(S.NS_MISSING) == ""


def test_iso_to_ns_epoch_seconds_input():
    # An epoch-seconds number coerces to ns.
    ns = S.iso_to_ns(1781591760)
    assert ns == 1781591760 * 1_000_000_000


# ---------------------------------------------------------------------------
# Parquet round-trip with canonical schema
# ---------------------------------------------------------------------------

def test_empty_frame_has_canonical_columns():
    df = S.empty_frame()
    assert list(df.columns) == list(S.COLUMNS)
    assert len(df) == 0


def test_parquet_round_trip(tmp_path):
    import pandas as pd

    row = {
        "ticker": "MKT-1", "event_ticker": "EVT-1", "series_ticker": "SER-1",
        "category": "Crypto", "market_type": "binary",
        "open_time": S.iso_to_ns("2026-06-16T06:00:00Z"),
        "close_time": S.iso_to_ns("2026-06-16T08:00:00Z"),
        "settlement_ts": S.iso_to_ns("2026-06-16T08:05:00Z"),
        "result": "yes", "settlement_value": 1.0,
        "entry_price": 0.87, "implied_prob": 0.87,
        "entry_snapshot_ts": S.iso_to_ns("2026-06-16T07:00:00Z"),
        "yes_bid": 0.85, "yes_ask": 0.88, "volume_fp": 47398.43,
    }
    df = pd.DataFrame([row])[list(S.COLUMNS)].astype(S.DTYPES)
    p = tmp_path / "part-00000.parquet"
    df.to_parquet(p, index=False)
    back = pd.read_parquet(p)
    assert list(back.columns) == list(S.COLUMNS)
    assert back.loc[0, "ticker"] == "MKT-1"
    assert float(back.loc[0, "entry_price"]) == pytest.approx(0.87)
    assert int(back.loc[0, "close_time"]) == row["close_time"]
    assert int(back.loc[0, "entry_snapshot_ts"]) < int(back.loc[0, "close_time"])


def test_resolved_statuses_and_results():
    assert "finalized" in S.RESOLVED_STATUSES
    assert "settled" in S.RESOLVED_STATUSES
    assert S.VALID_RESULTS == frozenset({"yes", "no"})
