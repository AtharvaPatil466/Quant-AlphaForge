# PEAD — Post-Earnings Announcement Drift (Pre-Committed Design)

**Status:** PRE-COMMITMENT. Written 2026-05-17. No code in `alphaforge-pead/` has been run against EDGAR data; no SUE has been computed.

**This document is the contract.** It defines, before any data has been pulled, the substrate window, the signal definition, the trial set, the deflation hurdle, and the decision matrix. **No edit to this document is permitted after the first SUE is computed.** Edits would constitute peeking — the discipline that produced four credible negative verdicts (equity Tier 1, Tier 2, crypto carry, and the methodology-bug fix on 2026-05-02) requires this contract stay frozen.

Pairs with `alphaforge-pead/CLAUDE.md` (sub-project context) and the top-level `CLAUDE.md` (substrate landscape).

---

## 0. Context — Why PEAD, Why Now

PEAD is the **fifth substrate attempt** in this project. The first four:

| # | Substrate | Verdict | Date |
|---|---|---|---|
| 1 | Equity cross-sectional factor combinations (Tier 1, 21d rebalance) | CLOSED FAILED | 2026-05-02 |
| 2 | Equity Tier 2 lower-turnover variants (63d / 126d) | CLOSED FAILED | 2026-05-02 |
| 3 | Crypto USDT-M funding-rate carry | CLOSED FAILED | 2026-05-15 |
| 4 | Microstructure (BTC-USDT L2 + tape) | IN PROGRESS (Phase 0 — book-data accumulation) | 2026-05-17 → +30d |

Microstructure Phase 0 requires 30 days of book-data wall-clock. PEAD is **parallel substrate work** during that wait: net-new strategy class, different return horizon (60-day post-announcement drift), different data source (EDGAR XBRL), different failure modes.

PEAD is NOT a replacement for microstructure. When the microstructure 30-day book-data clock closes, microstructure Phase 1 has priority. If PEAD finishes first with a credible result, both substrates report verdicts; the founder makes the deploy decision.

PEAD is **not** a reopening of the frozen equity factor stack. It is read-only consumption of the existing PIT universe + OHLCV substrate plus a new EDGAR-XBRL data layer. The frozen modules (`alphaforge-python/factors/`, `-marl/`, `-execution/`) stay frozen.

---

## 1. The Signal — SUE (Standardized Unexpected Earnings)

Classic Bernard & Thomas (1989) formulation, seasonal random walk variant (no analyst data):

$$
SUE_{i,q} = \frac{EPS_{i,q} - EPS_{i,q-4}}{\sigma\left(\{EPS_{i,k} - EPS_{i,k-4}\}_{k=q-7}^{q-1}\right)}
$$

Where:
- `i` = firm
- `q` = fiscal quarter (announcement event)
- `EPS_{i,q}` = Diluted EPS from continuing operations for firm `i` in fiscal quarter `q`, as known on the announcement filing date
- `EPS_{i,q-4}` = the same fiscal-quarter identifier (`fp`) one fiscal year prior
- Denominator: rolling 8-quarter standard deviation of the firm's own seasonal earnings differences, ending at `q-1` (no look-ahead).

**Event time** for firm-quarter `(i, q)` = the `filed` timestamp from the SEC Company Facts API for the 10-Q (or 10-K for `fp="FY"`) reporting that period.

**Portfolio formation:** at each calendar trading day `t`, identify all firms whose latest announcement filed in the prior `K` trading days (where `K` is the holding-period parameter — see trial set §3). Rank these by SUE. Long top quintile (or decile), short bottom quintile (or decile), equal-weighted within bucket, rebalanced daily as the event window slides.

**Returns:** computed at close-to-close, net of the standard equity Tier 1 / Tier 2 cost model (1bp commission + 2bp half-spread + 10bp/turnover linear impact). **Cost-sensitivity stress** at the Tier 2 cost-doubling level (2bp comm + 4bp half-spread + 20bp impact) is part of the Phase 2 gate, not Phase 1.

---

## 2. The Four Engineering Pre-Commitments

These were drafted and discussed on 2026-05-17 before any extractor code existed. They are frozen here for audit.

### 2.1 Restatements (as-of-date discipline)

For a signal computed at time `t`, only values with `filed ≤ t` are visible.

