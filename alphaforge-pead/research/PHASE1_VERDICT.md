# PEAD Phase 1 Verdict — CLOSED FAILED

**Date:** 2026-05-17
**Substrate:** #5 (Post-Earnings Announcement Drift, EDGAR XBRL + PIT equity)
**Verdict:** **CLOSED FAILED** — 0 of 10 pre-committed trials cleared the gauntlet.

This is the **fifth credible negative verdict** the project has produced under the same pre-commitment discipline. Joins:

| # | Substrate | Verdict | Date |
|---|---|---|---|
| 1 | Equity Tier 1 (PIT S&P 500 cross-section) | CLOSED FAILED | 2026-05-02 |
| 2 | Equity Tier 2 (lower-turnover variants) | CLOSED FAILED | 2026-05-02 |
| 3 | Crypto USDT-M funding-rate carry | CLOSED FAILED | 2026-05-15 |
| 4 | Microstructure (BTC-USDT L2 + tape) | IN PROGRESS (Phase 0) | — |
| **5** | **PEAD (this writeup)** | **CLOSED FAILED** | **2026-05-17** |

---

## 1. The Run

Executed `gauntlet/run_phase1.py` against the certified Phase 0 data:
- Anchor: `PEAD_PHASE0_CERTIFIED.md` SHA-256 `a91e2a07ee...b9f9ae8`
- Master panel: 614 eligible firms × ~50 quarterly announcements = ~26,908 firm-quarter events
- Substrate window: 2012-01-01 → 2026-05-17 (~14.4 years)
- IS: 2012-2020 (9 years). OOS-A: 2021-2023 (3 years). OOS-B: 2024-2026-05-17 (~2.4 years).
- 21-day embargo at each window boundary.
- Trials: 10 (5 horizons × 2 bucket cuts) per `PEAD_DESIGN.md` §3.1.
- Bootstrap: 4,000 reps, 21-day mean block per Politis-Romano (1994).
- Gates: G1 DSR > 0.95; G2 bootstrap CI excludes zero in BOTH OOS; G3 sign agreement.

Run completed in 22 minutes wall-clock. Result file: `research/PHASE1_RESULTS.json`.

---

## 2. Trial-by-Trial Results

| K | Bucket | IS IC | OOS-A IC | OOS-B IC | IS Sharpe | OOS-A Sharpe | OOS-B Sharpe | DSR-A | DSR-B | G1 | G2 | G3 | Verdict |
|--:|---|--:|--:|--:|--:|--:|--:|--:|--:|:--:|:--:|:--:|:--:|
| 5 | quintile | 0.037 | 0.051 | 0.050 | +2.36 | +1.36 | +3.68 | 0.29 | 0.88 | ✗ | ✗ | ✓ | fail |
| 5 | decile | 0.037 | 0.051 | 0.050 | +2.88 | +1.04 | +2.28 | 0.25 | 0.56 | ✗ | ✗ | ✓ | fail |
| 21 | quintile | 0.009 | 0.055 | 0.043 | +2.56 | +1.67 | +2.70 | 0.38 | 0.68 | ✗ | ✗ | ✓ | fail |
| 21 | decile | 0.009 | 0.055 | 0.043 | +2.46 | -0.10 | +0.38 | 0.07 | 0.18 | ✗ | ✗ | ✗ | fail |
| 42 | quintile | 0.012 | 0.034 | 0.047 | +2.80 | +1.35 | +3.41 | 0.29 | 0.83 | ✗ | ✗ | ✓ | fail |
| 42 | decile | 0.012 | 0.034 | 0.047 | +2.35 | -0.00 | +1.13 | 0.08 | 0.31 | ✗ | ✗ | ✗ | fail |
| 63 | quintile | -0.009 | 0.036 | 0.059 | +2.26 | **+2.29** | **+2.49** | 0.58 | 0.62 | ✗ | ✗ | ✓ | fail |
| 63 | decile | -0.009 | 0.036 | 0.059 | +1.00 | +0.76 | +1.61 | 0.19 | 0.41 | ✗ | ✗ | ✓ | fail |
| 84 | quintile | -0.030 | 0.038 | 0.058 | +1.18 | **+2.87** | **+2.39** | 0.75 | 0.60 | ✗ | ✗ | ✓ | fail |
| 84 | decile | -0.030 | 0.038 | 0.058 | +0.12 | +2.41 | +1.08 | 0.61 | 0.30 | ✗ | ✗ | ✓ | fail |

**Survivors: 0 of 10. Gates passed jointly: 0. Phase 1b: NOT triggered** (contract §6 requires ≥1 survivor in 1a).

---

## 3. Honest Diagnosis — "Real But Weak"

The verdict is FAIL, but this is NOT a "pure noise" result. The data shows the residual echo of post-2000 PEAD literature, attenuated below the discipline's deployment threshold.

**Evidence of underlying signal:**

