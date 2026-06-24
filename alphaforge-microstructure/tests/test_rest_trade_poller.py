"""Tests for the REST aggTrades poller (collector/rest_trade_poller.py).

Context (2026-06-24): the `btcusdt@aggTrade` WebSocket stream is region-gated
for this host, so the live collector produced zero trades while book snapshots
flowed fine. The decision (see research/PHASE0_RECOVERY.md + COLLECTOR_NOTES.md)
is to source the trade tape from REST `fapi/v1/aggTrades`, paging forward by
trade id. Latency is irrelevant for accumulation because each record carries the
exchange's own `T` timestamp.

These tests pin the poller's contract WITHOUT touching the network:

  - field mapping   REST record -> TradeEvent (exchange `T` is the timestamp)
  - fromId paging   first poll has no fromId; subsequent polls use last_seen+1
  - dedup           agg_trade_id already emitted is never re-emitted
  - rate budgeting  weight over the soft cap throttles; a full page drains fast
"""

from __future__ import annotations

import asyncio

from collector.binance_ws import TradeEvent
from collector.rest_trade_poller import (
    DEFAULT_WEIGHT_SOFT_CAP,
    RestTradePoller,
    _trade_from_rest_record,
)


# --- fixtures ---------------------------------------------------------------


def _rec(agg_id: int, *, ts_ms: int = 1_700_000_000_000,
         price: str = "57000.10", qty: str = "0.001",
         is_buyer_maker: bool = True) -> dict:
    """One Binance USDT-M REST aggTrades record (same keys as @aggTrade WS)."""
    return {
        "a": agg_id,
        "p": price,
        "q": qty,
        "f": agg_id * 10,
        "l": agg_id * 10 + 1,
        "T": ts_ms,
        "m": is_buyer_maker,
    }


# --- field mapping ----------------------------------------------------------


def test_record_maps_to_trade_event_using_exchange_timestamp():
    t = _trade_from_rest_record(_rec(5, ts_ms=1_700_000_000_123,
                                     price="57000.10", qty="0.001",
                                     is_buyer_maker=True),
                                local_ts_ns=999)
    assert isinstance(t, TradeEvent)
    assert t.agg_trade_id == 5
    assert t.exchange_ts_ns == 1_700_000_000_123 * 1_000_000  # ms -> ns
    assert t.local_ts_ns == 999
    assert t.price == 57000.10
    assert t.size == 0.001
    assert t.is_buyer_maker is True


# --- fromId paging ----------------------------------------------------------


def test_first_poll_has_no_fromid():
    p = RestTradePoller(symbol="BTCUSDT", limit=1000)
    params = p.next_params()
    assert params["symbol"] == "BTCUSDT"
    assert params["limit"] == 1000
    assert "fromId" not in params


def test_subsequent_poll_pages_by_fromid():
    p = RestTradePoller(symbol="BTCUSDT", limit=1000)
    p.ingest([_rec(10), _rec(11), _rec(12)], local_ts_ns=1)
    params = p.next_params()
    assert params["fromId"] == 13  # last_seen (12) + 1


# --- dedup ------------------------------------------------------------------


def test_ingest_drops_already_seen_ids():
    p = RestTradePoller()
    first = p.ingest([_rec(1), _rec(2), _rec(3)], local_ts_ns=1)
    assert [t.agg_trade_id for t in first] == [1, 2, 3]

    # An overlapping page (network resent 2,3) emits only the genuinely new ones.
    second = p.ingest([_rec(2), _rec(3), _rec(4), _rec(5)], local_ts_ns=2)
    assert [t.agg_trade_id for t in second] == [4, 5]
    assert p.last_seen_id == 5


def test_ingest_empty_keeps_last_seen():
    p = RestTradePoller()
    p.ingest([_rec(7), _rec(8)], local_ts_ns=1)
    out = p.ingest([], local_ts_ns=2)
    assert out == []
    assert p.last_seen_id == 8


def test_ingest_advances_last_seen_to_max_new_id():
    p = RestTradePoller()
    out = p.ingest([_rec(100), _rec(101), _rec(102)], local_ts_ns=1)
    assert len(out) == 3
    assert p.last_seen_id == 102


# --- rate-limit budgeting ---------------------------------------------------


def test_throttles_when_used_weight_exceeds_soft_cap():
    p = RestTradePoller(poll_interval_s=1.0, weight_soft_cap=DEFAULT_WEIGHT_SOFT_CAP)
    p.record_weight(DEFAULT_WEIGHT_SOFT_CAP + 50)
    assert p.should_throttle() is True
    # A throttle sleep is strictly longer than a normal poll interval.
    assert p.next_sleep_s(full_page=False) > 1.0


def test_full_page_drains_with_zero_sleep_when_not_throttled():
    p = RestTradePoller(poll_interval_s=1.0)
    p.record_weight(100)
    assert p.should_throttle() is False
    assert p.next_sleep_s(full_page=True) == 0.0


def test_partial_page_sleeps_one_poll_interval():
    p = RestTradePoller(poll_interval_s=0.75)
    p.record_weight(100)
    assert p.next_sleep_s(full_page=False) == 0.75


def test_throttle_overrides_full_page_drain():
    p = RestTradePoller(poll_interval_s=1.0, weight_soft_cap=DEFAULT_WEIGHT_SOFT_CAP)
    p.record_weight(DEFAULT_WEIGHT_SOFT_CAP + 1)
    # Even with a full page (backlog), the weight budget wins.
    assert p.next_sleep_s(full_page=True) > 1.0


# --- async surface (driven via asyncio.run, no plugin needed) ---------------


def test_poll_once_uses_injected_fetcher_and_records_weight():
    seen_params: list[dict] = []

    async def fake_fetch(session, params):
        seen_params.append(params)
        return [_rec(1), _rec(2)], 1234  # records, used_weight

    p = RestTradePoller(fetcher=fake_fetch)

    async def drive():
        return await p.poll_once(session=None)

    trades = asyncio.run(drive())
    assert [t.agg_trade_id for t in trades] == [1, 2]
    assert p.last_seen_id == 2
    assert p._used_weight == 1234
    assert "fromId" not in seen_params[0]  # first call


def test_run_emits_new_trades_then_stops():
    """run() pages forward across calls and never re-emits a seen id."""
    state = {"next_id": 1}

    async def fake_fetch(session, params):
        base = state["next_id"]
        recs = [_rec(base), _rec(base + 1)]
        state["next_id"] = base + 2
        return recs, 100

    p = RestTradePoller(fetcher=fake_fetch, poll_interval_s=0.0)

    async def drive():
        collected: list[int] = []
        async for t in p.run():
            collected.append(t.agg_trade_id)
            if len(collected) >= 6:
                break
        return collected

    collected = asyncio.run(drive())
    assert collected == [1, 2, 3, 4, 5, 6]