The EDGAR Company Facts API exposes, for each numeric concept value, the tuple `(val, accn, fy, fp, start, end, filed, form)`. The extractor stores per `(ticker, period_end)` a chronologically ordered list of `(filed, val, form)` tuples. Query function: `value_as_of(ticker, period_end, as_of_ts) -> Optional[float]` returns the latest `val` whose `filed ≤ as_of_ts`. A restated Q2 reported in November returns the original July value before November, the amended value from November onward.

10-Q/A (amendment) forms are treated identically to 10-Q for ordering purposes — the `filed` timestamp is the only discriminator. The original 10-Q value remains visible for the time window `[original_filed, amendment_filed)`.

### 2.2 Fiscal period alignment

Keyed by `(ticker, fy, fp)` where `fp ∈ {"Q1", "Q2", "Q3", "FY"}`. SUE compares `(fy, fp)` to `(fy-1, fp)`. Each firm's "same quarter" is its own fiscal `fp`. Apple's December-ending Q1 is compared to Apple's previous December-ending Q1, not to a calendar Q1.

Event time = the `filed` date of the 10-Q (Q1/Q2/Q3) or 10-K (FY) reporting that period, never the period-end date.

**53-week fiscal years (retailers):** when a firm's `fp="FY"` row has `start` to `end` spanning 53 weeks instead of 52, the firm-year is flagged but NOT dropped — the SUE denominator handles the resulting earnings-size noise statistically, and dropping rows would create a non-stationary survivorship pattern.

> **§2.2 ADDENDUM (2026-05-17, discovered during Phase 0 validation against live EDGAR data — NOT a contract revision, a correction of an assumption that proved wrong on first contact with the data):**
>
> EDGAR Company Facts API's `fp` field reflects the **filing form's fiscal period**, NOT the value's period. A 10-K filing for FY 2012 returns every quarterly value reported in that filing tagged with `fp=FY` (the FY of the filing form). The API also returns cumulative year-to-date values (e.g., a "Q2" value with `start=Jan 1, end=Jun 30, duration=180d` representing H1 cumulative) alongside the true single-quarter values (`duration=90d`).
>
> The canonical period identifier is therefore the **(period_end date, period_kind)** tuple where `period_kind` is derived from `(end_date - start_date).days`:
> - duration ∈ [85, 95]: `quarterly` ← the SUE-eligible substrate
> - duration ∈ [175, 190]: `ytd_q2`  ← cumulative, excluded
> - duration ∈ [265, 280]: `ytd_q3`  ← cumulative, excluded
> - duration ∈ [355, 380]: `annual`  ← FY-only, excluded for quarterly SUE
> - otherwise: `other`
>
> SUE computation operates on `dict[period_end, eps_val]` indexed by `period_end`. "Same quarter year ago" is looked up by date arithmetic: the unique period_end `P'` such that `(P - P') ∈ [350, 380]` days. Apple's September-fiscal-Q1 still works correctly because its period_end is a December date and the seasonal predecessor is the prior December.
>
> `fp` and `fy` are retained in the parquet schema for audit/reporting only. They are NOT join keys.
>
> Implementation: `gauntlet.sue.compute_sue(eps_by_period_end, focal_period_end)`, `gauntlet.panel.build_panel_for_firm` (filters to `period_kind == "quarterly"`), and `extractors.companyfacts.value_as_of(..., period_kind="quarterly")` enforce this collectively.
>
> This addendum does not relax any pre-committed gate. The Phase 1 trial set (§3.1), the gauntlet (§4), and the OOS protocol (§5) are unchanged. Only the *implementation key* changed — from a wrong assumption about `fp` semantics to the correct (period_end, period_kind) tuple.

### 2.3 EPS concept hierarchy

Locked here, never tuned. For each firm-quarter:

1. `us-gaap:IncomeLossFromContinuingOperationsPerDilutedShare` (primary).
2. Fallback → `us-gaap:EarningsPerShareDiluted`.
3. Fallback → drop the firm-quarter.

**No substitution to `EarningsPerShareBasic` is permitted** — basic and diluted are different metrics and silent substitution is a contract violation. Every step-2 substitution is logged with the `(ticker, fy, fp)` tuple. Substitution rate is reported in the verdict document. **Do not look at how many firm-quarters each hierarchy step rescues before locking it.**

