# Phase 1 — Signal Research Design (Pre-Committed)

**Status:** PRE-COMMITMENT. Written 2026-05-17, before any Phase 1 IC numbers have been computed. Not executable until Phase 0 is CERTIFIED.

**This document is the contract.** It defines, before any data has been looked at, exactly which trials will be run, which thresholds qualify a signal as passing, and how multiple-testing deflation will be applied. **No edit to this document is permitted after the first Phase 1 IC is computed.** Edits would constitute peeking — the same discipline that produced three honest negative verdicts already in this project requires this contract stay frozen.

Pairs with `MICROSTRUCTURE_DESIGN.md` (the five-phase plan), `PHASE0_RUNBOOK.md` (operational doc), and the sub-project `CLAUDE.md`.

---

## 1. Phase 1 Entry Gate (must be green BEFORE any signal code)

All four Phase 0 exit criteria from `MICROSTRUCTURE_DESIGN.md` and `CLAUDE.md`:

1. ≥30 days of book data on disk (90 preferred).
2. `validation/book_snapshot_check.py` reports 0 diffs across 24 sample REST snapshots.
3. `validation/temporal_alignment.py` reports trade-vs-book violation rate <0.01%.
4. `validation/gap_detector.py` reports gap fraction <0.1%.

When all four are green, file `research/PHASE0_CERTIFIED.md` containing the four validator JSON outputs and the date. Only then does Phase 1 unlock.

---

## 2. What "passing Phase 1" means

A signal configuration passes Phase 1 if and only if **all three** of the following hold:

| Gate | Threshold | Why |
|---|---|---|
| **G1 — IC magnitude** | `|IC|` ≥ 0.03 at the peak horizon, in BOTH halves of the data. | Pre-committed in `MICROSTRUCTURE_DESIGN.md` §"Phase 1 — Signal Research". Below 0.03 the signal is indistinguishable from noise at this frequency. |
| **G2 — Sign consistency** | Sign of IC at peak horizon agrees between first-half and second-half splits. | Microstructure regimes shift; a signal that flips sign across halves is regime-specific, not robust. |
| **G3 — Stability** | The horizon at which `|IC|` peaks in the second half is within ±1 step on the horizon grid of the first-half peak. | Catches signals where the peak migrates across horizons (overfit by horizon-choice). |

A signal that passes G1+G2+G3 is reported as a Phase 1 SURVIVOR. **Surviving Phase 1 does NOT mean the signal is deployable** — it means the signal is worth taking into Phase 2 strategy design. Phase 2 then adds inventory risk, execution costs, and adverse-selection considerations that may still kill the signal.

If **0 surviving signals**: Phase 1 closes FAILED, the same way Tier 1 / Tier 2 / crypto carry closed. We document the failure path in §6.

---

## 3. The Trial Set (frozen)

### 3.1 Phase 1a — Standalone signals (56 trials)

| Signal family | Parameter | Values | Count |
|---|---|---|---|
| **Order Book Imbalance (OBI)** | depth (top-N levels) | 1, 5, 10, 20 | 4 |
| **Trade Flow Imbalance (TFI)** | rolling window | 10s, 30s, 60s, 300s | 4 |

For each `(signal, parameter)` pair, IC is measured at 7 horizons:

| Horizon K | 1s | 5s | 30s | 60s | 300s | 900s | 3600s |
|---|---|---|---|---|---|---|---|
| | (1s) | (5s) | (30s) | (1m) | (5m) | (15m) | (1h) |

Total Phase 1a trials = `(4 + 4) × 7 = 56`.

### 3.2 Phase 1b — Conditional, spread-filtered (contingent)

Phase 1b only runs if Phase 1a produces ≥1 SURVIVOR. The rationale: the design doc treats spread dynamics as a regime filter, not a standalone predictor. Running 1b only when 1a has hits keeps the deflation hurdle manageable while still pre-committing the full enumeration.

| Filter parameter | Values | Count |
|---|---|---|
| **Spread regime** | TIGHT (spread < median over trailing 5m) / WIDE (spread ≥ median) | 2 |

For each `(signal, parameter)` from Phase 1a — `(4 + 4) = 8` configs — times 2 spread regimes times 7 horizons = `8 × 2 × 7 = 112` conditional trials.

**Pre-committed contingency:** if Phase 1a closes FAILED, Phase 1b is NOT triggered and its 112 trials do not count in any deflation calculation. This is the only post-hoc decision permitted by this contract.

