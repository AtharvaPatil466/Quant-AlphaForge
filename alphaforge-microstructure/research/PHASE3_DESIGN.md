# Microstructure Phase 3 — Backtest Engine Surgery (Pre-Committed)

**Status:** PRE-COMMITMENT, CONTINGENT. Written 2026-05-17. **Runs only if Phase 2 has produced ≥1 fully-specified strategy** per `PHASE2_DESIGN.md` §6. If Phase 2 stops at the cost-awareness gate or Phase 1 has no survivors, this document is unused.

**This document pre-commits the engine architecture.** Per my own honest read of the timeline, Phase 3 is the schedule-risk phase — the place where unbounded scope eats weeks. Pre-committing the simulation-loop architecture, the queue-position approximation, the cost-wiring discipline, and a performance budget makes the engine work bounded.

Pairs with:
- `PHASE2_DESIGN.md` §3.3 — the fill assumption that's already pre-committed.
- `MICROSTRUCTURE_DESIGN.md` §"Phase 3 — Backtest Engine Surgery" — original prose framing.
- `alphaforge-python/backtest/event_driven/` — the equity event-driven engine. Read-only carryover. The patterns survive; the time resolution does not.

---

## 1. What Carries Over Read-Only From the Existing Engine

The Tier 2 retirement of `real_engine.py` produced a clean event-driven engine in `alphaforge-python/backtest/event_driven/` with four pieces that *all* carry forward as discipline patterns:

| Existing module | Microstructure analog | Reuse mode |
|---|---|---|
| `events.py` (`MarketEvent`, `SignalEvent`, `OrderEvent`, `FillEvent`) | Identical events at 100ms cadence | **Imported as-is**. Event types do not change. |
| `data_handler.py::BarHistory` (raises if queried past `as_of`) | `BookHistory` (raises if queried past `as_of_ns`) | **New class, same discipline.** Nanosecond clock instead of daily. |
| `execution.py::ExecutionHandler` (requires next-bar timestamp > order timestamp) | Same invariant at ns granularity | **Imported, parameterized on resolution.** |
| `portfolio.py::Portfolio` (fails loudly on missing prices, per-fill cost accounting) | Same | **Imported as-is**. |

The equity engine's regression test (`test_engine_consolidation.py`) is the precedent for this sub-project's regression gate (§7).

---

## 2. What's New (Architecturally)

### 2.1 `BookHistory`

A point-in-time L2 book mirror sitting alongside `BarHistory`. Holds the reconstructed top-N book state up to the current simulation timestamp `as_of_ns`. Queries past `as_of_ns` raise `LookaheadError`. Same shape as `BarHistory`; different time resolution.

The data backing `BookHistory` is the parquet store written by `collector/storage.py`. Reading: stream parquet shards in chronological order, advance the `as_of_ns` cursor on each event, expose `top_n_at(as_of_ns)` as the only read interface.

### 2.2 Simulation loop (100ms cadence)

The equity engine iterates over daily bars. Microstructure iterates over 100ms book-update events. The loop architecture is identical:

```
while events:
    event = next(events)              # advance as_of_ns
    book_history.advance(event)        # may raise LookaheadError
    if signal_engine.should_evaluate(event):
        signals = signal_engine.compute(book_history)   # strategy hooks
        orders = strategy.decide(signals, portfolio)
        execution.submit(orders)
    fills = execution.process(event)   # next-tick fills, no same-tick
    portfolio.apply(fills)             # per-fill cost
```

The signal engine is the only point where strategy-specific code enters the loop. Everything else is shared infrastructure.

### 2.3 Performance budget (frozen)

**One full backtest of one strategy variant on one OOS window must complete in ≤10 minutes wall-clock on the development machine.** This is the iteration budget. If the naive Python implementation exceeds it, the fix is to vectorize the hot path (numpy operations on event chunks), NOT to drop fidelity (e.g., subsample to 1s cadence). Subsampling would change the strategy's effective fill model and is a contract violation.