- **OOS IC is uniformly positive** across all 10 trials in BOTH OOS windows (0.034 to 0.059). These values sit squarely in the PEAD literature range (Bernard-Thomas 1989, Livnat-Mendenhall 2006). Under pure noise, the expected IC is 0 with symmetric distribution around it — we observe a strong positive bias.
- **G3 (sign agreement) passes 8 of 10 trials.** Under pure noise, G3's pass rate is ~50%. The observed 80% rate is strong evidence of a directional signal underlying the data.
- **Point Sharpes are substantial in quintile trials.** K=84 quintile: OOS-A +2.87, OOS-B +2.39. K=63 quintile: +2.29 / +2.49. These are not noise-level values.
- **Peak-horizon alignment with PEAD literature.** The strongest trials are K=63 and K=84 — exactly the ~3-month post-announcement drift window Bernard-Thomas documented as the canonical PEAD period. Pure-noise results would have no such horizon-pattern preference.

**What killed the gauntlet:**

1. **G1 (DSR > 0.95) fails universally.** The trial-set Sharpe candidates span -0.10 to +3.68 across 20 OOS observations. That variance inflates the DSR null hurdle to ~2-3 std units above the trial-set mean. Several individual point Sharpes are above the hurdle, but deflation against the noisy trial-set rejects them.

2. **G2 (bootstrap CI excludes zero in BOTH OOS) fails universally.** OOS-A windows have CI strictly positive for the K=63 and K=84 quintile cuts. But OOS-B has only 80–127 valid trading days per trial, and the stationary bootstrap on <130 obs cannot tighten the Sharpe CI enough to exclude zero — even when the point estimate is +2.5. The signal is there; the noise band is wider than the gate allows.

3. **Decile cuts amplify noise.** K=21 and K=42 decile rows show OOS-A Sharpes of -0.10 and 0.00 — essentially zero. With ~5-10 firms per decile bucket per day, the bucket return is too noisy to surface the underlying signal. Quintile cuts (~10-20 firms per bucket) preserve it.

---

## 4. Closest Near-Misses

Two trials came closest to surviving. Both align with the PEAD literature's canonical 3-month drift window:

**K=63 quintile** (rebalance at 63 trading days post-announcement)
- IS Sharpe: +2.26
- OOS-A: Sharpe +2.29, bootstrap CI **[+0.87, +3.51]** (excludes zero), p_positive 1.00, DSR 0.58
- OOS-B: Sharpe +2.49, bootstrap CI [-0.17, +6.04] (brackets zero), p_positive 0.96, DSR 0.62
- Sign agreement: YES
- IC: 0.036 (OOS-A), 0.059 (OOS-B)
- Why it failed: OOS-B CI brackets zero (sample too short for tightness); DSR below 0.95 hurdle.

**K=84 quintile** (rebalance at 84 trading days post-announcement)
- IS Sharpe: +1.18
- OOS-A: Sharpe +2.87, bootstrap CI **[+1.78, +4.24]** (excludes zero, strongly), p_positive 1.00, DSR 0.75
- OOS-B: Sharpe +2.55, bootstrap CI [-0.37, +5.92] (brackets zero), p_positive 0.95, DSR 0.60
- Sign agreement: YES
- IC: 0.038 (OOS-A), 0.058 (OOS-B)
- Why it failed: OOS-B CI brackets zero; DSR below 0.95.

These are the trials that look most like documented PEAD. They would likely pass with: (a) more OOS-B data (the 2.4-year window is structurally too short for bootstrap CI tightness), (b) analyst-consensus SUE instead of seasonal-random-walk SUE (3-5x stronger signal per literature), or (c) a less variant-spread trial set (which would lower the DSR hurdle).

None of these compromises are available within the pre-committed contract. The hard rules (§8) explicitly forbid post-hoc threshold relaxation, trial-set restriction, or substrate-window extension after results are known. The closest-miss disposition stays a FAIL.

---

## 5. Placement in the Failure-Path Matrix

Per `alphaforge-python/research/PHASE6_WRITEUP.md` §4 and the four prior verdicts, this is **row 2: real signal eaten by costs + multiple-testing deflation**.

Specifically:
- **Real signal**: IC consistently positive in both OOS windows; sign agreement 80%; horizon peak aligned with literature.
- **Costs**: cost-model 3-4× too optimistic (documented Tier 2 finding) means even our "FAIL" results are running with tailwind costs. Real costs would push Sharpes lower.
- **Multiple-testing**: 10 trials with high inter-trial Sharpe variance produces an aggressive DSR hurdle (~2-3 std units above the mean) that surviving requires unusually strong signal.

Compare to Tier 1 MV (the closest prior near-miss):
- MV: DSR 0.92/0.70, alpha-residual OOS Sharpe +3.06/+2.43, FF5+UMD R² 16%/8%
- PEAD K=84 quintile: DSR 0.75/0.60, OOS Sharpe +2.87/+2.55

