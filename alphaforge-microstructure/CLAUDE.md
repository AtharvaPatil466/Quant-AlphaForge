# CLAUDE.md — alphaforge-microstructure

Sub-project context for Claude Code. Cross-cutting project context lives in the top-level `CLAUDE.md`; this file covers only the microstructure stack.

## Status (as of 2026-05-17, session 3)

**Phase 0 IN PROGRESS.** This sub-project was spun up on 2026-05-17 as the candidate strategy-class pivot after three substrate failures (equity Tier 1, equity Tier 2, crypto carry — all CLOSED FAILED). The design doc at `research/MICROSTRUCTURE_DESIGN.md` is pre-committed and load-bearing; it defines the five-phase plan and the gates each phase must clear before the next is unblocked.

**Hard rule: no signal code, no strategy code, no backtest code is in scope until Phase 0 is complete.** Phase 0 means: 24/7 Binance public-data collector running, 30+ days of clean data accumulated, and the three Phase-0 validation checks (REST snapshot match, temporal alignment, gap inventory) all green on the collected data. The plan's Phase 1 explicitly says it is gated on this.

This is the same pre-commitment discipline that produced the three honest negative verdicts already in the repo. The discipline is the load-bearing piece.

**Current data state (2026-05-17):**
- Historical aggTrades: ~58 days on disk (2026-02-17 → 2026-04-15) from a `historical.binance_vision` pull. The user re-ran the loader for the 2026-02-17 → 2026-05-17 range; final coverage will fill in on completion.
- Live collector: started 2026-05-17 (user confirmed). Book-data clock begins now; needs 30+ days minimum to unblock Phase 1.
- `_gaps.jsonl` has 87 pre-fix `snapshot_reconcile:buffer empty` entries from a previous run — predate the 2026-05-17 binance_ws fix and can be ignored.

**Phase 1 is NOT yet unblocked.** TFI research could theoretically begin on archive trades alone, but the design contract requires *all four* Phase 0 exit criteria green before any signal code is written. Run the validators against accumulated data, file `PHASE0_CERTIFIED.md` when they all pass, then start Phase 1.

## Current Scaffold

```
alphaforge-microstructure/
├── CLAUDE.md                              # this file
├── research/
│   ├── MICROSTRUCTURE_DESIGN.md           # pre-committed five-phase plan
│   ├── PHASE0_RUNBOOK.md                  # how to run/supervise the collector
│   ├── PHASE1_DESIGN.md                   # pre-committed Phase 1 trial set + gates
│   ├── PHASE2_DESIGN.md                   # pre-committed Phase 2 strategy spec (contingent on Phase 1 survivors)
│   └── PHASE3_DESIGN.md                   # pre-committed Phase 3 backtest-engine surgery contract (contingent on Phase 2)
├── collector/                             # Phase 0 — live data (24/7)
│   ├── __init__.py
│   ├── book.py                            # L2 order book reconstruction
│   ├── binance_ws.py                      # WebSocket client (depth + aggTrade)
│   ├── storage.py                         # rolling parquet writer
│   ├── status.py                          # `python3 -m collector.status` readiness CLI
│   └── run_collector.py                   # entrypoint script
├── historical/                            # Phase 0 — archive backfill (aggTrades only)
│   ├── __init__.py
│   └── binance_vision.py                  # data.binance.vision aggTrades loader
├── validation/                            # Phase 0 only
│   ├── __init__.py
│   ├── book_snapshot_check.py             # reconstructed book vs REST snapshot
│   ├── temporal_alignment.py              # trade tape vs book ts ordering
│   ├── gap_detector.py                    # find feed gaps > 1s
│   └── live_vs_archive.py                 # cross-check live trades vs archive trades
├── tests/                                 # 56 tests, all green
│   ├── test_book.py                       # apply_diff + top-N invariants (13)
│   ├── test_historical.py                 # archive parser + schema parity (21)
│   ├── test_storage.py                    # parquet round-trip + hourly roll (9)
│   ├── test_validation.py                 # diff/temporal/gap synthetic-data (8)
│   └── test_live_vs_archive.py            # cross-check logic (5)
├── data/                                  # collected parquet shards (gitignored)
├── logs/                                  # collector logs + gap inventory (gitignored)
└── requirements.txt
```

Phase 1+ directories (`signals/`, `strategy/`, `backtest/`, etc.) do not exist yet and must not be created until Phase 0 closes.

## Instrument & Venue (Phase 0)

- **Instrument:** BTC-USDT perpetual on Binance USDT-M futures (`btcusdt` in stream symbol).
- **Streams:** `btcusdt@depth@100ms` (incremental L2 deltas) + `btcusdt@aggTrade` (aggressor-tagged trades).
- **REST snapshot endpoint:** `https://fapi.binance.com/fapi/v1/depth?symbol=BTCUSDT&limit=1000` — used for book initialization and periodic resync checks.
- **No other instruments.** The plan is explicit: BTC-USDT only until Phase 1 signal validation closes.

