# AlphaForge Prediction Markets — Favorite-Longshot Bias on Kalshi — Pre-Committed Design

**Substrate #10. Status: PRE-COMMITMENT.** Written 2026-06-16, before any Phase 1
calibration number has been computed. **This document is the contract.** It defines, before
the data is examined, the hypothesis, the exact trial set, the gates that qualify the edge
as real, and how multiple-testing deflation and statistical power are applied. **No edit is
permitted after the first Phase 1 calibration statistic is computed.** ADDENDUM sections are
permitted only for in-place engineering discoveries (e.g. the Phase 0 spike confirming the
fee schedule) that do not change the substantive contract.

Mirrors the discipline of the prior nine substrates (`alphaforge-vix/research/VIX_DESIGN.md`,
etc.). Statistics are the canonical `afgauntlet` package; this substrate adds a calibration
module (`afgauntlet/binary.py`) rather than re-implementing.

---

## 0. Context — Why prediction markets, why now

Nine substrates have closed FAILED or are blocked. The power-calibration work (2026-06-15,
`alphaforge-gauntlet/power/`) showed the binding constraint is a high, economically-strict
detection floor on retail predictive signals — and that **every failed substrate shared one
structural disadvantage: capacity favored the incumbents.** Prediction markets invert that.
A $40k Kalshi market is too small for an institution and exactly right for a solo retail
trader. This is the first substrate where being small is the edge.

The framing is deliberately **not** a fund-scale alpha hunt. The goal is a credible **live
track record + demonstrated skill**: positive realized edge and calibration that beats the
market's, over a pre-committed number of resolved events. Capacity caps the dollars — that
is accepted by design, not a failure.

## 1. The Hypothesis

The favorite-longshot bias (FLB) is among the most robust anomalies in betting-market
history: longshots are systematically overpriced, favorites underpriced. On Kalshi's binary
event contracts this becomes **systematic miscalibration at the price extremes**:

> Across resolved Kalshi binary contracts, market-implied probability (price in dollars,
> 0–1) is a biased estimator of realized resolution frequency: low-price ("longshot") YES
> contracts resolve YES **less** often than priced, and high-price ("favorite") contracts
> resolve YES **more** often than priced. A systematic rule that fades overpriced longshots
> and backs underpriced favorites, **net of Kalshi fees and the bid/ask spread**, produces
> a positive realized edge with calibration superior to the market's.

**Load-bearing caveat:** classic FLB is a sports/racing effect driven by recreational
lottery preference. Whether it exists, and in which categories, on Kalshi's universe (heavy
in short-horizon crypto/sports "MVE" markets, plus econ/weather/politics) is the Phase 1
question itself. **A CLOSED-FAILED Phase 1 is a fully acceptable, informative outcome.**

## 2. Phase 0 — Data Collection and Validation

Source: Kalshi public REST API, base `https://api.elections.kalshi.com/trade-api/v2`
(read-only; no auth needed for market data). The ONLY network module is
`ingest/kalshi_client.py`; everything else reads parquet.

- `GET /markets?status=settled&limit=&cursor=` → resolved contracts with `ticker`,
  `event_ticker`, `result` ∈ {yes,no}, `settlement_value_dollars`, `last_price_dollars`,
  `yes_bid/ask_dollars`, `volume_fp`, `open_time`, `close_time`, `settlement_ts`,
  `market_type='binary'`, `strike_type`, `category`/series. Cursor-paginated.
- Price history (entry-price reconstruction) via the candlesticks endpoint
  (`/series/{series}/markets/{ticker}/candlesticks`) — confirmed in the Phase 0 spike
  (see `SPIKE_NOTES.md`).
- **Store:** one parquet row per resolved contract — identity, category, times, `result`,
  settlement, and the pre-committed **entry-price snapshot** (see §4), plus volume and
  bid/ask at entry.
- **No-look-ahead by construction:** a contract's entry features use only data with
  `ts < close_time`; the validator asserts this.
- **Phase 0 exit gate (all green before Phase 1):** (1) ≥ a pre-committed minimum count of
  resolved, volume-bearing contracts; (2) resolution integrity (`result` ∈ {yes,no},
  settlement consistent) ≥ 99.9%; (3) entry-snapshot timestamp strictly precedes close on
  100% of rows; (4) category coverage reported. File `PREDICTION_PHASE0_CERTIFIED.md` with
  this document's SHA-256.

## 3. Substrate Window

Kalshi meaningful-volume history (≈ 2022 → present; confirmed in Phase 0). Split **by
calendar time at the midpoint**: first half = IS/design, second half = OOS/validation. A
contract is assigned to a half by its `close_time`. Calibration, edge, and direction are
computed independently in each half; gates check BOTH.

