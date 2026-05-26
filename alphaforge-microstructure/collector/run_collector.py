"""24/7 collector entrypoint.

Wires BinanceFuturesCollector → ParquetStore. Logs gap events explicitly.
Designed to be run under a process supervisor (tmux, systemd, supervisord).
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
from pathlib import Path

from .binance_ws import BinanceFuturesCollector, TradeEvent
from .book import BookSnapshot
from .storage import ParquetStore


log = logging.getLogger("collector")


HEARTBEAT_INTERVAL_SECONDS = 60


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


async def _run(symbol: str, out_root: Path, log_dir: Path) -> None:
    store = ParquetStore(out_root)
    collector = BinanceFuturesCollector(symbol=symbol)

    n_books = 0
    n_trades = 0
    n_gaps = 0
    last_heartbeat = time.time()

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

    try:
        async for kind, payload in collector.run():
            if stop_event.is_set():
                break

            if kind == "book":
                snap: BookSnapshot = payload  # type: ignore[assignment]
                store.write_book_snapshot(snap)
                n_books += 1
            elif kind == "trade":
                t: TradeEvent = payload  # type: ignore[assignment]
                store.write_trade(t)
                n_trades += 1
            elif kind == "gap":
                gap = dict(payload)  # type: ignore[arg-type]
                gap.setdefault("symbol", symbol)
                store.write_gap(gap)
                n_gaps += 1
                log.warning("gap recorded: %s", gap)

            now = time.time()
            if now - last_heartbeat >= HEARTBEAT_INTERVAL_SECONDS:
                log.info(
                    "heartbeat: books=%d trades=%d gaps=%d",
                    n_books, n_trades, n_gaps,
                )
                last_heartbeat = now
    finally:
        store.close()
        log.info(
            "exiting: books=%d trades=%d gaps=%d",
            n_books, n_trades, n_gaps,
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
