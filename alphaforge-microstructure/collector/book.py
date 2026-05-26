"""L2 order book reconstruction from Binance USDT-M futures depth-diff stream.

Binance documents the resync protocol at:
    https://binance-docs.github.io/apidocs/futures/en/#how-to-manage-a-local-order-book-correctly

The protocol, restated for this codebase:

1. Open the WebSocket diff stream first. Buffer every incoming event.
2. Fetch a REST depth snapshot. The snapshot has a `lastUpdateId`.
3. Drop every buffered event whose `u` (final update id) is <= snapshot's
   `lastUpdateId`.
4. The first event we APPLY must satisfy `U <= lastUpdateId + 1 <= u`,
   where U/u are the event's first/final update ids. If no buffered event
   satisfies this, the snapshot is stale relative to the buffer; restart.
5. From then on, each event's `pu` (prev-final-update-id) must equal the
   prior event's `u`. If `pu != prior.u`, the stream had a gap and the book
   must be torn down and rebuilt from a fresh snapshot.

This module enforces all five steps. It exposes a pure `OrderBook` class
plus a `BookSnapshot` value object suitable for parquet serialization.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional
from sortedcontainers import SortedDict


# --- public types -----------------------------------------------------------


@dataclass(slots=True)
class BookSnapshot:
    """A point-in-time picture of the top N levels of the book.

    Timestamps are nanoseconds since epoch. Exchange timestamps come from
    the WebSocket payload's `E` (event time, ms) widened to ns; local
    timestamps are filled by the collector when the event is received.
    """

    exchange_ts_ns: int
    local_ts_ns: int
    last_update_id: int
    bids: list[tuple[float, float]]  # [(price, size), ...] descending price
    asks: list[tuple[float, float]]  # [(price, size), ...] ascending price

    @property
    def best_bid(self) -> Optional[float]:
        return self.bids[0][0] if self.bids else None

    @property
    def best_ask(self) -> Optional[float]:
        return self.asks[0][0] if self.asks else None

    @property
    def mid(self) -> Optional[float]:
        bb, ba = self.best_bid, self.best_ask
        if bb is None or ba is None:
            return None
        return 0.5 * (bb + ba)

    @property
    def spread(self) -> Optional[float]:
        bb, ba = self.best_bid, self.best_ask
        if bb is None or ba is None:
            return None
        return ba - bb


class BookResyncRequired(Exception):
    """Raised when the diff stream has a gap that invalidates the local book.

    The collector must respond by tearing down the OrderBook, fetching a
    fresh REST snapshot, and rebuilding. NEVER catch this and continue —
    silently dropping events here is the canonical microstructure data
    integrity failure.
    """


# --- core -------------------------------------------------------------------


class OrderBook:
    """Mutable local mirror of an exchange order book.

    Bids are stored as a SortedDict keyed by negative price so iteration
    yields highest-price-first; asks key by price directly (ascending).
    Size = 0 removes the level (per Binance's encoding).

    Sequence-number validation:

    - `last_update_id` tracks the `u` of the last applied event.
    - `apply_diff(event)` enforces `event['pu'] == last_update_id`. If not,
      raises BookResyncRequired.
    - On initial seed from REST snapshot, `last_update_id` is set to the
      snapshot's `lastUpdateId`. The first diff to apply must then satisfy
      `event['U'] <= last_update_id + 1 <= event['u']` — use
      `is_first_diff_after_snapshot` for that check.
    """

    __slots__ = ("_bids", "_asks", "last_update_id", "_seeded", "_post_seed_diffs")

    def __init__(self) -> None:
        self._bids: SortedDict = SortedDict()  # keyed by -price → size
        self._asks: SortedDict = SortedDict()  # keyed by  price → size
        self.last_update_id: int = -1
        self._seeded: bool = False
        self._post_seed_diffs: int = 0

    # -- seed / resync -------------------------------------------------------

    def seed_from_snapshot(
        self,
        bids: Iterable[tuple[float, float]],
        asks: Iterable[tuple[float, float]],
        last_update_id: int,
    ) -> None:
        """Initialize from a REST depth snapshot. Wipes any prior state."""
        self._bids.clear()
        self._asks.clear()
        for px, sz in bids:
            if sz > 0:
                self._bids[-px] = sz
        for px, sz in asks:
            if sz > 0:
                self._asks[px] = sz
        self.last_update_id = int(last_update_id)
        self._seeded = True
        self._post_seed_diffs = 0

    def is_first_diff_after_snapshot(self, U: int, u: int) -> bool:
        """Per Binance docs, the first diff to apply after a snapshot must
        bracket the snapshot's `lastUpdateId + 1`."""
        return U <= self.last_update_id + 1 <= u

    # -- diff application ----------------------------------------------------

    def apply_diff(
        self,
        U: int,
        u: int,
        pu: int,
        bids: Iterable[tuple[float, float]],
        asks: Iterable[tuple[float, float]],
    ) -> None:
        """Apply one depth-diff event.

        Args mirror the Binance payload fields:
            U  = First update id in event
            u  = Final update id in event
            pu = Previous-event's `u` (continuity check)

        Raises BookResyncRequired if the sequence-number invariant breaks.
        """
        if not self._seeded:
            raise BookResyncRequired("apply_diff called before seed_from_snapshot")

        # The very first diff after a seed is validated by the caller via
        # is_first_diff_after_snapshot (the bracket check). After that
        # first event, every subsequent event must satisfy pu == prior u.
        if self._post_seed_diffs == 0:
            if not self.is_first_diff_after_snapshot(U, u):
                raise BookResyncRequired(
                    f"first diff after seed does not bracket lastUpdateId+1: "
                    f"snap.lastUpdateId={self.last_update_id}, U={U}, u={u}"
                )
        elif pu != self.last_update_id:
            raise BookResyncRequired(
                f"sequence gap: prev_u={self.last_update_id}, event_pu={pu}, U={U}, u={u}"
            )

        for px, sz in bids:
            if sz == 0:
                self._bids.pop(-px, None)
            else:
                self._bids[-px] = sz
        for px, sz in asks:
            if sz == 0:
                self._asks.pop(px, None)
            else:
                self._asks[px] = sz

        self.last_update_id = int(u)
        self._post_seed_diffs += 1

    # -- read-side -----------------------------------------------------------

    def top_n(self, n: int = 20) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
        """Return (bids, asks), each at most `n` levels."""
        bid_keys = list(self._bids.islice(0, n))
        ask_keys = list(self._asks.islice(0, n))
        bids = [(-k, self._bids[k]) for k in bid_keys]
        asks = [(k, self._asks[k]) for k in ask_keys]
        return bids, asks

    def snapshot(self, exchange_ts_ns: int, local_ts_ns: int, n: int = 20) -> BookSnapshot:
        bids, asks = self.top_n(n)
        return BookSnapshot(
            exchange_ts_ns=exchange_ts_ns,
            local_ts_ns=local_ts_ns,
            last_update_id=self.last_update_id,
            bids=bids,
            asks=asks,
        )

    @property
    def is_seeded(self) -> bool:
        return self._seeded

    def __len__(self) -> int:
        return len(self._bids) + len(self._asks)
