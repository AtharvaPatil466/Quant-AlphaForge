"""24/7 collector entrypoint.

Wires two independent sources into one ParquetStore:
  - BinanceFuturesCollector (WebSocket `depth@100ms`) -> book snapshots + gaps
  - RestTradePoller (REST `fapi/v1/aggTrades`)        -> trade tape

The WS `@aggTrade` stream is region-gated for this host (it delivers no frames),
so trades are sourced from REST polling instead — see COLLECTOR_NOTES.md. The two
sources run as separate consumer coroutines; they touch disjoint writers in the
store (book/gap vs trade), so no locking is needed in single-threaded asyncio.

Designed to be run under a process supervisor (launchd KeepAlive, systemd, tmux).
Exits non-zero on unrecoverable errors so the supervisor restarts it.

Usage:
    python3 -m collector.run_collector --symbol BTCUSDT --out data/
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from .binance_ws import BinanceFuturesCollector
from .book import BookSnapshot
from .rest_trade_poller import RestTradePoller
from .storage import ParquetStore


log = logging.getLogger("collector")


HEARTBEAT_INTERVAL_SECONDS = 60


@dataclass
class _Counters:
    books: int = 0
    trades: int = 0
    gaps: int = 0


def _configure_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"collector_{time.strftime('%Y%m%d_%H%M%S')}.log"
    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_path),
    ]
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )
    log.info("logging to %s", log_path)


async def _consume_book(
    collector: BinanceFuturesCollector,
    store: ParquetStore,
    counters: _Counters,
    symbol: str,
) -> None:
    """Drain the WebSocket source: persist book snapshots and gap events.

    The WS `trade` kind is intentionally ignored — `@aggTrade` is region-gated
    here and the REST poller is the authoritative trade source. Were the WS feed
    ever restored (e.g. via VPN), honouring it here would double-count trades.
    """
    async for kind, payload in collector.run():
        if kind == "book":
            snap: BookSnapshot = payload  # type: ignore[assignment]
            store.write_book_snapshot(snap)
            counters.books += 1
        elif kind == "gap":
            gap = dict(payload)  # type: ignore[arg-type]
            gap.setdefault("symbol", symbol)
            store.write_gap(gap)
            counters.gaps += 1
            log.warning("gap recorded: %s", gap)
        # kind == "trade" (WS): ignored — REST poller owns the trade tape.


async def _consume_trades(
    poller: RestTradePoller,
    store: ParquetStore,
    counters: _Counters,
) -> None:
    """Drain the REST aggTrades poller: persist the trade tape."""
    async for trade in poller.run():
        store.write_trade(trade)
        counters.trades += 1


async def _heartbeat(counters: _Counters) -> None:
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
        log.info(
            "heartbeat: books=%d trades=%d gaps=%d",
            counters.books, counters.trades, counters.gaps,
        )


async def _run(symbol: str, out_root: Path, log_dir: Path) -> None:
    store = ParquetStore(out_root)
    collector = BinanceFuturesCollector(symbol=symbol)
    poller = RestTradePoller(symbol=symbol)
    counters = _Counters()

    stop_event = asyncio.Event()

    def _request_stop(*_: object) -> None:
        log.info("stop signal received; flushing")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig_name in ("SIGINT", "SIGTERM"):
        try:
            loop.add_signal_handler(getattr(signal, sig_name), _request_stop)
        except NotImplementedError:
            # Windows: signal handlers via add_signal_handler not supported
            pass

    workers = [
        asyncio.create_task(_consume_book(collector, store, counters, symbol),
                            name="consume_book"),
        asyncio.create_task(_consume_trades(poller, store, counters),
                            name="consume_trades"),
        asyncio.create_task(_heartbeat(counters), name="heartbeat"),
    ]
    stop_waiter = asyncio.create_task(stop_event.wait(), name="stop_waiter")

    try:
        # Wake on either a stop signal or a worker terminating. A worker only
        # returns/raises on an unrecoverable error (both sources loop forever
        # internally), so a finished worker means we should exit non-zero and
        # let the supervisor restart us.
        done, _ = await asyncio.wait(
            [*workers, stop_waiter], return_when=asyncio.FIRST_COMPLETED
        )
        crashed = [t for t in workers if t in done]
        for t in crashed:
            exc = t.exception()
            if exc is not None:
                raise exc
            raise RuntimeError(f"collector worker {t.get_name()!r} exited unexpectedly")
    finally:
        for t in (*workers, stop_waiter):
            t.cancel()
        await asyncio.gather(*workers, stop_waiter, return_exceptions=True)
        store.close()
        log.info(
            "exiting: books=%d trades=%d gaps=%d",
            counters.books, counters.trades, counters.gaps,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Binance USDT-M L2 + tape collector")
    parser.add_argument("--symbol", default="BTCUSDT", help="Instrument (default BTCUSDT)")
    parser.add_argument("--out", type=Path, default=Path("data"), help="Output root")
    parser.add_argument("--log-dir", type=Path, default=Path("logs"), help="Log directory")
    args = parser.parse_args()

    _configure_logging(args.log_dir)
    try:
        asyncio.run(_run(args.symbol, args.out, args.log_dir))
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