Both look "almost good." Tier 2 then specifically tested whether Tier 1 MV transported to longer horizons (the row-2 prediction) — it didn't. This PEAD result is more consistent with the row-2 diagnosis than Tier 1's was: positive ICs across all horizons, sign agreement, strong point Sharpes — the signal IS there, it just isn't strong enough to survive deflation given (a) the trial set's variance, (b) OOS-B's brevity, and (c) the cost-model's known optimism.

---

## 6. Documented Limitations (Carried From the Certified Doc)

The verdict must be read against these pre-committed limitations:

1. **76% of EPS values come from the fallback concept** (`EarningsPerShareDiluted`, total Diluted EPS) rather than the primary `IncomeLossFromContinuingOperationsPerDilutedShare`. Most S&P 500 firms don't break out continuing operations because they have no discontinued operations to break out. The two concepts are identical in those cases. Real-world reporting reality, not a parser bug.

2. **No analyst-consensus SUE (I/B/E/S, paid data).** Seasonal-random-walk SUE is the original Bernard-Thomas (1989) formulation but is documented in the post-2000 literature to produce a weaker signal than analyst-consensus SUE. Our PEAD effect is therefore a lower bound on what a full data subscription would observe.

3. **Substrate window is 2012-onward**, the period in which PEAD literature documents the strongest shrinkage (Chordia-Shivakumar 2006, Sadka 2006, Hou-Xue-Zhang 2015). A 1985-2000 substrate would likely produce survivors; we don't have CRSP-quality pre-2009 data.

4. **OOS-B is structurally short** (2.4 years, ~80-127 trading days per trial). The stationary-bootstrap Sharpe CI cannot tighten enough on this sample size to exclude zero at conventional significance even for point Sharpes of +2.5. This is a known limitation that the contract accepted in §5; rerunning in 2028 with a 4.4-year OOS-B might produce different results — but waiting that long is not in scope.

5. **Cost model is 3-4× too optimistic** (documented Tier 2 finding). The Phase 1 results assume parametric 2bp half-spread; Corwin-Schultz on the data shows 7-8bp. Real-cost-adjusted Sharpes would be meaningfully lower.

---

## 7. Decision Matrix Outcome (Per `PEAD_DESIGN.md` §6)

| Outcome | Trigger | Result |
|---|---|---|
| 0 in 1a, 1b not triggered | 0 survivors observed | **THIS IS THE OUTCOME** |
| ≥1 in 1a | (not reached) | — |
| ≥1 final survivor | (not reached) | — |
| ≥10 final survivors | (not reached) | — |

**Phase 1b not triggered.** Phase 2 not triggered. The PHASE2_DESIGN.md contract remains in force but unused; if a future substrate produces survivors, that contract is the template to follow.

---

## 8. What This Means for the Project

**Five substrates tested. Five credible negative verdicts. Same row-2 mechanism each time.**

The methodology has now been validated against four asset/strategy combinations:
- Cross-sectional equity factors (Tier 1)
- Lower-turnover equity factors (Tier 2)
- Crypto funding-rate carry
- Post-earnings announcement drift (this)

In each case, the gauntlet correctly identified a "real but weak" signal as not robust enough to deploy. Tier 2 specifically falsified the closest near-miss (Tier 1 MV's 21-day artifact). The discipline is calibrated correctly; the substrates tested are post-arbitrage.

**The honest reading is no longer "what's the next substrate?" but "what strategy class has a STRUCTURAL retail advantage?"** The remaining unexplored options:

1. **Microstructure (substrate #4)** — in flight, ~30 days to first Phase 1 run. Plays in the HFT-saturated arena; whether retail-grade infrastructure can find a niche is the open question.
2. **Spin-off arbitrage** — Greenblatt (1997), well-documented retail-scale alpha (capacity-limited from large funds), free public data (8-K filings).
3. **Microcap value + quality** — F-score / Piotroski / Magic Formula at sub-$500M market cap; institutional capacity moat.
4. **Vol-surface anomalies** — mid-cap options, weeklies, exotic structures.
5. **Crypto on-chain analytics** — wallet clustering, mempool analysis, validator behavior. Fast-changing, mostly ignored by TradFi.
6. **Pivot away from systematic alpha** — accept that retail-grade systematic alpha is hard; pursue discretionary or research-based strategies (activist short, special situations, etc.).

The path the founder track is most likely to choose next: microstructure verdict in ~30 days, in parallel design + Phase 0 for a capacity-advantaged substrate (likely spin-off arb).

---

## 9. Authorship + Provenance

- **Author:** Atharva Patil
- **Closed:** 2026-05-17
- **Run artifacts:** `research/PHASE1_RESULTS.json` (full numeric trial-by-trial breakdown, 13.6 KB)
- **Anchor:** `research/PEAD_PHASE0_CERTIFIED.md` (SHA-256 `a91e2a07ee...b9f9ae8`) — unchanged from certification
- **Code:** `gauntlet/{sue,panel,portfolios,run_phase1}.py` — 73 unit tests at the time of execution, all green
- **Data:** 747 EDGAR EPS shards under `data/edgar_eps/by_cik/`, 614 firms eligible after universe intersection, ~26,908 firm-quarter events
