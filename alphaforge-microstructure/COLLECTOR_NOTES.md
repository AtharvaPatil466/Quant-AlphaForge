# Collector Notes — trade-tape fidelity caveats

**Status: 2026-06-24.** These caveats describe how the Phase 0 collector sources
its two data streams and what the resulting parquet does and does not guarantee.
They are load-bearing for any Phase 1 signal that consumes the trade tape (TFI,
Hawkes). Read alongside `research/PHASE0_RECOVERY.md` and `CLAUDE.md`.

## Two sources, one store

| Stream | Source | Module | Notes |
|---|---|---|---|
| Book (L2 top-20, 100ms) | WebSocket `btcusdt@depth@100ms` | `collector/binance_ws.py` | Full fidelity; native diff stream. |
| Trade tape (aggregated) | **REST** `fapi/v1/aggTrades` | `collector/rest_trade_poller.py` | Polled, not streamed — see below. |

Both write the same parquet schema as before (`storage.py`); downstream code is
origin-agnostic for trade rows.

## Why the trade tape is REST-polled, not WebSocket-streamed

The `btcusdt@aggTrade` WebSocket stream is **region-gated** for the collecting
host's IP (a Binance derivatives restriction). It connects but delivers **zero
frames**, while `depth@100ms`/`bookTicker` on the same host flood normally. This
was the second of two bugs that left the collector producing books but no trades.
`feed_probe.py` (now in `validation/`) confirms the gating; a VPN through a
non-restricted region flips `aggTrade` from 0 → non-zero.

REST `fapi/v1/aggTrades` is **not** gated from this IP and returns the same
aggregated trades, so it is the chosen trade source. Decision is final for
Phase 0 accumulation; if a future VPN restores the native WS feed it is preferred
(no polling caveats), but the collector deliberately **ignores** WS `trade`
events while REST polling is active to avoid double-counting.

## Fidelity caveats (the important part)

1. **Timestamp used is the exchange's `T`, not local receive time.** Each row's
   `exchange_ts_ns` is Binance's trade timestamp (`T`, ms → ns). `local_ts_ns`
   records when *our poller* received the record and is therefore inflated by the
   polling latency — **do not** use `local_ts_ns` for trade research. All
   TFI/Hawkes timing keys off `exchange_ts_ns`. Because `T` is set by the
   exchange at match time, REST polling introduces **no error** in the quantity
   that matters; it only delays when we learn about the trade.

2. **Polling interval ≈ 250 ms – 1 s (default 1 s).** Steady-state cadence is
   `DEFAULT_POLL_INTERVAL_S = 1.0`. When a page comes back full (a backlog
   exists, e.g. just after a restart or during a volume burst), the poller drains
   immediately (0 s sleep) until it catches up, subject to the weight budget.

3. **No trade is ever skipped — worst case is latency, never loss.** The poller
   pages strictly forward by aggregate-trade id (`fromId = last_seen + 1`). Under
   extreme volume it may fall behind real time, but it always resumes from the
   exact next unseen id, so the recorded series is **gap-free in id space**. This
   is the property that makes REST polling acceptable for accumulation.

4. **Rate-limit budgeting.** USDT-M futures REST is governed by a per-IP weight
   limit of 2400/min (`X-MBX-USED-WEIGHT-1M`); each `aggTrades` request costs 20
   (confirmed live). The poller reads the used-weight header back from every
   response and throttles (10 s cooldown) once it crosses a soft cap of 1800
   (75%), so the burst-drain path can never trip the hard limit and earn a 418/429
   ban. At the 1 s default that is 1200 weight/min — comfortably under cap.

5. **Cross-restart overlap → dedup by `agg_trade_id` downstream.** Within a single
   process run, dedup is exact (monotonic `last_seen_id`). Across a restart the
   poller cold-starts with no `fromId` and re-fetches the most recent ~1000
   trades to re-seed, which can re-emit trades already written before the crash.
   `agg_trade_id` is stored on every row and is unique/monotonic, so any analysis
   pass MUST dedup the trade tape by `agg_trade_id` (the existing
   `validation/live_vs_archive.py` already indexes by it). Treat the trades table
   as a multiset keyed by `agg_trade_id`, not as already-unique.

## Inherited caveats (from the design doc, unchanged)

- **Latency:** Python over public REST/WS is L4 at best. Any signal whose IC
  decays below noise within ~1 s is not exploitable at this stack. Phase 1 IC
  analysis reports peak-IC horizon explicitly.
- **Queue position:** public L2 feeds expose no queue position; any passive-fill
  model is a known overestimate.
- **Wash trading:** some Binance tape volume is not genuine; the noise floor is
  higher than equity-microstructure literature suggests.
