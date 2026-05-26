# Microstructure Phase 2 — Strategy Design (Pre-Committed)

**Status:** PRE-COMMITMENT, CONTINGENT. Written 2026-05-17. **Runs only if Phase 1 produces ≥1 SURVIVOR** per `PHASE1_DESIGN.md` §6. If Phase 1 closes FAILED, this document is unused.

**This document is the contract for the strategy spec.** Phase 2 produces a *fully specified strategy* — one with no remaining parameter degrees of freedom — ready to be handed off to the Phase 3 backtest engine. **No edits to this document after the first Phase 2 parameter value is computed.** Every threshold, sizing rule, risk limit, and execution decision is either fixed numerically here OR specified as a *deterministic rule applied to the Phase 1 result*. There are no free-floating "we'll tune that later" knobs.

Pairs with:
- `PHASE1_DESIGN.md` — the Phase 1 signal contract.
- `MICROSTRUCTURE_DESIGN.md` §"Phase 2 — Strategy Design" — the original prose framing.
- `alphaforge-execution/configs/execution_config.yaml` — kill-switch precedent for risk limits.

---

## 1. Why Pre-Commit the Strategy, Not Just the Signal

A Phase 1 survivor establishes that some signal config (e.g., `OBI@depth=5`, peak IC at K=30s) has predictive content. Strategy design then translates that predictive content into a tradable strategy with entry/exit thresholds, sizing, inventory limits, and execution discipline. Each of those decisions is a degree of freedom; each degree of freedom is a peeking opportunity unless pre-committed.

The Tier 1 / Tier 2 lesson applies in inverted form. Tier 2 falsified the row-2 hypothesis by lowering rebalance frequency *after* the Tier 1 MV alpha was known — that was the right discipline because lowering frequency was the *pre-committed Tier 2 test*. In microstructure, the equivalent failure mode is: pick the entry threshold, exit horizon, or inventory limit to maximize backtest Sharpe. **Pre-committing the parameter-derivation rules makes that impossible.**

---

## 2. The Parameter-Derivation Rules (frozen)

For any Phase 1 survivor — denoted `(signal, depth_or_window, K*)` where `K*` is its peak-IC horizon — the strategy parameters are derived as follows. **Values pop out deterministically from these rules; they are not chosen.**

### 2.1 Entry threshold

Let `s_t` be the signal value at time `t`, normalized to z-score using the IS-half mean and std. Entry signals are generated only when `|s_t|` exceeds a pre-committed z-threshold:

| Strategy variant | Entry z-threshold |
|---|---|
| **Standard** | 1.5 |
| **Conservative** | 2.0 |

Both variants run; they are not tuned against each other. Phase 2's deliverable is two fully-specified strategies, one per variant, both submitted to Phase 4 evaluation.

### 2.2 Exit rule

Exits are time-based, not threshold-based. A position opened at time `t` is closed at `t + K*`, where `K*` is the Phase 1 peak-IC horizon (rounded to the nearest 100ms tick). No early-exit on signal reversal (that would be a second decision rule and create peek-and-tune opportunities). The only override is the stop-loss in §2.5.

### 2.3 Position sizing

Fixed-notional per entry, NOT proportional to signal strength. Reason: signal-proportional sizing introduces another parameter (the proportionality constant) and creates correlation between sizing error and entry timing error. Fixed-notional keeps the experiment clean.

Notional per entry = `min(max_inventory / 3, top_of_book_notional)`:
- `max_inventory` from §2.4.
- `top_of_book_notional` = the resting size at the entry-side best price × current best price. Capping at top-of-book makes the standard variant never consume more than one level (the slippage assumption stays clean).

### 2.4 Maximum inventory

Pre-committed in dollar terms (NOT notional contracts). Set to **$50,000 USD-equivalent per side**. This is a research scale, not a deployment scale. It is intentionally smaller than the typical Phase 1 top-of-book depth on BTC-USDT perp so that backtest fills land at the best price under the conservative passive-only model (§3.3) and slippage from queue-jumping doesn't dominate the result.

If Phase 1 reveals a signal that's only profitable at scale beyond $50k (which would be surprising for a 100ms-cadence signal), Phase 2 reports "passes Phase 1 but research-scale not deployable" — the founder track does not run a hedge fund at $50k notional inventory.