### 3.3 What is NOT in the trial set (banned from Phase 1)

The following are NOT trials and shall not be reported as IC computations:

- Microprice as a standalone predictor. Per the design doc, microprice is used to DEFINE returns (`r_K = log(microprice_{t+K} / microprice_t)`), not as a separate signal. There is exactly one return definition; varying it constitutes peeking.
- Combinations / linear blends of OBI + TFI. Combinations are Phase 2 strategy design, not Phase 1 signal research.
- Any signal not enumerated above. New signal ideas surface a `Phase 1.x` extension, which would require freezing a NEW design doc and re-running with a deflated hurdle.
- Different rolling-window functions on TFI (EWMA, exponential decay, etc.). Only flat windows of the four lengths above.
- Re-parameterization after seeing results. If `top-3` looks interesting after seeing `top-1`/`top-5` results, too bad — `top-3` was not in the pre-committed set.

---

## 4. Statistical Hygiene

### 4.1 No-look-ahead

Every IC computation must use `BookHistory` / data-handler patterns matching the equity event-driven engine's discipline: queries past `as_of` raise. Phase 3's `BookHistory` type is the canonical enforcement; until that exists, Phase 1 code reads parquet only with explicit `as_of` filtering.

Specifically: the signal at time `t` may only consume data with `local_ts_ns ≤ t`. Future-leakage in rolling computations (e.g., `pandas.rolling(...).mean()` centered windows) is a fatal bug, not a tunable.

### 4.2 Out-of-sample split

The collected book-data window is split exactly at the midpoint by calendar time. First half = design / IS. Second half = validation / OOS.

- IC, sign, and peak-horizon are computed independently in each half.
- G1–G3 gates check BOTH halves; failing in either half = failing the gate.
- No tuning, no parameter search, no signal modification is permitted after looking at the OOS half. The first OOS IC computed is the final OOS IC for that config.

### 4.3 Embargo

Cross-half embargo: a 1-hour embargo at the IS/OOS boundary excludes any sample whose label horizon K would straddle the boundary. This matches the López de Prado embargo discipline used in `alphaforge-python/research/stats_hygiene.py::PurgedEmbargoedKFold`.

### 4.4 Sample resolution

IC is computed on returns at the same 100ms cadence as the book snapshots. At 30 days × 24h × 3600s × 10 obs/s ≈ 2.6 × 10⁷ observations per half, statistical power at `|IC| = 0.03` is overwhelming under any conventional test. The risk Phase 1 actually faces is *regime specificity*, not *insufficient power* — hence the two-halves stability requirement does the work that a t-test would in a smaller-N setting.

### 4.5 Multiple-testing deflation

With 56 Phase 1a trials, the deflation hurdle equivalent to the equity gauntlet's DSR > 0.95 is:

- **Bonferroni-style for IC**: an IC's effective p-value is multiplied by 56. To clear a 5% per-family-wise error rate, the per-trial threshold corresponds to a higher `|IC|` than 0.03 — but **this contract does NOT adjust the 0.03 threshold upward**. Instead, the discipline relies on G1+G2+G3 *jointly* — IC magnitude AND sign consistency AND peak-horizon stability — to deflate the false-discovery rate.
- **Reported alongside**: each surviving config's IC will be reported with its Bonferroni-adjusted p-value as informational context, not as a separate gate.

If Phase 1b triggers, the effective trial count is `56 + 112 = 168`, but Phase 1b is reported in its own family (the conditional one) and G1+G2+G3 are applied independently.

### 4.6 Pre-committed reporting format

The Phase 1 output document (`research/PHASE1_VERDICT.md`, written AFTER execution) must include:

1. IC heatmap: rows = signal configs (8 in 1a), columns = horizons (7), cells = IC in IS half.
2. The same heatmap for OOS half.
3. For each config: peak horizon in IS, peak horizon in OOS, sign(IC) in each half, G1/G2/G3 verdict.
4. The full IC table as JSON for audit (`PHASE1_RESULTS.json`).
5. A NumPy random seed (for any bootstrap or resampling used) declared in the file header.

No prose interpretation precedes the tables. Tables first, prose after.

---

## 5. Cost-Awareness Pre-Gate (informational, not blocking)

Even a signal passing G1+G2+G3 only matters if expected return per trade exceeds Binance's fees. For each surviving config, compute:

- Expected return per trade horizon K = `|IC| × σ(r_K)`, where `σ(r_K)` is the standard deviation of K-horizon returns over the period.
- Compare to round-trip cost: taker fee (4 bps) + half-spread proxy (Corwin-Schultz on the trade tape, or directly from book on overlap days) + impact estimate.

If `E[return] < round-trip cost`, the signal is reported as "passes IC gate but fails cost-awareness pre-gate" and is NOT taken into Phase 2 as-is — it would require a passive-only execution design where maker rebates flip the cost sign.

This pre-gate is informational because Phase 2 handles execution-side decisions properly. Phase 1's job is to identify whether the signal has predictive content at all.

---

## 6. Decision Matrix (Phase 1 outcomes)

| # Survivors (1a + conditional 1b) | Outcome | Next action |
|---|---|---|
| 0 in 1a, 1b not triggered | **CLOSED FAILED** | File `PHASE1_VERDICT.md` with negative result. Per `MICROSTRUCTURE_DESIGN.md` "honest caveats after Phase 1": "If your decay analysis shows no signal with IC above 0.03 at any horizon, the answer is not to lower the threshold. The answer is to consider whether a different strategy class is more appropriate." Project enters a founder-track decision window matching the post-crypto-carry state. |
| ≥1 in 1a | **PROCEED TO 1b** | Run the 112 conditional trials. If 1b adds ≥1 survivor on top, the spread filter is included in the strategy design. |
| ≥1 final survivor | **PROCEED TO PHASE 2** | The surviving config(s) become the input to strategy design. Write `PHASE2_DESIGN.md` with pre-committed thresholds before any Phase 2 backtest runs. |
| ≥10 final survivors | **STOP AND TRIAGE** | A high pass rate this far into a deflated trial set is suspicious — either the data is leaking future info into signals, or the threshold is mis-calibrated. Audit `BookHistory` enforcement and the IS/OOS split before claiming the result. |

---

## 7. Honest Caveats (carried from `MICROSTRUCTURE_DESIGN.md`)

- **Latency**: Python over public WebSocket is L4 at best. Any signal whose peak IC is at K ≤ 1s is not exploitable at our execution stack. We will report such signals as "predictive but not exploitable at L4 latency" — they are interesting but not deployable. **A peak at K ≤ 1s does NOT pass the implicit "deployable" bar even if it passes G1+G2+G3.** This is a fourth, informational gate.
- **Queue position**: Phase 1 IC analysis does not depend on queue position. The exposure shows up in Phase 3 backtest fill modeling. Documented in `MICROSTRUCTURE_DESIGN.md` §"Phase 3 — Backtest Engine Surgery".
- **Wash trading on Binance**: trade-tape volume includes non-genuine prints. The IC=0.03 threshold accounts for this by being meaningfully above the no-noise expectation. Expect noisier ICs than equity-microstructure papers suggest.

---

## 8. Hard Rules (the non-negotiables)

1. **Do not edit this document after the first Phase 1 IC is computed.** Any edit constitutes peeking.
2. **Do not look at the OOS half until the IS half is fully written up.** "Looking" includes computing summary statistics, plotting, or running anything that produces a number from OOS data.
3. **Do not add trials to the trial set after starting.** New ideas land in `PHASE1_5_DESIGN.md` with a fresh deflated trial count.
4. **Do not lower a threshold to fit the data.** If 0.03 fails to produce survivors, the answer is row 1 of the failure-path matrix (strategy class problem) — pivot, don't tune.
5. **Do not retroactively split the trial set into "real" trials and "exploratory" trials.** All 56 base trials are real. All 112 conditional trials are real if Phase 1b triggers.

These rules failed exactly zero times across Tier 1, Tier 2, and crypto carry. They are why the project has three credible negative verdicts instead of three undeployed false positives. They are not optional here.

---

## 9. Authorship and Pre-Commitment Anchor

- **Author**: Atharva Patil
- **Drafted**: 2026-05-17 (pre-Phase-0-certification, pre-Phase-1-execution)
- **Pre-commitment anchor**: this document's SHA-256 hash will be computed and included in `PHASE0_CERTIFIED.md` when that document is filed. Subsequent edits to this file invalidate the Phase 1 execution and require a fresh contract.

```bash
# After committing this file:
shasum -a 256 alphaforge-microstructure/research/PHASE1_DESIGN.md
# Paste the hash into PHASE0_CERTIFIED.md to anchor the contract.
```