The 10-minute budget is the hard ceiling. The soft target is 2–5 minutes. At 30 days × 24h × 3600s × 10 obs/s ≈ 2.6×10⁷ events per OOS window, this implies ~50k events/sec sustained throughput — achievable with pyarrow + numpy if the per-event Python overhead is minimized via chunked iteration.

---

## 3. The Fill Model (frozen, mirrors PHASE2_DESIGN.md §3.3)

This restates PHASE2_DESIGN.md §3.3 as the *binding* fill model the engine implements. **No deviation in Phase 3 from what Phase 2 pre-committed.**

### 3.1 Passive limit-at-best (resting orders)

A passive limit order posted at the best price on side `S` fills if and only if the market trades *through* that price on side `S` after the order's submission timestamp.

- "Trades through" means: between submission and now, there is a trade-tape event at the order's price level with aggressor side opposite to `S`, OR a book event reduces the level's depth to zero with the order still resting.
- The order fills at the order's price (i.e., earns the spread).
- **The order NEVER fills on a non-trade-through tick**, even if hours pass and the best price moves favorably. This is the honest understatement that biases the backtest against the strategy.

### 3.2 Aggressive market order

Fills instantly at the opposite-side best price at the order's submission timestamp.

- If notional > top-of-book depth at that timestamp, the order *consumes* successive levels. Per-level slippage is the realized average fill price.
- The taker fee (4 bp) applies to the full notional.

### 3.3 Order book impact on aggressive orders

Aggressive orders larger than top-of-book have impact computed level-by-level from the L2 snapshot at order-submission time. **No statistical impact model** (square-root, linear-on-ADV, etc.) — direct level-walking only. This is more accurate at 100ms granularity than any closed-form model and consistent with the data we have.

### 3.4 What is NOT modeled (and is documented as bias)

- **Queue position for our passive orders.** We assume worst case (only filled on trade-through). Real queue position would sometimes fill on non-trade-through ticks. Bias direction: pessimistic for the strategy. Magnitude: unknown until live deployment.
- **Adverse selection of *other* market participants' passive orders.** Their fills are observed via the trade tape; we don't simulate their behavior, we just read the resulting trades.
- **Latency between strategy decision and order arrival at exchange.** Documented in `PHASE2_DESIGN.md` §"Honest Caveats" — Python over public WS is L4 at best. The backtest assumes zero latency, which is unrealistic and biased *in favor* of the strategy. Phase 4 must report this bias direction.

---

## 4. Cost Wiring (per-fill, not post-hoc)

Each `FillEvent` carries:

- `fee_bps` (taker 4 bp, maker −2 bp; sign convention: positive = cost, negative = income).
- `slippage_bps` (the difference between fill price and the best price at order submission, expressed in bp; 0 for passive fills, ≥ 0 for aggressive that consumed multiple levels).
- `notional_usd` (filled size × fill price).
- `cost_usd` = `(fee_bps + slippage_bps) × notional_usd / 10_000`.

The `Portfolio` debits `cost_usd` from cash on every fill. **No flat-bps deduction post-hoc.** This is the architectural correction that retired `real_engine.py` in Tier 2; it carries forward verbatim.

---

## 5. What the Engine Does NOT Do

A scope-fence to keep Phase 3 bounded:

- **No matching engine for our own orders against the order book.** Our orders never "fill against" other resting limits. Fill simulation is conditional on tape events (§3.1) or instant against the snapshot (§3.2). A full matching engine is out of scope.
- **No own-order impact on the public book.** Posting a passive order does not displace levels in the simulated book. (At $50k inventory cap on BTC-USDT perp where top-of-book is typically $100k+, this is approximately true. Documented as a known limitation.)
- **No simulation of latency.** Assumed zero. Phase 5 (live paper trade) measures realized latency separately.
- **No multi-instrument cross-impact.** One instrument (BTC-USDT perp); no spillover modeling.
- **No tick-size or lot-size validation.** Strategy orders are assumed to comply with Binance's contract specs at submission time.

---

## 6. Strategy Hook Surface (the only place strategy-specific code enters)

The engine exposes exactly four hooks to Phase 2 strategy code:

