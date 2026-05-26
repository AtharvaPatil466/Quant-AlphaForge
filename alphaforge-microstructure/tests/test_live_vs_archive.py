"""Tests for validation.live_vs_archive."""

from __future__ import annotations

import pyarrow as pa

from collector.storage import _trade_schema
from validation.live_vs_archive import compare_trades


def _trades(rows: list[dict]) -> pa.Table:
    return pa.Table.from_pylist(rows, schema=_trade_schema())


def _row(agg_id: int, price: float = 100.0, size: float = 1.0,
         is_buyer_maker: bool = False, exchange_ts_ns: int = 1_000_000_000) -> dict:
    return {
        "exchange_ts_ns": exchange_ts_ns,
        "local_ts_ns": exchange_ts_ns,
        "agg_trade_id": agg_id,
        "price": price,
        "size": size,
        "is_buyer_maker": is_buyer_maker,
    }


def test_identical_tables_pass():
    rows = [_row(i, price=100 + i, size=0.1) for i in range(5)]
    a = _trades(rows)
    b = _trades(rows)
    r = compare_trades(a, b)
    assert r["passed"] is True
    assert r["common_ids"] == 5
    assert r["mismatches"] == []


def test_disjoint_id_sets_fail():
    a = _trades([_row(i) for i in range(5)])
    b = _trades([_row(i) for i in range(100, 105)])
    r = compare_trades(a, b)
    assert r["passed"] is False
    assert r["reason"] == "no overlap on agg_trade_id"
    assert r["common_ids"] == 0


def test_price_mismatch_flagged():
    a = _trades([_row(1, price=100.0), _row(2, price=101.0)])
    b = _trades([_row(1, price=100.0), _row(2, price=999.0)])
    r = compare_trades(a, b)
    assert r["passed"] is False
    cols = [m["column"] for m in r["mismatches"]]
    assert "price" in cols
    pm = next(m for m in r["mismatches"] if m["column"] == "price")
    assert pm["n_mismatched"] == 1
    assert pm["samples"][0]["agg_trade_id"] == 2


def test_only_in_live_counted():
    a = _trades([_row(1), _row(2), _row(3)])
    b = _trades([_row(1), _row(2)])
    r = compare_trades(a, b)
    assert r["only_in_live"] == 1
    assert r["only_in_archive"] == 0
    assert r["common_ids"] == 2
    # Common ids match → no per-column mismatches even though sets differ
    assert r["passed"] is True


def test_is_buyer_maker_mismatch_flagged():
    a = _trades([_row(1, is_buyer_maker=True)])
    b = _trades([_row(1, is_buyer_maker=False)])
    r = compare_trades(a, b)
    assert r["passed"] is False
    cols = [m["column"] for m in r["mismatches"]]
    assert "is_buyer_maker" in cols
