"""REST aggTrades poller — the trade-tape source for Phase 0.

Why this exists (2026-06-24): the `btcusdt@aggTrade` WebSocket stream is
region-gated for this host (Binance derivatives restriction for the collecting
IP). Book streams (`depth@100ms`) flow fine, so the live collector accumulated
book snapshots but ZERO trades. The REST endpoint

    GET https://fapi.binance.com/fapi/v1/aggTrades?symbol=BTCUSDT&fromId=<id>&limit=1000

is NOT gated and returns the same aggregated trades with the exchange's own `T`
timestamp. We page forward by aggregate-trade id (`fromId = last_seen + 1`), so
no trade is ever skipped — the worst case under load is added *latency*, never
*loss*. Local receive latency is irrelevant for Phase 0 accumulation because
Hawkes/TFI calibration keys off the exchange timestamp `T`, not arrival time.

Fidelity caveats are documented in `COLLECTOR_NOTES.md`.

Rate-limit budgeting: USDT-M futures REST is governed by a per-IP weight limit
(`X-MBX-USED-WEIGHT-1M`, 2400/min). Each aggTrades request costs
``AGGTRADES_REQUEST_WEIGHT``. The poller reads the used-weight header back from
every response and throttles once it crosses a soft cap, so a burst (e.g.
draining a backlog after a restart) can never trip the hard limit.
"""

from __future__ import annotations

import asyncio
import logging
import ssl
import time
from typing import AsyncIterator, Awaitable, Callable, Optional

import aiohttp
import certifi

from .binance_ws import TradeEvent


log = logging.getLogger(__name__)


# --- config -----------------------------------------------------------------

FAPI_REST_AGGTRADES = "https://fapi.binance.com/fapi/v1/aggTrades"
DEFAULT_LIMIT = 1000  # max page size for fapi/v1/aggTrades

# Steady-state cadence. At AGGTRADES_REQUEST_WEIGHT=20, one request per second is
# 1200 weight/min — comfortably under the 2400/min hard cap with headroom for the
# burst-drain path. The decision note allows ~250ms–1s; 1s is the safe default
# and the throttle below protects any faster cadence.
DEFAULT_POLL_INTERVAL_S = 1.0

# USDT-M futures REST budget. `aggTrades` weight is fixed at 20 regardless of
# `limit`; the per-IP limit is 2400 weight/min. Soft cap at 75% leaves margin
# for clock skew between our minute window and Binance's.
FUTURES_WEIGHT_LIMIT_1M = 2400
AGGTRADES_REQUEST_WEIGHT = 20
DEFAULT_WEIGHT_SOFT_CAP = 1800

# When we cross the soft cap, sleep long enough that the trailing 1-minute weight
# window drains meaningfully before the next request.
THROTTLE_COOLDOWN_S = 10.0


# Fetcher signature: (session, params) -> (records, used_weight_or_None).
FetchFn = Callable[
    [Optional["aiohttp.ClientSession"], dict],
    Awaitable[tuple[list[dict], Optional[int]]],
]


# --- helpers ----------------------------------------------------------------


def _ns_now() -> int:
    return time.time_ns()


def _ms_to_ns(ms: int) -> int:
    return int(ms) * 1_000_000


def _ssl_context() -> ssl.SSLContext:
    """Pin certifi's CA bundle, mirroring binance_ws — the python.org macOS build
    ships without a working system trust store and would otherwise fail TLS."""
    return ssl.create_default_context(cafile=certifi.where())


def _trade_from_rest_record(rec: dict, local_ts_ns: int) -> TradeEvent:
    """Map one REST aggTrades record to a TradeEvent.

    The REST record carries the same keys as the `@aggTrade` WS payload, so the
    resulting rows are schema-identical to the (gated) live-WS path:
        a -> agg_trade_id, p -> price, q -> size, T -> exchange_ts (ms), m -> maker.
    """
    return TradeEvent(
        exchange_ts_ns=_ms_to_ns(rec["T"]),  # exchange trade time, ms -> ns
        local_ts_ns=local_ts_ns,
        agg_trade_id=int(rec["a"]),
        price=float(rec["p"]),
        size=float(rec["q"]),
        is_buyer_maker=bool(rec["m"]),
    )


# --- the poller -------------------------------------------------------------