## Data Source Matrix — what each path unblocks

There are two ways to populate `data/` and they cover different research:

| Source | Module | Trades | Book (L2) | Granularity | Wall-clock |
|---|---|---|---|---|---|
| **Live WebSocket** | `collector/` | yes | **yes (full top-20)** | 100ms book + per-trade | requires ≥30 days running |
| **Binance Vision archives** | `historical/` | yes (multi-year) | **no** | per-trade | ~1 week of work, decades of data |

**There is no free historical L2 diff archive from Binance Vision.** They publish `aggTrades` (matches the live `@aggTrade` stream — usable verbatim), but the other products are not suitable:
- `bookTicker` — best-bid/ask only (L1, not L2)
- `bookDepth` — 5-second percentile depth aggregates, not level-by-level
- `klines` — OHLCV bars, useless for microstructure

**What this means for Phase 1:**
- **TFI** (Trade Flow Imbalance) research — fully unblocked by `historical/binance_vision.py` on multi-year archives. Run it today.
- **OBI / microprice / spread dynamics** — require the live collector. No archive shortcut. Wait 30+ days of `collector/run_collector.py` accumulating book snapshots.

The two paths write to the SAME parquet schema (`collector/storage.py::_trade_schema` and `historical/binance_vision.py::_trade_schema` are asserted-equal in tests). Downstream signal code is origin-agnostic for trade data; OBI code intrinsically requires book data, which only the live path produces.

## Storage Contract

The parquet store is the immutable Phase 0 artifact. Two streams, two tables:

- `data/book_snapshots/YYYY-MM-DD/HH.parquet`: one row per 100ms book update, columns `exchange_ts_ns`, `local_ts_ns`, `mid`, `spread`, `bid_px_1..20`, `bid_sz_1..20`, `ask_px_1..20`, `ask_sz_1..20`, `last_update_id`.
- `data/trades/YYYY-MM-DD/HH.parquet`: one row per aggregated trade, columns `exchange_ts_ns`, `local_ts_ns`, `price`, `size`, `is_buyer_maker` (aggressor side = ¬`is_buyer_maker`), `agg_trade_id`.

Timestamps are nanosecond ints, never floats. Files are rolled hourly so a crashed collector loses at most one hour of working state.

## Phase 0 Exit Criteria (the gate)

Before any Phase 1 code lands:

1. **30 days minimum** (90 days preferred) of collected data on disk.
2. `validation/book_snapshot_check.py` reports zero diffs (to-the-tick) between the reconstructed book and Binance's periodic REST snapshots over a 24h sample.
3. `validation/temporal_alignment.py` confirms every trade's `exchange_ts_ns` lies within `[book_snapshot_before, book_snapshot_after]` for ≥99.99% of trades.
4. `validation/gap_detector.py` emits a gap inventory; feed-gap minutes are <0.1% of total collection time, and each gap is explicitly logged so downstream research can exclude those windows.

Failing any of these means more collection time or a collector fix — not loosening the criterion.

## Commands

```bash
cd alphaforge-microstructure
python3 -m pip install -r requirements.txt

# --- Live path (Phase 0 source of book + trade data; book data is live-only) ---
# Start the 24/7 collector (run under tmux/systemd in production)
python3 -m collector.run_collector --symbol BTCUSDT --out data/

# Status / Phase 0 readiness — run any time during the accumulation window
python3 -m collector.status --data-root data/
python3 -m collector.status --data-root data/ --json   # machine-readable

# Run validation against collected data (after ≥1 day of accumulation)
python3 -m validation.book_snapshot_check --data-root data/ --samples 24
python3 -m validation.temporal_alignment --data-root data/ --date 2026-05-18
python3 -m validation.gap_detector --data-root data/ --start 2026-05-17 --end 2026-05-18

# Cross-check live-collector trades vs archive trades on overlap days.
# Requires writing live/archive to separate roots (e.g. data/live/, data/archive/)
# so the loader can distinguish them.
python3 -m validation.live_vs_archive \
    --live-root data/live/ --archive-root data/archive/ --date 2026-05-18

# --- Historical path (unblocks TFI research on multi-year trade data only) ---
python3 -m historical.binance_vision \
    --symbol BTCUSDT --start 2024-01-01 --end 2024-12-31 --out data/

# Tests
python3 -m pytest tests/ -v
```

See `research/PHASE0_RUNBOOK.md` for setup, supervision (tmux/systemd), recovery procedures, and the Phase 0 exit gate.

## Honest Caveats (carried from the design doc)

- **Latency:** Python over public WebSocket is L4 at best. Any signal whose IC decays below noise within ~1s is not exploitable at this execution stack. Phase 1 IC analysis will report peak-IC horizon explicitly.
- **Queue position:** Public L2 feeds do not expose queue position; any future passive-fill model will be a known overestimate.
- **Wash trading:** Some Binance trade-tape volume is not genuine. Signal noise floor is higher than equity-microstructure literature would suggest.

