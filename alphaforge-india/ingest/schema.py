"""Unified Parquet schema for both eras of NSE bhavcopy data.

See `research/INDIA_DESIGN.md` §2.2. Both `parser_legacy` and `parser_unified`
emit DataFrames matching this schema so downstream consumers (signals,
backtest, validator) don't need to know which era a row came from.
"""
from __future__ import annotations

# Canonical column order. Both parsers MUST return DataFrames with exactly
# these columns in this order.
COLUMNS: tuple[str, ...] = (
    "date",          # pd.Timestamp (date-only)
    "symbol",        # str
    "series",        # str — always "EQ" after ingestion filter
    "open",          # float, INR
    "high",          # float, INR
    "low",           # float, INR
    "close",         # float, INR
    "last",          # float, INR — last traded price
    "prev_close",    # float, INR
    "volume",        # int — shares traded
    "value",         # float, INR — total traded value
    "num_trades",    # Int64 — NaN for legacy era (column not present)
    "deliv_qty",     # int — shares physically delivered
    "deliv_pct",     # float — delivery as % of volume (0..100)
    "source_era",    # str — "legacy+mto" or "unified"
)

LEGACY_ERA = "legacy+mto"
UNIFIED_ERA = "unified"

# Column → dtype mapping for explicit casting after parse.
DTYPES = {
    "symbol": "string",
    "series": "string",
    "open": "float64",
    "high": "float64",
    "low": "float64",
    "close": "float64",
    "last": "float64",
    "prev_close": "float64",
    "volume": "int64",
    "value": "float64",
    "num_trades": "Int64",  # nullable; legacy era has no num_trades
    "deliv_qty": "int64",
    "deliv_pct": "float64",
    "source_era": "string",
}