```python
class StrategyHook:
    def compute_signal(self, book_history: BookHistory, trade_tape: TradeTape) -> float: ...
    def decide_entry(self, signal_z: float, portfolio: Portfolio) -> Optional[OrderEvent]: ...
    def decide_exit(self, position: Position, book_history: BookHistory, now_ns: int) -> Optional[OrderEvent]: ...
    def check_risk(self, portfolio: Portfolio, prospective_order: OrderEvent) -> bool: ...
```

`compute_signal`, `decide_entry`, `decide_exit`, `check_risk` are the four functions a strategy implements. Each function's parameters and return type are fixed here. **Adding a fifth hook is a contract violation** — it expands the strategy's degrees of freedom mid-Phase-3.

The Phase 2 spec (entry threshold, exit horizon, sizing, stop-loss, passive/aggressive predicate) maps to these four hooks deterministically.

---

## 7. Validation Gate (the engine's regression test)

Before any Phase 1 survivor is run through the engine, the engine must pass a *synthetic-signal regression test*:

1. Construct a synthetic OBI-like signal with **known** predictive content (e.g., a sine wave plus noise where the next-100ms mid-return is a deterministic function of the signal).
2. Run the standard-variant strategy on this synthetic data.
3. The backtest must produce a Sharpe within ±0.2 of the analytically computable value, AND a per-trade P&L distribution centered at the analytically computable mean.

This test is what `alphaforge-python/backtest/event_driven/test_engine_consolidation.py` was for the equity engine — proof that the simulation produces the right answer on a problem with a known answer. If the synthetic-signal test fails, no real Phase 1 survivor is run until the test passes. Same gate Tier 2 used.

The test code lives in `alphaforge-microstructure/backtest/tests/test_synthetic_signal.py` (NOT YET CREATED — the backtest/ directory does not exist until this contract executes).

---

## 8. Hard Rules (the non-negotiables)

1. **Phase 3 does not run if Phase 2 has not produced a fully-specified strategy.**
2. **The fill model is exactly §3.** No "let's relax the trade-through requirement to see what happens" runs.
3. **No closed-form impact model.** Level-walking only.
4. **No subsampling of the 100ms cadence** to make backtests faster. Vectorize instead.
5. **The strategy hook surface (§6) has exactly 4 functions.** Adding a fifth requires a fresh design doc.
6. **The synthetic-signal regression test (§7) must pass before any Phase 1 survivor runs.**
7. **The performance budget (≤10 min per backtest) is a hard ceiling.** If naive Python doesn't make it, vectorize; do not drop fidelity.
8. **`alphaforge-python/backtest/event_driven/` modules are imported, not modified.** The retired `real_engine.py` is *retired*; we do not resurrect it for microstructure.

---

## 9. What Phase 3 Hands Off to Phase 4

Phase 4 receives:

1. A backtest CLI that takes `(strategy_variant, oos_window) -> (per_trade_pnl.parquet, daily_returns.csv, fill_log.parquet)`.
2. The synthetic-signal regression test (committed and green).
3. A `book_history.json` style audit artifact per backtest: the first and last `as_of_ns`, total events processed, mean per-event simulation time. Used for performance regression detection.
4. The two strategy variants from Phase 2 (standard z=1.5, conservative z=2.0), backtested on IS, OOS-A, OOS-B independently.

Phase 4 then runs the gauntlet on those backtest outputs: adverse-selection ratio, realized spread capture, Sharpe with stationary-bootstrap CI, cost-doubling stress, DSR deflation against `phase1_survivor_count × 2` trials.

---

## 10. Authorship and Pre-Commitment Anchor

- **Author:** Atharva Patil
- **Drafted:** 2026-05-17 (pre-Phase-0-certification, pre-Phase-1-execution, pre-engine-existence)
- **Pre-commitment anchor:** this document's SHA-256 hash is to be included in `PHASE2_VERDICT.md` *only if* Phase 2 produces a strategy spec and Phase 3 is consequently triggered.

```bash
shasum -a 256 alphaforge-microstructure/research/PHASE3_DESIGN.md
```
