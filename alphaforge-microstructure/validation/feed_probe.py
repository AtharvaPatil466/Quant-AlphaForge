"""Binance USDT-M futures feed probe — confirm whether the aggTrade (trade-print)
WebSocket stream is being served to THIS host/region.

Background (2026-06-24): the live collector produces book snapshots but zero
trades because `btcusdt@aggTrade` and `markPrice@1s` deliver NO frames here,
while `depth@100ms` and `bookTicker` flood the same fstream host and REST
`fapi/v1/aggTrades` returns prints ~1s old. Leading hypothesis: Binance gates
the trade-print WS feed for this IP/region. This probe confirms or refutes that
— run it once WITHOUT a VPN and once THROUGH a non-restricted region.

Usage:
    .venv/bin/python -m validation.feed_probe

PASS (aggTrade served): the `aggTrade` row shows a non-zero frame count.
FAIL (aggTrade gated):  `aggTrade` stays 0 while `depth`/`bookTicker` are > 0.
If a VPN flips aggTrade from 0 → non-zero, the native WS feed is restored and is
the preferred trade source (full per-trade fidelity, no REST-polling caveats).
"""

from __future__ import annotations

import asyncio
import ssl
import time

import aiohttp
import certifi

FSTREAM = "wss://fstream.binance.com/ws/{stream}"
REST_AGGTRADES = "https://fapi.binance.com/fapi/v1/aggTrades?symbol=BTCUSDT&limit=3"
PROBE_SECONDS = 10

# (stream name, role) — book/quote streams are the working controls; trade and
# markPrice are the suspected-gated streams.
STREAMS = [
    ("btcusdt@depth@100ms", "control (book)"),
    ("btcusdt@bookTicker", "control (quote)"),
    ("btcusdt@aggTrade", "SUSPECT (trade prints)"),
    ("btcusdt@markPrice@1s", "SUSPECT (mark price)"),
]


def _ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=certifi.where())


async def _count_frames(ctx: ssl.SSLContext, stream: str, seconds: int) -> int:
    """Open a single-stream WS and count frames of any type for `seconds`."""
    frames = 0
    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(
                FSTREAM.format(stream=stream), heartbeat=30, ssl=ctx
            ) as ws:

                async def drive() -> None:
                    nonlocal frames
                    async for _ in ws:
                        frames += 1

                try:
                    await asyncio.wait_for(drive(), timeout=seconds)
                except asyncio.TimeoutError:
                    pass
    except Exception as exc:  # noqa: BLE001 — report and continue
        print(f"  {stream:<26} CONNERR {type(exc).__name__}: {exc}")
        return -1
    return frames


async def _rest_recency(ctx: ssl.SSLContext) -> None:
    async with aiohttp.ClientSession() as session:
        async with session.get(REST_AGGTRADES, ssl=ctx, timeout=10) as r:
            data = await r.json()
    age_s = round((time.time() * 1000 - data[-1]["T"]) / 1000, 1)
    print(f"REST aggTrades sanity: latest print {age_s}s old (market is "
          f"{'TRADING' if age_s < 30 else 'STALE?'})\n")


async def main() -> None:
    ctx = _ssl_context()
    await _rest_recency(ctx)

    results: dict[str, int] = {}
    print(f"Probing each stream for {PROBE_SECONDS}s ...")
    for stream, role in STREAMS:
        n = await _count_frames(ctx, stream, PROBE_SECONDS)
        results[stream] = n
        print(f"  {stream:<26} {role:<24} frames={n}")

    agg = results.get("btcusdt@aggTrade", 0)
    book = results.get("btcusdt@depth@100ms", 0)
    print("\n==== VERDICT ====")
    if agg > 0:
        print("aggTrade SERVED — native trade-print WS works from this host. "
              "Use the live WS feed for trades.")
    elif book > 0:
        print("aggTrade GATED — trade prints silent while book stream works. "
              "This IP/region is not being served trade prints. Try a VPN, or "
              "fall back to REST aggTrades polling.")
    else:
        print("INCONCLUSIVE — even the book control returned 0 frames; check "
              "connectivity before trusting the aggTrade result.")


if __name__ == "__main__":
    asyncio.run(main())