### 2.4 Eligibility filter (missing-data handling)

- **Substrate window:** 2012-01-01 to 2026-05-17. Pre-2012 XBRL coverage is structurally incomplete (the XBRL mandate phased in 2009–2011); restricting to 2012-onward gives a clean substrate.
- **Per-firm minimum:** 8 quarters of clean Diluted-continuing EPS history before that firm is eligible for SUE computation. Below 8 quarters the SUE denominator (rolling 8-quarter σ) is structurally noisy.
- **Universe intersection:** PIT membership (`alphaforge-python/data/market/pit/`) × XBRL availability × OHLCV coverage (`data/quarantine/market/`). Firm-quarters that fail any of the three are reported as data gaps in every metric, same discipline as the existing "226 of 881 ever-members have no OHLCV" disclosure.

---

## 3. The Trial Set (frozen)

### 3.1 Phase 1a — Standalone PEAD configurations (10 trials)

| Parameter | Values | Count |
|---|---|---|
| **Holding horizon `K`** (trading days post-announcement) | 5, 21, 42, 63, 84 | 5 |
| **Bucket cut** | quintile (top 20% / bottom 20%) / decile (top 10% / bottom 10%) | 2 |
| **SUE expectation model** | seasonal random walk (SRW) only — no I/B/E/S data available | 1 |

Total Phase 1a trials = `5 × 2 × 1 = 10`.

Rationale for not including I/B/E/S consensus: it's paid data ($10k+/year minimum); the cooldown design prohibits paid data. SRW is the original Bernard-Thomas (1989) formulation and produces a weaker but legitimate version of the signal. The fact that institutional PEAD desks use consensus is a real disadvantage and is disclosed in §7.

### 3.2 Phase 1b — Conditional neutralization (20 trials)

Phase 1b only runs if Phase 1a produces ≥1 SURVIVOR. Mirror discipline to microstructure Phase 1b: spread-filter triggered only if base survives.

| Variant | Trials |
|---|---|
| Sector-neutral SUE (residualize SUE on GICS sector dummies at announcement time) | 10 |
| Size-neutral SUE (residualize on log market cap quintile dummies) | 10 |

Total Phase 1b trials = 20.

If Phase 1a closes FAILED, Phase 1b is NOT triggered and its 20 trials do not count in any deflation calculation.

### 3.3 What is NOT in the trial set (banned)

- Analyst-consensus SUE. Paid data; not in budget.
- Earnings-day return predictors (drift requires *post*-announcement returns, not announcement-day).
- Accruals / cash-flow signals (Sloan 1996). Different signal class, would require its own design doc.
- Combinations of PEAD with other factors (size, value, momentum). Phase 2 work, not Phase 1.
- Tuning `K` or the cut after seeing results.

---

## 4. The Gauntlet (Pass Criteria)

Same methodology as equity Tier 1, applied to the PEAD substrate. A configuration passes Phase 1 if and only if **all three** hold:

| Gate | Threshold | Source |
|---|---|---|
| **G1 — Deflated Sharpe** | DSR > 0.95 on alpha-residual OOS returns in BOTH windows | Bailey & López de Prado 2014; same as Tier 1 |
| **G2 — Bootstrap CI** | Stationary-bootstrap 95% CI excludes zero in BOTH OOS windows | Politis & Romano 1994; 4,000 reps, 21d mean block |
| **G3 — Sign agreement** | OOS-A and OOS-B Sharpes have the same sign | Same as Tier 1 |

Alpha-residual = the post-portfolio time-series regression of each strategy's daily returns on the FF5+UMD reference factors, using `alphaforge-python/research/risk_model.py`. HC0 SEs on the alpha intercept. **This is the post-fix residualization layer the 2026-05-02 bug fix established** — the same residualization that found MV-21 to be alpha-significant but DSR-fail.

DSR deflation is against the full pre-committed trial count (10 for Phase 1a, or 30 if Phase 1b triggers).

---

## 5. OOS Protocol

Substrate: 2012-01-01 to 2026-05-17 (~14.4 years).

| Window | Range | Role |
|---|---|---|
| Training / IS | 2012-01-01 → 2020-12-31 | Signal definition only. No threshold tuning. |
| OOS-A | 2021-01-01 → 2023-12-31 | First holdout. Gate evaluation. |
| OOS-B | 2024-01-01 → 2026-05-17 | Second holdout. Independent gate evaluation. |