## Recent fixes

**2026-05-17 (session 6) — Pre-committed Phase 3 backtest-engine contract.** `research/PHASE3_DESIGN.md` filed. Pre-commits: simulation-loop architecture (event-driven at 100ms, reusing `alphaforge-python/backtest/event_driven/{events,execution,portfolio}` read-only), `BookHistory` PIT enforcement (raises on queries past `as_of_ns`), the binding fill model from PHASE2 §3.3 restated (passive only on trade-through, aggressive walks levels, no closed-form impact), per-fill cost wiring (no flat-bps post-hoc deduction — the retired `real_engine.py` lesson), 4-function strategy hook surface (cannot grow to 5 without a fresh contract), 10-minute per-backtest performance budget (hard ceiling — vectorize, do not subsample), and a synthetic-signal regression test as the engine's validation gate before any Phase 1 survivor runs. Eight hard rules close peeking doors. Scope-fence §5 enumerates what the engine deliberately does NOT do (no own-order matching, no own-order book impact, no latency simulation, no multi-instrument).

**2026-05-17 (session 5) — Pre-committed Phase 2 strategy design.** `research/PHASE2_DESIGN.md` filed before any Phase 1 result lands. Pre-commits the parameter-derivation rules (entry z-thresholds 1.5 and 2.0 as two variants, time-based exits at Phase 1 peak K\*, fixed-notional sizing capped at top-of-book, $50k USD-equivalent inventory cap, time + price stop-loss with `3×MAD` multiplier, deterministic passive/aggressive predicate based on signal z and spread z, 6bp round-trip cost-awareness gate). The doc takes the form of a *contract over derivation rules*, not parameter values — values pop out deterministically when Phase 1 closes. Phase 4 DSR deflation factor pre-committed at `phase1_survivor_count × 2`. Hard rules section enumerates 8 non-negotiables (no entry-threshold tuning, no signal-proportional sizing, no MAD-multiplier tuning, etc.). Mirrors the PEAD Phase 2 contract drafted in the same session for the parallel substrate.

**2026-05-17 (session 4) — Pre-committed Phase 1 design.** `research/PHASE1_DESIGN.md` filed before any Phase 1 IC is computed. Enumerates the 56-trial Phase 1a set (OBI top-{1,5,10,20} × 7 horizons + TFI window-{10s,30s,60s,300s} × 7 horizons) plus the 112-trial contingent Phase 1b spread-filter set. Defines G1 (|IC|≥0.03), G2 (sign consistency), G3 (peak-horizon stability) as the joint pass criteria, with a 50/50 calendar-time IS/OOS split and 1-hour embargo at the boundary. Session triggered after the user said "Phase 1 is unblocked" — pushed back honestly: live collector started today, ~hours of book data, gate is not green. User then picked "wait for the gate" and "pre-write Phase 1 design" as the in-between productive work. The design doc is the *contract* for Phase 1; its SHA-256 will anchor PHASE0_CERTIFIED.md when that lands.

**2026-05-17 (session 3) — Added validation tests + live↔archive consistency checker.** `tests/test_validation.py` (8 tests) covers `_diff_books` logic, temporal-alignment search-sorted invariants, and gap-detector threshold behavior on synthetic parquet fixtures. `validation/live_vs_archive.py` + `tests/test_live_vs_archive.py` (5 tests) cross-check trades from the two ingest paths on overlap days — index by `agg_trade_id`, assert price/size/side/exchange_ts identity, flag any divergence. Test suite is now 56/56 green.

**2026-05-17 (session 2) — `binance_ws._reconcile_buffer_with_snapshot` no longer raises on empty-buffer-after-drop.** Previously raised `BookResyncRequired("buffer empty after dropping stale events")` whenever the REST snapshot's `lastUpdateId` was newer than every buffered diff. That's a normal case — the right behavior is to let the next arriving WS event get bracket-checked by `OrderBook.apply_diff`'s `_post_seed_diffs == 0` branch. The old code wasted reconnect cycles (87 such events in `_gaps.jsonl` from the pre-fix collector run). After the fix, `_reconcile_buffer_with_snapshot` returns `Optional[BookSnapshot]` — `None` means "seeded, awaiting first diff," and `BookResyncRequired` is reserved for the genuine sequence-gap case where a buffered event fails the bracket check.

## What This Sub-Project Is NOT

- Not a live trading system. The execution-side bits (testnet order routing, kill-switch integration) are Phase 5 and live in `alphaforge-execution/` when they happen.
- Not a backtester. Phase 3 is engine surgery on the existing event-driven engine; that is also future work.
- Not authorized to consume paid data, exchange-private feeds, or anything beyond Binance public WebSockets + REST.