## 4. Pre-Committed Trial Set (frozen)

- **Entry price** (frozen definition): the contract's last trade price at a fixed lead of
  **1 hour before `close_time`** (fallback: last available pre-close trade). Implied
  probability = entry price in dollars. There is exactly one entry definition; varying it is
  peeking.
- **Price buckets (7):** (0,5], (5,15], (15,35], (35,65], (65,85], (85,95], (95,100) cents.
- **Categories (pre-committed grouping):** {crypto-short-horizon, sports, economics, weather,
  politics/other}. Categories with fewer than the MDE-implied minimum resolved contracts
  (§5) are reported as UNDERPOWERED, not pass/fail.
- **Trial count for deflation:** the directional FLB test is evaluated per (extreme-bucket ×
  category) cell. `N_trials` = the number of evaluated cells (pooled + per-category). The
  exact count is fixed by the bucket × category grid above and recorded by the orchestrator
  before any statistic is read.

Banned from Phase 1 (peeking): re-bucketing after seeing results; alternative entry-lead
times; per-market discretionary selection; any category or rule not enumerated here.

## 5. Pass Criteria — Calibration Gates (all must pass)

Computed via `afgauntlet/binary.py`. Run the **power analysis first**: `binary_mde` reports
the minimum resolved-event count per bucket to detect the edge; any cell below it is
UNDERPOWERED and cannot pass (the small-N wall that killed PEAD is the central risk here).

| Gate | Criterion |
|---|---|
| **G1 — Calibration gap** | Longshot region (entry ≤ 15c): realized YES freq < implied by ≥ the pre-committed magnitude. Favorite region (entry ≥ 85c): realized > implied. Required in BOTH IS and OOS halves. |
| **G2 — Direction consistency** | Sign of the calibration gap agrees across the two halves. |
| **G3 — Edge CI** | Per-bucket (realized − implied) edge bootstrap CI excludes zero in the FLB direction (events independent → iid bootstrap). |
| **G4 — Net-of-fee survival** | The tradeable edge survives the honest Kalshi fee + bid/ask spread model (§6), and a doubled-fee stress. **This is the make-or-break gate** — the FLB gross edge is small and price-dependent fees can exceed it. |
| **G-deflation** | The edge is deflated across `N_trials` (Bonferroni/DSR-analog). |

## 6. Cost Model

- **Kalshi trading fee:** the price-dependent schedule confirmed in the Phase 0 spike
  (general form ≈ `ceil(0.07 × C × P × (1−P))` dollars per fill, with some series at a
  lower rate; maker treatment per current rules). **Exact current schedule frozen from the
  spike into this section's ADDENDUM before Phase 1.**
- **Spread:** entry and exit cross the bid/ask; modeled from recorded `yes_bid/ask` at entry.
- **G4 stress:** double the fee schedule (house pattern), edge must remain positive.

## 7. Confounds & Controls

- **Volume/liquidity filter:** only contracts with `volume_fp` > 0 at entry enter the study;
  the threshold is pre-committed in Phase 0.
- **Category mix drift:** report per-category so a pooled result is not an artifact of one
  category dominating one half.
- **Resolution/look-ahead:** entry strictly precedes close; settlement from `result` only.
- **Adverse selection note:** a mispriced-looking contract may reflect information we lack;
  the bucket-level (not contract-level) test is the control — FLB is a population property.

## 8. Phase 1 — Calibration Study

`signals/flb.py` (trial enumeration) + `research/run_phase1.py` (SHA-anchored via
`afgauntlet.PreRegistration`; refuses to run on hash/trial-count mismatch). Output: IS and
OOS reliability curves, per-bucket net edge, per-cell gate verdicts, the MDE table, and
`PHASE1_VERDICT.md`. Tables first, prose after.

## 9. Phase 2 — Forward Paper-Trade Record (delivers the goal)

Conditional on ≥1 Phase 1 survivor cell. `signals/strategy.py` (rule derived
deterministically from survivors; frozen) + `research/paper_trader.py` places paper orders
on live Kalshi markets matching the rule, logs entry price + implied prob, reconciles at
resolution, and tracks **live** realized edge + Brier/log-loss vs the market over a
pre-committed event count. **Success = realized-edge CI excludes zero AND calibration beats
market-implied over the pre-committed N resolved events.**

## 10. Phase 3 — Small Real Capital (conditional, user-run)

Only if the Phase 2 forward record clears. Tiny size. This is the credible live record — the
substrate's actual deliverable.

## 11. Decision Matrix