**21-day embargo** at each window boundary, matching the equity gauntlet's `OOS_START=2024-01-02` discipline.

**No looking at OOS until IS is fully written up.** "Looking" includes Sharpe, bootstrap CI, sign — anything that produces a number from OOS data. The first OOS number computed is the final OOS number for that config.

---

## 6. Decision Matrix

| # Survivors (1a + conditional 1b) | Outcome | Next action |
|---|---|---|
| 0 in 1a, 1b not triggered | **CLOSED FAILED (substrate #5)** | File `PEAD_VERDICT.md` with negative result. PEAD takes its place in the failure-row matrix. |
| ≥1 in 1a | **PROCEED TO 1b** | Run 20 conditional sector/size-neutral trials. |
| ≥1 final survivor | **PROCEED TO PEAD PHASE 2** | Cost-sensitivity stress test (Tier 2 cost-doubling), capacity study, regime conditioning. Write `PEAD_PHASE2_DESIGN.md` first. |
| ≥5 final survivors | **STOP AND TRIAGE** | High pass rate on a deflated trial set is suspicious. Audit as-of date discipline, the seasonal random walk implementation, and the FF5+UMD residualization wiring before claiming the result. |

---

## 7. Honest Caveats (Carried From the Literature)

- **PEAD shrinkage.** The original Bernard-Thomas (1989) effect was ~5%/quarter; Chordia-Shivakumar (2006), Sadka (2006), and others document the magnitude declining over the 2000s. Pre-committed expectation: a 2012-onward substrate may show a smaller effect than the textbook. This is not grounds for adjusting the threshold downstream — it is grounds for accepting CLOSED FAILED if the threshold doesn't clear.
- **No analyst consensus.** SRW-based SUE is the original Bernard-Thomas formulation but is acknowledged in the literature to be a weaker signal than analyst-consensus SUE (Livnat-Mendenhall 2006). The PEAD literature post-2000 mostly uses consensus. Working without it is a known disadvantage of this implementation.
- **Substrate is the same one Tier 1 / Tier 2 failed on.** The PIT universe, the OHLCV store, the cost model — all the same. The cost-model underestimate documented in the Tier 2 verdict (parametric 2bp half-spread vs Corwin-Schultz median 7-8bp) applies here too. Phase 2 cost-doubling addresses it explicitly.
- **Survivorship in the EDGAR API.** The Company Facts API at `data.sec.gov/api/xbrl/companyfacts/CIK{}.json` returns the *current* CIK's full history. Companies that have been merged, dissolved, or deregistered may have incomplete API coverage. The PIT-universe intersection in §2.4 partially handles this but does not eliminate it.

---

## 8. Hard Rules (the Non-Negotiables)

1. **Do not edit this document after the first SUE is computed.**
2. **Do not look at OOS data until IS is fully written up.**
3. **Do not add trials to the trial set after starting.** New ideas → fresh design doc → fresh deflated trial count.
4. **Do not lower a threshold to fit the data.** If DSR > 0.95 fails, file CLOSED FAILED.
5. **Do not retroactively split the trial set into "real" and "exploratory" trials.**
6. **Do not substitute Basic EPS for Diluted EPS** under any circumstance.
7. **Do not run Phase 1b unless Phase 1a has ≥1 SURVIVOR.**

These rules failed exactly zero times across Tier 1, Tier 2, crypto carry, and (so far) microstructure Phase 0. They are why the project has four credible verdicts instead of four undeployed false positives.

---

## 9. Authorship and Pre-Commitment Anchor

- **Author:** Atharva Patil
- **Drafted:** 2026-05-17 (pre-extractor, pre-data-pull, pre-any-SUE)
- **Pre-commitment anchor:** this document's SHA-256 hash is to be included in `PEAD_PHASE0_CERTIFIED.md` when that document is filed (after the EDGAR extractor passes its own validation gate — see `alphaforge-pead/CLAUDE.md` for the Phase 0 criteria).

```bash
# After committing this file:
shasum -a 256 alphaforge-pead/research/PEAD_DESIGN.md
# Paste the hash into PEAD_PHASE0_CERTIFIED.md to anchor the contract.
```