### 2.5 Stop-loss

Time-based + price-based:

- **Time stop**: a position is closed unconditionally at `t + 2·K*` if not already closed via §2.2. Catches the case where the matching engine missed the K* exit (e.g., dropped fill event).
- **Price stop**: a position is closed when its mark-to-mid PnL falls below `-3 × MAD_K*(returns)`, where `MAD_K*(returns)` is the median absolute deviation of K*-horizon mid-returns computed on the IS half. The `3 × MAD` threshold is the pre-committed multiplier — not tuned. MAD is used instead of standard deviation for tail robustness.

The price stop dominates time stop when they conflict — i.e., a stopped-out position is closed at the stop price, not held until `t + 2·K*`.

### 2.6 Passive vs aggressive execution rule

The design doc treats this as a meaningful decision. Pre-commit a deterministic rule:

```
if |s_t| >= 2.5 OR current_spread_bps >= median(spread_bps_IS) + 1·MAD(spread_bps_IS):
    aggressive_market_order
else:
    passive_limit_at_best (queue position not modelable; see §3.3)
```

That is: hit the market only when (a) the signal is exceptionally strong (z ≥ 2.5), OR (b) the spread is wide enough that paying it is justified by the implied higher information-rate environment. Otherwise post passive. The `+1·MAD` is pre-committed, not tuned.

---

## 3. Cost & Execution Model (frozen for Phase 2 + Phase 3)

### 3.1 Honest cost components

- **Taker fee**: 4 bps (Binance USDT-M futures market-taker rate, retail tier).
- **Maker rebate**: −2 bps (Binance maker rate; rebate means cost is *negative*, i.e., income).
- **Slippage beyond top-of-book**: only applies if §2.3's `top_of_book_notional` cap fails to keep an order at one level. Modeled in Phase 3 by the engine's queue-aware fill model.

### 3.2 The cost-awareness pre-trade gate (informational, blocks Phase 2 → Phase 3 if it fails)

Before any backtest is run, compute the expected per-trade economic return at the Phase 1 peak IC:

```
E[return_per_trade] = |IC_peak| × σ(returns over K*) − round_trip_cost
```

where `round_trip_cost` is:
- For the standard variant (mixed passive/aggressive per §2.6): `0.5 × (taker_fee + |maker_rebate|) × 2` ≈ 6 bps for an entry-and-exit pair where one leg is aggressive, one passive, on average.
- For an all-aggressive variant: `2 × taker_fee` = 8 bps.
- For an all-passive variant: `2 × maker_rebate` = -4 bps (income).

If `E[return_per_trade] ≤ 0` for the standard variant, Phase 2 reports **PASSES PHASE 1 BUT FAILS COST-AWARENESS** and does not proceed to Phase 3 in its standard form. An all-passive variant *may* still pass — but an all-passive variant is a market-making strategy, not the directional-microstructure strategy this contract specifies, and would require its own design doc.

This is a gate, not a tunable. If `E[return_per_trade] ≤ 0`, we do not "try a longer K*" or "use a tighter entry threshold." Those moves are pre-commit violations.

### 3.3 Backtest fill assumption (pre-committed for Phase 3)

Queue position is not observable from public L2 data. The pre-committed fill model is conservative:

- **Passive limit at best**: fills only when the market price *trades through* the order's level (i.e., we get filled only on adverse moves). Never assume a fill at the best price on a non-trade-through tick.
- **Aggressive market order**: fills instantly at the opposite-side best, with slippage to the next level only if the order's notional exceeds top-of-book depth at the timestamp.

This understates passive performance (real queue position would sometimes fill at the best price on non-trade-through ticks). It is the **honest understatement** documented in `MICROSTRUCTURE_DESIGN.md` §"Phase 3 — Backtest Engine Surgery". A signal that passes Phase 4 under this fill model passes despite the headwind, which is the right direction of bias.

---

## 4. Risk Controls (load-bearing, mirror execution-system precedent)

Inventory and stop-loss are not optional. They are integrated into the strategy spec at the same load-bearing level as the kill-switch in `alphaforge-execution/risk/kill_switch.py`. Specifically:

1. **Inventory cap** (§2.4): if a new entry signal would push net inventory past $50k USD-equivalent, the entry is dropped. Not deferred, not queued — dropped. This is consistent with the execution system's pre-trade size check.
2. **Stop-loss** (§2.5): unconditional. The matching engine cannot defer a stop-out.
3. **Maximum simultaneous positions**: 3. (Three concurrent entries × $50k / 3 inventory cap = $50k max gross exposure.)
4. **Daily loss limit**: −2% of capital. If hit, the strategy halts for the rest of the day. Re-enables at next UTC midnight. Same shape as the execution system's kill-switch.

These are not Phase 4 evaluation gates — they are part of the strategy spec. A Phase 2 strategy without these controls is incomplete.

---

## 5. Phase 2 Trial Count

Phase 2 produces **2 strategy variants** (standard + conservative entry-threshold, both with identical exit/sizing/risk rules). Both are submitted to Phase 3 backtest and Phase 4 evaluation.

The Phase 4 DSR deflation factor is therefore `phase1_survivor_count × 2`. This is pre-committed here so the Phase 4 verdict doc cannot retroactively claim a smaller trial count.

---

## 6. Decision Matrix (Phase 2 outcomes)

| Cost-awareness gate (§3.2) | Both variants spec-complete? | Verdict |
|---|---|---|
| Pass for standard variant | Yes | **PROCEED TO PHASE 3** (backtest engine surgery). Standard + conservative variants both proceed. |
| Fail for standard variant (E[return] ≤ 0 net of 6bp cost) | — | **STOP**. PHASE2_VERDICT.md filed with the negative cost-awareness number. Phase 1 survivor is reported as "predictive but not economically tradable under retail-tier costs." |
| Standard variant passes cost-awareness but stop-loss MAD is computed as 0 or NaN (degenerate Phase 1 returns) | — | **STOP AND TRIAGE**. The Phase 1 result is degenerate; revisit Phase 1 data before Phase 3. |

---

## 7. Hard Rules (the non-negotiables)

1. **Phase 2 does not run if Phase 1 has zero survivors.**
2. **Entry threshold values are 1.5 and 2.0. Period.** No "let's see what happens at 1.75" runs.
3. **Exit horizon = Phase 1 peak K\*.** Not the second-best horizon, not a "smoothed" horizon, not a horizon-grid average.
4. **Position sizing is fixed-notional.** No signal-proportional sizing, no Kelly-style scaling.
5. **Inventory cap, stop-loss MAD multiplier, max simultaneous positions, daily loss limit:** all fixed at the values in §2.4–2.5 and §4. No tuning.
6. **Passive/aggressive rule is the deterministic predicate in §2.6.** Not a learned classifier, not a discretionary rule.
7. **Cost-awareness gate is at 6 bps round-trip for the standard variant.** If `E[return_per_trade] ≤ 0`, Phase 2 stops. We do not "try a longer horizon to amortize cost" — that's a horizon change, which would be a Phase 1 reopening.
8. **No new variants beyond the two specified in §5.** "Passive-only" or "aggressive-only" are *different strategies* requiring their own design docs.

These rules are the microstructure analog of the discipline that produced four credible verdicts. They exist specifically because every degree of freedom in strategy design is a peeking opportunity.

---

## 8. What Phase 2 Hands Off to Phase 3

The Phase 3 backtest engine receives:

1. Two strategy specs (standard, conservative), each fully parameterized at the moment Phase 2 closes — i.e., after the Phase 1 peak K* is known and the IS-half MAD is computed.
2. The pre-committed fill model (§3.3).
3. The pre-committed cost model (§3.1).
4. The risk controls (§4) as enforced invariants of the simulation.

Phase 3's `PHASE3_DESIGN.md` (not yet written, will pre-commit before any backtest runs) will define the simulation loop, the queue-position approximation, the BookHistory enforcement, and the cost-wiring per fill. None of those are tunable based on Phase 2 results.

---

## 9. Authorship and Pre-Commitment Anchor

- **Author:** Atharva Patil
- **Drafted:** 2026-05-17 (pre-Phase-0-certification, pre-Phase-1-execution, pre-any-Phase-2-parameter-value)
- **Pre-commitment anchor:** this document's SHA-256 hash is to be included in `PHASE1_VERDICT.md` *only if* Phase 1 produces ≥1 survivor and Phase 2 is consequently triggered.

```bash
shasum -a 256 alphaforge-microstructure/research/PHASE2_DESIGN.md
```