class RestTradePoller:
    """Polls `fapi/v1/aggTrades`, paging forward by id, and yields TradeEvents.

    Usage:
        poller = RestTradePoller(symbol="BTCUSDT")
        async for trade in poller.run():
            store.write_trade(trade)

    The poller is deliberately split into small pure pieces (`next_params`,
    `ingest`, `record_weight`, `should_throttle`, `next_sleep_s`) so its contract
    is testable without a live connection; `poll_once`/`run` are the thin async
    shell over them. A `fetcher` may be injected to bypass aiohttp in tests.
    """

    def __init__(
        self,
        symbol: str = "BTCUSDT",
        *,
        limit: int = DEFAULT_LIMIT,
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
        weight_soft_cap: int = DEFAULT_WEIGHT_SOFT_CAP,
        base_url: str = FAPI_REST_AGGTRADES,
        fetcher: Optional[FetchFn] = None,
        clock: Callable[[], int] = _ns_now,
    ) -> None:
        self.symbol = symbol.upper()
        self.limit = limit
        self.poll_interval_s = poll_interval_s
        self.weight_soft_cap = weight_soft_cap
        self.base_url = base_url
        self._fetcher: FetchFn = fetcher or self._http_fetch
        self._clock = clock
        self._ssl = _ssl_context()

        self._last_seen_id: Optional[int] = None
        self._used_weight: int = 0

    # -- state accessors -----------------------------------------------------

    @property
    def last_seen_id(self) -> Optional[int]:
        return self._last_seen_id

    # -- pure request/parse contract ----------------------------------------

    def next_params(self) -> dict:
        """Build query params for the next request.

        The first poll has no `fromId` (Binance returns the most recent `limit`
        trades, which seeds `last_seen_id`); every later poll pages strictly
        forward from `last_seen_id + 1`.
        """
        params: dict = {"symbol": self.symbol, "limit": self.limit}
        if self._last_seen_id is not None:
            params["fromId"] = self._last_seen_id + 1
        return params

    def ingest(self, records: list[dict], local_ts_ns: int) -> list[TradeEvent]:
        """Convert new records to TradeEvents, dedup'ing by agg_trade_id.

        Records with an id at or below the id we have already emitted are
        dropped (Binance pages can overlap at the boundary). `last_seen_id`
        advances to the largest new id seen. Records are filtered against the
        fixed start-of-call `last_seen_id`, so ordering of the page does not
        matter for correctness.
        """
        last = self._last_seen_id
        out: list[TradeEvent] = []
        max_id = last if last is not None else -1
        for rec in records:
            agg_id = int(rec["a"])
            if last is not None and agg_id <= last:
                continue
            out.append(_trade_from_rest_record(rec, local_ts_ns))
            if agg_id > max_id:
                max_id = agg_id
        if out:
            self._last_seen_id = max_id
        return out

    # -- rate-limit budget ---------------------------------------------------

    def record_weight(self, used_weight: Optional[int]) -> None:
        """Record the `X-MBX-USED-WEIGHT-1M` value from the last response."""
        if used_weight is not None:
            self._used_weight = int(used_weight)

    def should_throttle(self) -> bool:
        return self._used_weight >= self.weight_soft_cap

    def next_sleep_s(self, full_page: bool) -> float:
        """How long to wait before the next request.

        Priority order:
          1. Over the weight soft cap -> back off (THROTTLE_COOLDOWN_S), even if
             there is a backlog. The budget always wins.
          2. Full page and within budget -> drain immediately (0s): a full page
             means more trades are already waiting, so don't idle.
          3. Otherwise -> the steady-state poll interval.
        """
        if self.should_throttle():
            return max(THROTTLE_COOLDOWN_S, self.poll_interval_s)
        if full_page:
            return 0.0
        return self.poll_interval_s

    # -- async shell ---------------------------------------------------------

    async def _http_fetch(
        self, session: aiohttp.ClientSession, params: dict
    ) -> tuple[list[dict], Optional[int]]:
        async with session.get(
            self.base_url, params=params, timeout=10, ssl=self._ssl
        ) as r:
            r.raise_for_status()
            uw = r.headers.get("X-MBX-USED-WEIGHT-1M")
            used = int(uw) if uw is not None else None
            return await r.json(), used

    async def poll_once(
        self, session: Optional[aiohttp.ClientSession]
    ) -> list[TradeEvent]:
        records, used_weight = await self._fetcher(session, self.next_params())
        self.record_weight(used_weight)
        return self.ingest(records, self._clock())

    async def run(self) -> AsyncIterator[TradeEvent]:
        """Yield TradeEvents forever. Reconnect/backs off on transient errors.

        The caller cancels this coroutine to stop it. On any exception the poller
        backs off (capped at 60s) and retries — `last_seen_id` is preserved, so a
        transient outage resumes exactly where it left off with no gap and no
        duplicate emission.
        """
        backoff = 1.0
        async with aiohttp.ClientSession() as session:
            while True:
                try:
                    trades = await self.poll_once(session)
                    for t in trades:
                        yield t
                    backoff = 1.0
                    full_page = len(trades) >= self.limit
                    sleep_s = self.next_sleep_s(full_page)
                    if sleep_s > 0:
                        await asyncio.sleep(sleep_s)
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001 — log + back off + retry
                    log.warning(
                        "aggTrades poll failed: %s; retrying in %.1fs", e, backoff
                    )
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 60.0)
