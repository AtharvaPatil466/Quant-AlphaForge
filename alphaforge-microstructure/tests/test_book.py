"""Tests for the L2 order book reconstruction.

These exercise the load-bearing invariants:
    - seed_from_snapshot sets up bid/ask sides correctly
    - apply_diff with size=0 removes a level
    - apply_diff with size>0 inserts/updates a level
    - pu-continuity enforcement raises BookResyncRequired on gaps
    - is_first_diff_after_snapshot brackets correctly
    - top_n returns levels in the correct order
"""

from __future__ import annotations

import pytest

from collector.book import OrderBook, BookSnapshot, BookResyncRequired


def _seed_basic(b: OrderBook, last_update_id: int = 100) -> None:
    b.seed_from_snapshot(
        bids=[(99.0, 1.0), (98.0, 2.0), (97.0, 3.0)],
        asks=[(101.0, 1.5), (102.0, 2.5), (103.0, 3.5)],
        last_update_id=last_update_id,
    )


# --- seed -------------------------------------------------------------------


def test_seed_orders_bids_descending_asks_ascending():
    b = OrderBook()
    _seed_basic(b)
    bids, asks = b.top_n(3)
    assert [px for px, _ in bids] == [99.0, 98.0, 97.0]
    assert [px for px, _ in asks] == [101.0, 102.0, 103.0]


def test_seed_drops_zero_size_levels():
    b = OrderBook()
    b.seed_from_snapshot(
        bids=[(99.0, 1.0), (98.0, 0.0), (97.0, 3.0)],
        asks=[(101.0, 0.0), (102.0, 2.5)],
        last_update_id=10,
    )
    bids, asks = b.top_n(5)
    assert bids == [(99.0, 1.0), (97.0, 3.0)]
    assert asks == [(102.0, 2.5)]


def test_seed_marks_seeded():
    b = OrderBook()
    assert not b.is_seeded
    _seed_basic(b)
    assert b.is_seeded


# --- first-diff-after-snapshot bracket --------------------------------------


def test_first_diff_after_snapshot_bracketing():
    b = OrderBook()
    _seed_basic(b, last_update_id=100)
    # last_update_id + 1 == 101 must be in [U, u]
    assert b.is_first_diff_after_snapshot(U=99, u=105)
    assert b.is_first_diff_after_snapshot(U=101, u=101)
    assert not b.is_first_diff_after_snapshot(U=102, u=110)
    assert not b.is_first_diff_after_snapshot(U=50, u=80)


# --- apply_diff -------------------------------------------------------------


def test_apply_diff_updates_existing_level():
    b = OrderBook()
    _seed_basic(b, last_update_id=100)
    b.apply_diff(U=101, u=102, pu=100, bids=[(99.0, 5.0)], asks=[])
    bids, _ = b.top_n(3)
    assert bids[0] == (99.0, 5.0)
    assert b.last_update_id == 102


def test_apply_diff_removes_level_on_zero_size():
    b = OrderBook()
    _seed_basic(b, last_update_id=100)
    b.apply_diff(U=101, u=102, pu=100, bids=[(98.0, 0.0)], asks=[])
    bids, _ = b.top_n(5)
    assert (98.0, 2.0) not in bids
    assert bids == [(99.0, 1.0), (97.0, 3.0)]


def test_apply_diff_inserts_new_level():
    b = OrderBook()
    _seed_basic(b, last_update_id=100)
    # 99.5 inside the bid book becomes new best bid; 100.5 inside the ask
    # book becomes new best ask.
    b.apply_diff(U=101, u=102, pu=100, bids=[(99.5, 0.5)], asks=[(100.5, 0.7)])
    bids, asks = b.top_n(5)
    assert bids[0] == (99.5, 0.5)
    assert asks[0] == (100.5, 0.7)


def test_apply_diff_chain_continuity_passes():
    b = OrderBook()
    _seed_basic(b, last_update_id=100)
    b.apply_diff(U=101, u=110, pu=100, bids=[], asks=[])
    b.apply_diff(U=111, u=115, pu=110, bids=[], asks=[])
    b.apply_diff(U=116, u=120, pu=115, bids=[], asks=[])
    assert b.last_update_id == 120


def test_apply_diff_raises_on_pu_mismatch():
    b = OrderBook()
    _seed_basic(b, last_update_id=100)
    b.apply_diff(U=101, u=110, pu=100, bids=[], asks=[])
    with pytest.raises(BookResyncRequired):
        # pu should be 110, not 109
        b.apply_diff(U=111, u=115, pu=109, bids=[], asks=[])


def test_apply_diff_before_seed_raises():
    b = OrderBook()
    with pytest.raises(BookResyncRequired):
        b.apply_diff(U=1, u=2, pu=0, bids=[], asks=[])


# --- top_n / snapshot -------------------------------------------------------


def test_top_n_limits_levels():
    b = OrderBook()
    bids = [(100.0 - i, 1.0) for i in range(50)]
    asks = [(101.0 + i, 1.0) for i in range(50)]
    b.seed_from_snapshot(bids=bids, asks=asks, last_update_id=1)
    bb, aa = b.top_n(5)
    assert len(bb) == 5
    assert len(aa) == 5
    assert bb[0][0] == 100.0
    assert aa[0][0] == 101.0


def test_snapshot_carries_timestamps_and_derived_fields():
    b = OrderBook()
    _seed_basic(b, last_update_id=42)
    snap = b.snapshot(exchange_ts_ns=1_000_000, local_ts_ns=2_000_000, n=3)
    assert isinstance(snap, BookSnapshot)
    assert snap.exchange_ts_ns == 1_000_000
    assert snap.local_ts_ns == 2_000_000
    assert snap.last_update_id == 42
    assert snap.best_bid == 99.0
    assert snap.best_ask == 101.0
    assert snap.mid == 100.0
    assert snap.spread == 2.0


def test_snapshot_empty_book_is_safe():
    b = OrderBook()
    b.seed_from_snapshot(bids=[], asks=[], last_update_id=0)
    snap = b.snapshot(exchange_ts_ns=0, local_ts_ns=0, n=5)
    assert snap.best_bid is None
    assert snap.best_ask is None
    assert snap.mid is None
    assert snap.spread is None