| Outcome | Verdict | Next |
|---|---|---|
| G1–G3 pass, powered, G4 pass | **PROCEED to Phase 2** | forward paper record |
| G1–G3 pass, powered, G4 fail | **REAL BUT NOT RETAIL-EXTRACTABLE** | document; no Phase 2 |
| Any key cell UNDERPOWERED | **INCONCLUSIVE** | forward-only data accumulation |
| No FLB-direction gap | **CLOSED FAILED** | tenth credible negative; founder-track decision |

## 12. Timeline

Phase 0 + design freeze: 1 session. afgauntlet `binary.py`: 1 session. Phase 1: 1 session.
Phase 2: wall-clock (user-run forward window). Phase 0/1 are not gated on the live wait.

## 13. Honest Limitations (pre-committed)

- FLB may be weak/absent outside sports → Phase 1 may CLOSE FAILED. Fine.
- **Small-N power is the central risk** — hence `binary_mde` runs up front, not after.
- Kalshi fees are price-dependent and can exceed the gross FLB edge — G4 is make-or-break.
- Kalshi's volume concentrates in short-horizon crypto/sports MVE markets; their FLB
  behaviour may differ from classic event markets and is reported separately.
- Capacity caps dollars; this is a skill/record project by design.
- Resolution/counterparty/regulatory risk is lower on Kalshi than offshore venues but nonzero.

## 14. Hard Rules

1. Do not edit this document after the first Phase 1 calibration statistic is computed.
2. Do not look at the OOS half until the IS half is fully written up.
3. Do not add buckets, categories, or entry-lead variants after starting.
4. Do not lower a gate threshold to fit the data. A failed FLB is row-1 (strategy class), not
   a tuning opportunity.
5. The fee model is frozen from the Phase 0 spike; no post-hoc fee reductions.

## 15. SHA-256 Anchor

This document's SHA-256 is computed at Phase 0 certification and recorded in
`PREDICTION_PHASE0_CERTIFIED.md`. The Phase 1 and Phase 2 orchestrators recompute it at
runtime (via `afgauntlet.PreRegistration`) and refuse to execute on mismatch. Any edit
invalidates the anchor and requires a fresh contract.

- **Author:** Atharva Patil
- **Drafted:** 2026-06-16 (pre-Phase-0-certification, pre-Phase-1-execution)

---

## 16. ADDENDUM — Phase 0 Data-Source Discovery (2026-06-16)

Filed after the Phase 0 spike + initial pull, BEFORE any Phase 1 calibration statistic.
Re-scopes §2/§3 to the data actually available on the free read-only Kalshi host. Does NOT
change the hypothesis (§1), the gates (§5), the cost model intent (§6), or the decision
matrix (§11). **Direction-of-effect: every change makes Phase 1 HARDER** (smaller N,
narrower categories), consistent with §13. Evidence: `research/SPIKE_NOTES.md`.

Findings:
1. The free `GET /markets?status=settled` feed is most-recent-first and saturated by
   sub-minute crypto/sports "MVE" markets; a 30k-market cursor walk recedes only ~4.5 hours
   of wall-clock — **pure pagination cannot reach 2022**.
2. Date-windowed pulls reach ~2023-06-22, but pre-≈2025 settled markets carry `volume_fp=0`
   on this host. The usable resolved + volume universe is **recent and MVE-heavy**; the
   first certified pull was **292 volume-bearing contracts, all category "Exotics."**
3. **Fee schedule CONFIRMED** (Kalshi Feb-2026 schedule): `ceil(0.07 × C × P × (1−P))`
   general taker; half for S&P/Nasdaq series; maker 25%. §6 is frozen to this (taker).

Re-scope:
- **§3 substrate window:** the clean multi-year, multi-category panel is NOT freely
  available. Phase 1 runs on the available recent universe and is **EXPECTED to be
  UNDERPOWERED and category-narrow** → per §11 the likely verdict is **INCONCLUSIVE**, with
  **Phase 2 forward accumulation as the PRIMARY path** (which suits the live-track-record
  goal anyway). `binary_mde` is run first and reports the floor against the available N.
- A clean historical panel (category breadth, classic non-MVE event markets) requires a
  richer/authenticated Kalshi source — **out of scope for the free-data substrate**; flagged
  for the founder decision.
- The MVE sub-minute crypto/sports category is structurally unlike classic FLB markets
  (recreational lottery preference); its results are reported **separately**, never pooled
  with non-MVE data.

The new SHA-256 anchor (post-ADDENDUM) is recorded in `PREDICTION_PHASE0_CERTIFIED.md` and
supersedes the pre-ADDENDUM value `796d6617...`.
