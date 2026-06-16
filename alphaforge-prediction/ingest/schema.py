"""Parquet schema for resolved Kalshi binary contracts.

See `research/PREDICTION_MARKETS_DESIGN.md` §2 (store) and §4 (entry price).

ONE ROW PER RESOLVED CONTRACT. The row carries the contract identity, the
event-level category/series, the lifecycle timestamps, the resolution
(`result` + `settlement_value`), and the pre-committed **entry-price
snapshot** reconstructed from candlesticks at the §4-frozen lead of one hour
before `close_time` (fallback: last available pre-close trade).

Convention notes (matching `alphaforge-india/ingest/schema.py`):
  - Canonical, ordered column tuple; the parser MUST emit exactly these.
  - Explicit dtype map applied after parse.
  - Timestamps stored as **ns ints** (UTC epoch nanoseconds) — pandas-native
    `datetime64[ns]`-compatible and look-ahead-checkable as plain ints. The ISO
    strings from the API are parsed once at ingest into these ns ints.

All numeric ingest goes through `_to_float` / `_to_int_ns` defensive coercers
because every Kalshi `*_dollars` / `*_fp` field is a JSON **string** and the
timestamps are ISO strings (see SPIKE_NOTES.md).
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Canonical column order. The parser MUST return rows/DataFrames with exactly
# these keys/columns in this order.
# ---------------------------------------------------------------------------
COLUMNS: tuple[str, ...] = (
    "ticker",            # str  — market ticker (unique resolved-contract id)
    "event_ticker",      # str  — parent event ticker
    "series_ticker",     # str  — series ticker (from the event; candlesticks path key)
    "category",          # str  — event category (§4 grouping key); "" if unknown
    "market_type",       # str  — e.g. "binary"
    "open_time",         # int64 ns — market open (UTC epoch ns)
    "close_time",        # int64 ns — market close (UTC epoch ns)
    "settlement_ts",     # int64 ns — settlement timestamp (UTC epoch ns); -1 if absent
    "result",            # str  — "yes" | "no"
    "settlement_value",  # float — 1.0 if YES resolved, 0.0 if NO (dollars)
    "entry_price",       # float — §4 last trade at close-1h (fallback last pre-close trade)
    "implied_prob",      # float — == entry_price (dollars 0..1)
    "entry_snapshot_ts", # int64 ns — end_period_ts of the candle entry_price came from
    "yes_bid",           # float — yes_bid_dollars at the entry candle
    "yes_ask",           # float — yes_ask_dollars at the entry candle
    "volume_fp",         # float — market lifetime volume (contracts)
)

# Column -> pandas dtype for explicit casting after row assembly.
DTYPES: dict[str, str] = {
    "ticker": "string",
    "event_ticker": "string",
    "series_ticker": "string",
    "category": "string",
    "market_type": "string",
    "open_time": "int64",
    "close_time": "int64",
    "settlement_ts": "int64",
    "result": "string",
    "settlement_value": "float64",
    "entry_price": "float64",
    "implied_prob": "float64",
    "entry_snapshot_ts": "int64",
    "yes_bid": "float64",
    "yes_ask": "float64",
    "volume_fp": "float64",
}

# Sentinel for "no timestamp" in an int64 column (NaN is not representable in int64).
NS_MISSING: int = -1

# Resolved-status strings (per SPIKE_NOTES.md (a)). Either is terminal.
RESOLVED_STATUSES: frozenset[str] = frozenset({"finalized", "settled"})
VALID_RESULTS: frozenset[str] = frozenset({"yes", "no"})


# ---------------------------------------------------------------------------
# Defensive coercers — every Kalshi numeric / ts field arrives as a string.
# ---------------------------------------------------------------------------

def to_float(x: Any, default: float = float("nan")) -> float:
    """Coerce a Kalshi *_dollars / *_fp string (or number) to float.

    Returns `default` on None / "" / unparseable / non-finite input.
    """
    if x is None:
        return default
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(v):
        return default
    return v


def iso_to_ns(s: Any) -> int:
    """Parse a Kalshi ISO-8601 UTC timestamp string to epoch nanoseconds.

    Accepts trailing 'Z'. Returns `NS_MISSING` on None / "" / unparseable.
    Fractional seconds (e.g. settlement_ts) are preserved to ns precision.
    """
    if s is None or s == "":
        return NS_MISSING
    if isinstance(s, (int, float)):
        # Already an epoch — assume seconds if it looks like one, else ns.
        v = float(s)
        if not math.isfinite(v):
            return NS_MISSING
        return int(v * 1_000_000_000) if v < 1e12 else int(v)
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return NS_MISSING
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    # epoch seconds (float, sub-second preserved) -> ns int
    return int(round(dt.timestamp() * 1_000_000_000))


def ns_to_iso(ns: int) -> str:
    """Inverse of `iso_to_ns` for reporting. Returns "" for NS_MISSING."""
    if ns is None or ns == NS_MISSING:
        return ""
    dt = datetime.fromtimestamp(ns / 1_000_000_000, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def empty_frame():
    """An empty DataFrame with the canonical columns + dtypes.

    Imported lazily so the schema module has no hard pandas dependency at
    import time (mirrors india's lean schema module).
    """
    import pandas as pd

    df = pd.DataFrame({c: pd.Series(dtype=DTYPES[c]) for c in COLUMNS})
    return df[list(COLUMNS)]
