"""Binance USDT-M futures WebSocket client for depth + aggTrade streams.

Streams:
    btcusdt@depth@100ms  — incremental L2 book deltas, 100ms cadence
    btcusdt@aggTrade     — aggregated trades, one event per match group

REST snapshot:
    GET https://fapi.binance.com/fapi/v1/depth?symbol=BTCUSDT&limit=1000

The collector follows Binance's documented sequence:
    1. Open WS stream, buffer events.
    2. Fetch REST snapshot.
    3. Drop buffered events with u <= snapshot.lastUpdateId.
    4. Verify first remaining event satisfies U <= lastUpdateId+1 <= u.
    5. Apply that event and all subsequent events, checking pu continuity.

On any BookResyncRequired, the collector tears down the book and restarts
from step 1. Resync events are logged with timestamps and gap size so the
gap-detector can later inventory them.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import AsyncIterator, Callable, Optional

import aiohttp

from .book import OrderBook, BookResyncRequired, BookSnapshot


log = logging.getLogger(__name__)


# --- config -----------------------------------------------------------------


FAPI_WS_URL = "wss://fstream.binance.com/stream"
FAPI_REST_DEPTH = "https://fapi.binance.com/fapi/v1/depth"
DEFAULT_DEPTH_LEVELS = 1000  # max for REST snapshot on USDT-M


@dataclass(slots=True)
class TradeEvent:
    exchange_ts_ns: int
    local_ts_ns: int
    agg_trade_id: int
    price: float
    size: float
    is_buyer_maker: bool  # aggressor side is the OPPOSITE of this


# --- helpers ----------------------------------------------------------------


def _ns_now() -> int:
    return time.time_ns()


def _ms_to_ns(ms: int) -> int:
    return int(ms) * 1_000_000


def _parse_levels(raw: list[list[str]]) -> list[tuple[float, float]]:
    return [(float(px), float(sz)) for px, sz in raw]


# --- the collector --------------------------------------------------------


class BinanceFuturesCollector:
    """Drives the WebSocket connection, applies diffs to the OrderBook,
    and yields validated (BookSnapshot, [TradeEvent]) updates downstream.

    Usage:
        async for kind, payload in collector.run():
            if kind == 'book':
                handle_book_snapshot(payload)
            elif kind == 'trade':
                handle_trade(payload)
            elif kind == 'gap':
                log_gap(payload)  # {'reason': ..., 'last_u': ..., 'ts_ns': ...}
    """

    def __init__(
        self,
        symbol: str = "BTCUSDT",
        depth_levels_emitted: int = 20,
    ) -> None:
        self.symbol = symbol.upper()
        self.stream_symbol = symbol.lower()
        self.depth_levels_emitted = depth_levels_emitted
        self.book = OrderBook()
        self._buffered_diffs: deque[dict] = deque()

    # -- public driver -------------------------------------------------------

    async def run(self) -> AsyncIterator[tuple[str, object]]:
        """Yield ('book', BookSnapshot) | ('trade', TradeEvent) | ('gap', dict).

        Runs forever. Caller is responsible for cancellation. On any
        resync, emits a 'gap' event and restarts cleanly.
        """
        backoff = 1.0
        while True:
            try:
                async for kind, payload in self._run_once():
                    yield kind, payload
                    backoff = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 — log + reconnect
                log.warning("collector loop crashed: %s; reconnecting in %.1fs", e, backoff)
                yield "gap", {"reason": f"loop_crash:{type(e).__name__}", "ts_ns": _ns_now()}
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)

    # -- one connection lifecycle -------------------------------------------

    async def _run_once(self) -> AsyncIterator[tuple[str, object]]:
        url = f"{FAPI_WS_URL}?streams={self.stream_symbol}@depth@100ms/{self.stream_symbol}@aggTrade"
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(url, heartbeat=30) as ws:
                log.info("connected: %s", url)

                # Reset state for this connection
                self.book = OrderBook()
                self._buffered_diffs.clear()

                # Step 1-2: buffer for a moment, then fetch snapshot.
                # The Binance doc says: subscribe first; we do that on
                # connect. We buffer for ~1s to ensure the snapshot's
                # lastUpdateId is bracketed by the buffer.
                buffer_started_ns = _ns_now()
                buffer_window_ns = 1_000_000_000
                snapshot_data: Optional[dict] = None

                async for msg in ws:
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        continue
                    local_ts = _ns_now()
                    evt = json.loads(msg.data)
                    stream = evt.get("stream", "")
                    data = evt.get("data", evt)

                    if stream.endswith("@depth@100ms") or data.get("e") == "depthUpdate":
                        self._buffered_diffs.append((data, local_ts))
                    elif stream.endswith("@aggTrade") or data.get("e") == "aggTrade":
                        # During the buffering window we drop trades — we
                        # haven't pinned the book yet so a trade has no
                        # book context. Once the book is seeded, trades
                        # flow normally.
                        if self.book.is_seeded:
                            yield "trade", self._trade_from_payload(data, local_ts)

                    # When the buffer window has elapsed AND we have not
                    # yet fetched a snapshot, fetch one now.
                    if snapshot_data is None and _ns_now() - buffer_started_ns >= buffer_window_ns:
                        snapshot_data = await self._fetch_rest_snapshot(session)
                        log.info(
                            "REST snapshot fetched: lastUpdateId=%d, bids=%d asks=%d",
                            snapshot_data["lastUpdateId"],
                            len(snapshot_data["bids"]),
                            len(snapshot_data["asks"]),
                        )

                        try:
                            first_snapshot = self._reconcile_buffer_with_snapshot(snapshot_data)
                        except BookResyncRequired as e:
                            log.warning("snapshot reconciliation failed: %s; reconnecting", e)
                            yield "gap", {
                                "reason": f"snapshot_reconcile:{e}",
                                "ts_ns": _ns_now(),
                            }
                            return  # falls through to outer reconnect loop

                        if first_snapshot is not None:
                            # Buffer had a bracketing event; first diff applied
                            # and a snapshot is ready to emit.
                            yield "book", first_snapshot
                        # else: buffer was empty after dropping stale events.
                        # Book is seeded but no first-diff applied yet. The next
                        # WS event that arrives will be bracket-checked by
                        # OrderBook.apply_diff (post_seed_diffs == 0 branch).

                    # If we have a seeded book, every subsequent diff applies.
                    if snapshot_data is not None and self.book.is_seeded and self._buffered_diffs:
                        for diff, diff_local_ts in list(self._buffered_diffs):
                            self._buffered_diffs.popleft()
                            try:
                                self.book.apply_diff(
                                    U=diff["U"],
                                    u=diff["u"],
                                    pu=diff.get("pu", -1),
                                    bids=_parse_levels(diff.get("b", [])),
                                    asks=_parse_levels(diff.get("a", [])),
                                )
                            except BookResyncRequired as e:
                                log.warning("sequence gap detected: %s; reconnecting", e)
                                yield "gap", {"reason": f"seq_gap:{e}", "ts_ns": _ns_now()}
                                return
                            yield "book", self.book.snapshot(
                                exchange_ts_ns=_ms_to_ns(diff.get("E", diff.get("T", 0))),
                                local_ts_ns=diff_local_ts,
                                n=self.depth_levels_emitted,
                            )

    # -- helpers -------------------------------------------------------------

    async def _fetch_rest_snapshot(self, session: aiohttp.ClientSession) -> dict:
        params = {"symbol": self.symbol, "limit": DEFAULT_DEPTH_LEVELS}
        async with session.get(FAPI_REST_DEPTH, params=params, timeout=10) as r:
            r.raise_for_status()
            return await r.json()

    def _reconcile_buffer_with_snapshot(self, snap: dict) -> Optional[BookSnapshot]:
        """Steps 3-4 of the Binance protocol.

        Returns the BookSnapshot taken right after the first valid diff is
        applied to the seeded book — OR `None` if the buffer was empty
        after dropping stale events (which is a normal outcome when the
        snapshot's `lastUpdateId` is newer than every buffered event).
        The caller must then keep listening: the next WS event will be
        bracket-checked by `OrderBook.apply_diff` directly.

        Raises BookResyncRequired only when there IS a buffered event but
        it doesn't bracket `lastUpdateId + 1` — that means we missed events
        between the snapshot and the buffer, and a full reconnect is
        required.
        """
        last_update_id = int(snap["lastUpdateId"])
        self.book.seed_from_snapshot(
            bids=_parse_levels(snap["bids"]),
            asks=_parse_levels(snap["asks"]),
            last_update_id=last_update_id,
        )

        # Drop stale buffered events.
        while self._buffered_diffs and self._buffered_diffs[0][0]["u"] <= last_update_id:
            self._buffered_diffs.popleft()

        if not self._buffered_diffs:
            # Normal case when snapshot is newer than all buffered events.
            # The next event we receive will satisfy the bracket condition
            # (or fail and trigger a reconnect via apply_diff's check).
            return None

        first, first_local_ts = self._buffered_diffs[0]
        if not self.book.is_first_diff_after_snapshot(first["U"], first["u"]):
            raise BookResyncRequired(
                f"first diff does not bracket lastUpdateId+1: "
                f"snap.lastUpdateId={last_update_id}, U={first['U']}, u={first['u']}"
            )

        self._buffered_diffs.popleft()
        self.book.apply_diff(
            U=first["U"],
            u=first["u"],
            pu=first.get("pu", last_update_id),  # not used on first event
            bids=_parse_levels(first.get("b", [])),
            asks=_parse_levels(first.get("a", [])),
        )
        return self.book.snapshot(
            exchange_ts_ns=_ms_to_ns(first.get("E", first.get("T", 0))),
            local_ts_ns=first_local_ts,
            n=self.depth_levels_emitted,
        )

    @staticmethod
    def _trade_from_payload(data: dict, local_ts_ns: int) -> TradeEvent:
        return TradeEvent(
            exchange_ts_ns=_ms_to_ns(data["T"]),  # trade time, ms
            local_ts_ns=local_ts_ns,
            agg_trade_id=int(data["a"]),
            price=float(data["p"]),
            size=float(data["q"]),
            is_buyer_maker=bool(data["m"]),
        )
