# AlphaForge India — Pre-Committed Design

**Status:** PRE-COMMITMENT. Written 2026-05-18. No bhavcopy data has been downloaded beyond the 30-date spike test (`/tmp/nse_spike/results.json`). No signal has been computed. No backtest has been run.

**This document is the contract.** It defines, before any data infrastructure code is run at scale, the substrate window, the signal definitions, the trial set, the deflation hurdle, the cost model, and the decision matrix. **No edit to this document is permitted after Phase 1 begins.** Edits after Phase 1 starts would constitute peeking — the discipline that produced five credible negative verdicts (equity Tier 1, Tier 2, crypto carry, methodology-bug retest, PEAD) requires this contract stay frozen.

Pairs with `alphaforge-india/CLAUDE.md` (sub-project context) and the top-level `CLAUDE.md` (substrate landscape).

---

## 0. Context — Why India, Why Now

India is the **sixth substrate attempt** in this project. The first five:

| # | Substrate | Verdict | Date | Diagnosis |
|---|---|---|---|---|
| 1 | Equity cross-sectional factor combinations (Tier 1, 21d rebalance) | CLOSED FAILED | 2026-05-02 | Row 2 — real signal eaten by costs + multiple-testing |
| 2 | Equity Tier 2 lower-turnover variants (63d / 126d) | CLOSED FAILED | 2026-05-02 | Same substrate, different parameters — clean fail |
| 3 | Crypto USDT-M funding-rate carry | CLOSED FAILED | 2026-05-15 | Same row 2 — signal IC=0.5 but costs+DSR win |
| 4 | Microstructure (BTC-USDT L2 + tape) | IN PROGRESS — Phase 0 book-data accumulation | 2026-05-17 → +30d | — |
| 5 | PEAD (post-earnings drift, EDGAR XBRL) | CLOSED FAILED | 2026-05-17 | Same row 2 — "real but weak"; 0/10 trials cleared |

**Same diagnostic each time: row 2 of the failure-path matrix.** Real signal, eaten by honest costs and multiple-testing deflation. The methodology is calibrated correctly — it is correctly identifying real-but-weak signals as not robust enough to deploy, the same way it would correctly identify a real-and-strong signal as deployable if one existed in the data tested.

**The honest read is no longer "what substrate?" — it's "what strategy class?"** Five cross-sectional rank-based signals on US-equity-like data have failed under the same gauntlet. The remaining unexplored options are different *classes*, not different *substrates*: capacity-limited strategies where institutional funds structurally cannot compete because of size constraints, or geographic markets where global quant fund competition is structurally thinner.

This substrate explicitly chooses the **second option**: NSE equities, with signals (delivery percentage anomaly, FII/DII flow imbalance, F&O expiry effect) that are India-specific. The data is genuinely retail-accessible in a way that US data is not — bhavcopy publishes delivery percentages daily for every listed stock, SEBI mandates FII/DII flow disclosure, and the F&O expiry mechanism is institutionally distinct from US-market expiration. **The strategy class is event-driven and flow-based, not cross-sectional rank-based** — that distinction is load-bearing. Every prior substrate failed as a cross-sectional rank study. This substrate avoids that class.

India is **parallel substrate work** alongside microstructure (#4): different data, different signals, different return horizons. Spike test on 2026-05-18 (`/tmp/nse_spike/results.json`) cleared the four data-access hypotheses (H1-H4). Phase 0 infrastructure is unblocked.

India is **not** a reopening of the frozen equity factor stack. It is a net-new sub-project with its own data, its own signals, and its own pre-commit gauntlet. The frozen modules (`alphaforge-python/factors/`, `-marl/`, `-execution/`) stay frozen.

When microstructure's 30-day book-data clock closes (≈ 2026-06-17), microstructure Phase 1 takes priority. If India finishes Phase 0 / Phase 1 first with a credible result, both substrates report verdicts; the founder makes the deploy decision.

---

## 1. The Hypothesis

Three pre-committed signal candidates. All three are documented in academic Indian-market literature. All three exploit data structures that do not exist in US equity datasets. None of the three is a cross-sectional rank study of the kind that has now failed five times.

### 1.1 Delivery Percentage Anomaly — Primary

NSE publishes daily *delivery percentage* for every listed equity: the fraction of the day's traded volume that resulted in physical settlement (vs intraday position-squaring). High delivery percentage indicates conviction-based accumulation (investors taking physical possession of shares with intent to hold). Low delivery percentage indicates speculative position-taking (intraday turnover with no settlement).

**Signal:** for each stock on each day, compute the z-score of delivery percentage against the stock's own trailing 20-day mean and std. Long signal = unusually high delivery percentage (conviction accumulation). Short signal = unusually low delivery percentage (speculative distribution).

**Why this is not a cross-sectional rank study in disguise:** the signal is normalized against each stock's own history, not against the cross-section. A stock with structurally high delivery percentage (e.g. low-float, illiquid name) does not dominate the signal; only the *deviation* from its own baseline does. This is a within-stock event signal that happens to be aggregated cross-sectionally for portfolio formation.

### 1.2 [CANCELLED / DROPPED] FII/DII Flow Imbalance — Secondary

This signal family has been dropped from the substrate design. See 2026-05-19 ADDENDUM.

### 1.3 F&O Expiry Effect — Tertiary

NSE futures and options expire on the last Thursday of each month (Wednesday on Thursday-holiday weeks). In the 1-5 trading days before expiry, derivative position-unwinding pressure has been documented to push high-OI underlyings down; in the 1-5 days after expiry, mean reversion has been documented as the unwound positions reverse.

**Signal:** event-driven, triggered by proximity to expiry date. For each stock with significant futures open interest (above its own 50th-percentile of OI over the prior 252 days), enter positions in the pre-expiry window, exit in the post-expiry window.

**Sample size note:** ~12 expiry events per year × 22 years ≈ 264 events. This is adequate but small. Bootstrap CIs on this signal will be structurally wider than on the daily-observation signals. Pre-committed Gate 2 must be satisfied on this smaller event sample.

---

## 2. Phase 0 — Universe Construction and Data Infrastructure

**Objective:** Build the Indian equivalent of the PIT S&P 500 membership log and validate the full historical dataset before a single line of signal code runs. Nothing in Phase 1 is unblocked until all six Phase 0 exit criteria below are met.

### 2.1 Nifty 500 PIT Universe

NSE publishes historical Nifty 500 index composition via:
- The NSE India website index archive (point-in-time constituent lists)
- The NSE circular archive (every index reconstitution announced with an effective date)
- `jugaad-trader` / `nsepy` for programmatic access to recent composition

**Construction discipline:**

- Every addition and removal is recorded with its **effective date** — the date the change took effect in the index, NOT the announcement date.
- Announcement date and effective date differ. A circular published Monday may say "effective from next Friday." A stock can only enter the eligible universe from the effective date.
- Stored as a chronological event log mirroring the equity PIT structure (`alphaforge-python/data/market/pit/_event_log.parquet`, 837 events).
- Validate the reconstructed universe by computing the Nifty 500 TR index return from the PIT membership log and comparing against NSE's officially published Nifty 500 TR index return.

**Validation threshold:** reconstructed-return correlation with official Nifty 500 TR ≥ 0.98 over the IS window (2004-2014).

**What happens if the 0.98 threshold is missed:** if correlation lands at 0.95 ≤ ρ < 0.98, the universe construction is partial-pass and **must be revisited** before Phase 0 closes — typical cause is missed corporate-action handling, dividend re-investment differences, or a small number of missing constituent change events. Document the gap, fix the construction, re-validate. If correlation < 0.95, Phase 0 is blocked and the substrate stalls until the universe layer is rebuilt. **No silent acceptance of a sub-0.98 correlation.**

### 2.2 Bhavcopy — Two-Era Loader Architecture (Spike Test Finding 1)

**Discovered 2026-05-18 via spike test, frozen here as engineering pre-commit:**

NSE published bhavcopy data in two structurally different formats over the 22-year history. The loader must handle both.

**Pre-2020 era (2004-01-01 → ~2020-01-31):**
- Source A: **legacy bhavcopy CSV** (zipped) at `archives.nseindia.com/content/historical/EQUITIES/{YYYY}/{MMM}/cm{DDMMMYYYY}bhav.csv.zip`. Columns: `SYMBOL, SERIES, OPEN, HIGH, LOW, CLOSE, LAST, PREVCLOSE, TOTTRDQTY, TOTTRDVAL, TIMESTAMP`. No delivery percentage, no ISIN.
- Source B: **MTO `.DAT`** at `archives.nseindia.com/archives/equities/mto/MTO_{DDMMYYYY}.DAT`. Semi-structured. Lines have `record_type, sr_no, symbol, series, qty_traded, deliv_qty, deliv_per`. Confirmed back to 2004-04-05 in spike test.
- Pre-2020 ingestion is a **JOIN** of A and B on `(date, SYMBOL, SERIES)`.

**Post-2020 era (~2020-02-01 → present):**
- Single source: **unified `sec_bhavdata_full_*.csv`** at `archives.nseindia.com/products/content/sec_bhavdata_full_{DDMMYYYY}.csv`. Columns: `SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, LAST_PRICE, CLOSE_PRICE, AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER`. No ISIN.
- Post-2020 ingestion is a single-source read.

**Mandatory cross-check, pre-2020 only:** for each date with both legacy bhavcopy AND MTO present, the join must verify `bhavcopy.TOTTRDQTY == mto.QUANTITY_TRADED` for every `(SYMBOL, SERIES)` pair. **Mismatches are flagged and excluded**, not silently resolved. Excluded rows go to a `data/processed/_disagreements.parquet` log; coverage of these is reported in the Phase 0 certification.

**Mandatory cross-check, post-2020 only (validation overlap):** for any date where both the legacy bhavcopy and the unified file exist, run the same `TOTTRDQTY == TTL_TRD_QNTY` cross-check on a random sample of 50 dates to confirm the two eras agree on the overlap window (Q1 2020 has both). Document any systematic disagreement in the certification doc.

**Unified output schema (Parquet):** regardless of source era, all bhavcopy data lands in `data/processed/bhavcopy/{YYYY}.parquet` with columns:
```
date, symbol, series, open, high, low, close, last, prev_close,
volume, value, num_trades, deliv_qty, deliv_pct, source_era
```
where `source_era ∈ {"legacy+mto", "unified"}` so downstream code can audit which path produced any given row.

### 2.3 SERIES=EQ Filter — Mandatory Ingestion-Time (Spike Test Finding 2)

**Discovered 2026-05-18 via spike test, frozen here as engineering pre-commit:**

NSE bhavcopy files include rows for SERIES values other than EQ (debt: GS, GB; ETFs: EQ-like; preferential shares: BE, BL, BT; SME segment: SM, ST). Delivery percentage is legitimately not applicable to non-EQ rows and appears as `"-"` (literal hyphen) or blank.

**The 100% DELIV_PER coverage figure quoted in the spike test summary is only valid when SERIES=EQ is filtered.** Without the filter, raw row-count coverage was 84-93% — diluted by non-EQ rows.

**Mandate:** SERIES=EQ filter is applied at ingestion time, in `ingest/parser_legacy.py` and `ingest/parser_unified.py`. Non-EQ rows are written to a separate `data/processed/_non_eq/` partition for audit and never enter any downstream signal computation. Every Phase 0 validator and every Phase 1 signal computation operates only on SERIES=EQ rows.

**Document this in every downstream metric:** "delivery percentage coverage" and "universe size" and "IC sample size" all refer to SERIES=EQ rows.

### 2.4 ISIN Master Loader (Spike Test Finding 3)

**Discovered 2026-05-18 via spike test, frozen here as engineering pre-commit:**

Neither legacy bhavcopy nor unified bhavcopy includes ISIN. This is a real limitation that affects symbol-continuity tracking across renames and share-class splits.

**Mitigation — separate ISIN master file:**

- NSE publishes a securities master file ("EQUITY_L.csv" at `archives.nseindia.com/content/equities/EQUITY_L.csv`) containing the current listed equity universe with `SYMBOL, NAME, SERIES, DATE_OF_LISTING, PAID UP VALUE, MARKET LOT, ISIN NUMBER, FACE VALUE`. This is downloaded once and re-downloaded weekly (the master changes as new listings happen).
- Historical NSE rename events are documented in NSE circulars (e.g. TATAMOTORS → TATAMTRDVR DVR shares creation). The differ in `universe/pit.py` operates on `(SYMBOL, SERIES)` as the join key with **explicit rename-event handling** keyed off the circular archive.
- Symbol-continuity flag: any symbol that appears in NSE's "List of changes in symbol" circular (cross-referenced against the ISIN master) gets a `prior_symbol` field in the PIT universe event log. The Phase 1 universe accessor (`membership_on_date`) joins through the rename graph so a position opened under the old symbol carries forward to the new symbol without becoming a phantom exit/entry.

**This is structurally more fragile than the CIK-based S&P 500 differ.** The CIK is a permanent SEC identifier that survives every corporate action. NSE's SYMBOL is mutable. **Documented as a known limitation in §14.** The mitigation reduces risk but does not eliminate it; the Phase 0 universe validation against NSE's official Nifty 500 TR index return is the empirical check that the rename-graph is complete.

### 2.5 [CANCELLED / DROPPED] FII/DII Daily Series

This data collection step has been cancelled and dropped. See 2026-05-19 ADDENDUM.

### 2.6 F&O Expiry Calendar — Empirical Holiday Construction

**Operational decision frozen 2026-05-18:**

NSE does not publish a clean historical holiday list as a CSV. The F&O expiry calendar must be reconstructed empirically.

**Construction protocol:**

1. The downloader is the source of truth. For every weekday in the substrate window (2004-01-01 → present), the downloader attempts bhavcopy retrieval.
2. Any weekday where all three sources (legacy bhavcopy, MTO, unified) return 404 or empty content is logged to `data/processed/_holidays.jsonl` as a suspected non-trading day.
3. The expiry calendar generator (`ingest/expiry_calendar.py`) starts from "last Thursday of each month" and walks forward: if that Thursday is in `_holidays.jsonl`, expiry shifts to Wednesday; if Wednesday is also in `_holidays.jsonl`, expiry shifts to Tuesday; and so on. The shift logic is pre-committed before any backtest runs.
4. **Validation pass:** the holiday log is cross-checked manually against a list of major Indian market holidays for at least 5 calendar years (2010, 2014, 2018, 2022, 2024). Required holidays in the verification set: Republic Day (Jan 26), Holi, Eid-ul-Fitr, Mahavir Jayanti, Good Friday, Maharashtra Day (May 1), Independence Day (Aug 15), Ganesh Chaturthi, Gandhi Jayanti (Oct 2), Dussehra, Diwali (Lakshmi Pujan), Christmas (Dec 25). Any weekday in the empirical log that is NOT a known holiday is flagged as a potential data gap (NOT a holiday) and investigated. Any known holiday NOT in the empirical log is flagged as a downloader bug.
5. The validated expiry calendar is exported to `data/processed/fo_expiry_calendar.parquet` and frozen at Phase 0 close.

**Zero-error requirement for spot-check:** the validation pass must produce a 50-date spot-check where all 50 dates from the validated expiry calendar match NSE's published expiry records. Any miss blocks Phase 0.

### 2.7 Checkpointing Downloader — Mandatory

**Operational decision frozen 2026-05-18:**

Full historical pull is ≈ 16,500 requests (≈ 5,500 trading days × up to 3 sources × occasional retries). At 1-per-second polite spacing this is ~5 hours. NSE rate-limiting behavior at this scale is unverified.

**The downloader is checkpointed:**
- After every successful date-source combination, append to `data/processed/_download_checkpoint.jsonl` with `(date, source, status, bytes, sha256, completed_at)`.
- On restart, the downloader reads the checkpoint file and skips already-completed `(date, source)` pairs.
- Maximum retry count: 3 per `(date, source)` pair with exponential backoff (2s, 8s, 32s) on transient errors (timeouts, 5xx). 403/429 errors halt the run and require manual intervention.
- The downloader is intended to be run from an Indian IP (the user's Mumbai machine) for best rate-limit treatment, but the spike test cleared 30 requests from a US sandbox without 403s — the checkpointing protocol is the safety net regardless of run location.

### 2.8 Phase 0 Exit Criteria — All Seven Must Pass

Before Phase 1 begins, all of the following must be true and committed to `research/INDIA_PHASE0_CERTIFIED.md` with the SHA-256 anchor of this `INDIA_DESIGN.md` file:

1. **PIT Nifty 500 universe** validated at correlation ≥ 0.98 with official Nifty 500 TR index returns over the IS window
2. **Bhavcopy two-era loader** complete: 2004-01-01 → present in Parquet, with TOTTRDQTY cross-check log
3. **SERIES=EQ filter** applied at ingestion; non-EQ rows quarantined
4. **ISIN master** loaded and rename-event graph constructed; differ validated on at least 10 hand-verified rename events
5. **[CANCELLED / DROPPED] FII/DII daily series** (Dropped per 2026-05-19 ADDENDUM)
6. **F&O expiry calendar** validated with zero errors on 50-date spot-check
7. **Holiday calendar** empirically constructed and cross-checked against 5 calendar years of known major holidays
8. **DELIV_PER coverage** ≥ 95% of SERIES=EQ rows within Nifty 500 ever-members over the substrate window

---

## 3. Universe and Substrate Window

**Universe:** Nifty 500 PIT members from 2004-01-01 to present. Stocks enter the eligible universe on their effective addition date. Stocks exit on their effective removal date. Delisted stocks are included through their last trading date — no survivorship-bias exclusion.

**Substrate window:** 2004-01-01 → present (≈ 2026-05-18).

**Splits:**
- **In-sample (IS):** 2004-01-01 → 2014-12-31 — 11 years
- **OOS-A:** 2015-01-01 → 2019-12-31 — 5 years
- **OOS-B:** 2020-01-01 → present — ≈ 5.4 years
- **Embargo:** 21 trading days at each window boundary

**Rationale for the split:**
- IS covers 2008 financial crisis + 2013 taper tantrum (both are pre-committed Gate 5 stress periods) so signal fitting is not artificially insulated from regime stress.
- OOS-A covers a relatively stable period in Indian markets — useful to confirm the signal works in low-volatility conditions, not just stress.
- OOS-B covers COVID crash + recovery + rate cycle — a genuine stress test on a period structurally different from OOS-A. Sign agreement across OOS-A and OOS-B is meaningful because the regimes are genuinely different, not just temporally adjacent.

---

## 4. Pre-Committed Trial Set

Every parameter variation is listed here BEFORE Phase 1 runs. This is the DSR deflation denominator.

### 4.1 Delivery Percentage Trials (18)

| Lookback window | Bucket | Holding period |
|---|---|---|
| 10-day, 20-day, 60-day | Quintile (top/bottom 20%), Decile (top/bottom 10%) | 5-day, 10-day, 21-day |

3 × 2 × 3 = **18 trials**

### 4.2 [CANCELLED / DROPPED] FII/DII Flow Trials (0)

These trials have been cancelled and dropped from the pre-committed trial set because historical FII/DII flow data is not freely accessible (see 2026-05-19 ADDENDUM).

### 4.3 F&O Expiry Trials (4)

| Pre-expiry window | Post-expiry window |
|---|---|
| 3-day, 5-day | 3-day, 5-day |

2 × 2 = **4 trials**

### Total: 22 pre-committed trials

**DSR deflation is computed against all 22 trials regardless of how many actually advance to the gauntlet.** A signal family that fails Phase 1 still counts toward the deflation denominator — Phase 1 is a pre-filter, not a free-search.

**Known limitation acknowledged:** the 22-trial count understates the effective search space by ~2-3×. The signal *families* themselves represent a pre-screened selection from a larger candidate set (we did not enumerate every possible Indian-specific signal). This is documented honestly in §14 as a known understatement of the DSR denominator. Same discipline as the prior substrates' known-limitation disclosures.

**Hard rule:** do not add trials after Phase 1 begins. Do not silently drop trials after Phase 1 begins. Any trial that errors out at runtime is marked failed (not skipped) and counts toward deflation.

---

## 5. Pass Criteria — Five Gates, All Must Pass

### 5.1 Gate 1 — DSR > 0.95

Deflated Sharpe Ratio (Bailey & López de Prado 2014) computed on each OOS window independently, deflated against all 22 pre-committed trials. **DSR > 0.95 required in BOTH OOS-A and OOS-B for any signal to pass Gate 1.**

### 5.2 Gate 2 — Bootstrap CI Excludes Zero

4,000 stationary-bootstrap (Politis & Romano 1994) replications with 21-day mean block. The 95% percentile CI of the bootstrapped Sharpe must exclude zero independently in both OOS-A and OOS-B.

**Special case for F&O expiry signal:** the bootstrap block is reduced to 5 trading days (matching the event window length) and the CI is computed on the event-study return distribution (~60 OOS events per family) rather than the daily return series. This is a recognized limitation of the small event sample documented in §14.

### 5.3 Gate 3 — Sign Agreement

Sharpe must be positive in both OOS-A and OOS-B (sign agreement). The OOS windows are regime-distinct (calm vs stress); sign agreement across them is the empirical check that the signal is not a single-regime artifact.

### 5.4 Gate 4 — Cost Survival with FULL Indian Regulatory Stack Doubled

**Cost model (see §6 for derivation):** baseline round-trip cost ≈ 35.9bp + 10bp linear impact per unit turnover. Gate 4 doubles the full stack to ≈ 71.8bp + 20bp impact and requires the strategy to retain a positive Sharpe in both OOS windows.

**This is not a cost-doubling shortcut:** the doubling applies to the full stack (brokerage + GST + STT + exchange charges + SEBI charges + stamp duty + impact), not a simplified subset. The Tier 2 finding — that simplified-cost-model results overstate net Sharpe by 3-4× — is the empirical justification for the doubling stress.

### 5.5 Gate 5 — Regime Stress Test (4-of-4 + 60% Positive Months)

Required: positive Sharpe in **all four** of the following pre-committed stress periods, AND at least 60% of months within each period showing positive returns:

1. **2008 financial crisis:** 2008-01-01 → 2009-06-30 (18 months)
2. **2013 taper tantrum:** 2013-05-01 → 2013-09-30 (5 months)
3. **2020 COVID crash and recovery:** 2020-02-01 → 2020-12-31 (11 months)
4. **2022 rate cycle:** 2022-01-01 → 2022-12-31 (12 months)

**Rationale for tightening from 3-of-4 to 4-of-4:** 3-of-4 under a coin-flip null has p ≈ 0.31 — not stringent. 4-of-4 has p ≈ 0.0625 under a coin-flip null. Combined with the within-period 60%-positive-months requirement, the gate has meaningful power against single-regime artifacts.

**This gate is NOT DSR-deflated.** It is a binary pass/fail on each sub-period independently. A strategy that passes Gates 1-4 but fails Gate 5 is closed FAILED — Gate 5 is non-negotiable.

---

## 6. Cost Model — Full Indian Regulatory Stack

**STT is load-bearing.** It does not exist in US markets and was not in the prior cost models. It must be in the model from day one.

**Per-side cost stack for NSE equity *delivery* trades:**

| Component | Buy side | Sell side |
|---|---|---|
| Brokerage (NSE standard retail) | 10.0 bp | 10.0 bp |
| GST on brokerage (18% of brokerage) | 1.8 bp | 1.8 bp |
| Exchange transaction charges | 0.3 bp | 0.3 bp |
| SEBI charges | 0.1 bp | 0.1 bp |
| Stamp duty (state-level, 1.5bp standard) | 1.5 bp | 0.0 bp |
| Securities Transaction Tax (STT, sell-only) | 0.0 bp | 10.0 bp |
| **Per-side total** | **13.7 bp** | **22.2 bp** |

**Round-trip parametric cost:** 13.7 + 22.2 = **35.9 bp** before market impact.

**Market impact:** linear, 10 bp per unit of turnover (matching the Tier 2 baseline).

**Gate 4 stress:** doubled to **71.8 bp round-trip + 20 bp per unit impact**.

**Corwin-Schultz calibration check (Phase 0 deliverable):** before any backtest runs, compute Corwin-Schultz half-spread estimates on the bhavcopy OHL data for a 50-stock random sample of Nifty 500 names across IS, OOS-A, and OOS-B windows. Compare against the 5bp half-spread implicit in the parametric model. If Corwin-Schultz shows median > 10bp on Nifty 500 names, document the divergence the same way Tier 2 documented the 2bp vs 7-8bp gap. **Do not recalibrate mid-research** — document and proceed. The 3-4× understatement risk is acknowledged in §14.

---

## 7. Factor Residualization — Four-Factor Model

**Indian markets do not have a Ken French equivalent.** The closest available free-data factors:

1. **Market factor (RM-Rf):** Nifty 500 equal-weight index return minus risk-free rate.
2. **Risk-free rate:** RBI-published 91-day Treasury Bill rate (free, daily).
3. **Size proxy (SMB-like):** mimicking portfolio long bottom half by free-float market cap, short top half. Free-float market cap computed daily from `close × free_float_shares` where free-float adjustment factors come from NSE index methodology documents (updated periodically).
4. **Liquidity proxy (Amihud-illiquidity):** mimicking portfolio long low-Amihud quintile, short high-Amihud quintile. Amihud computed as `|return| / (volume × close)` rolling 21-day.

**Residualization protocol:** post-portfolio time-series regression of strategy daily returns on the four-factor return vector. HC0 heteroskedasticity-consistent standard errors on the alpha intercept.

**Hard rule:** the alpha intercept must be statistically significant (HC0 t-stat > 1.96, two-sided p < 0.05) after residualization for a signal to pass the gauntlet. A signal whose entire return is captured by size or liquidity exposure is not a real signal — it is a size or liquidity premium in disguise.

**Limitation acknowledged:** four-factor coverage is less complete than FF5+UMD. The Indian-equity factor stack is missing direct equivalents for value (HML), profitability (RMW), investment (CMA), and momentum (UMD). This is the best available from free data and is documented as a known incompleteness in §14.

---

## 8. Phase 1 — Signal Research

**Objective:** Determine whether any pre-committed signal has predictive power at any pre-committed horizon, **on in-sample data only**. Phase 1 does not touch OOS data. OOS windows are sealed until Phase 3.

**Phase 1 output:** three IC decay charts (one per signal family) + a pass/fail call per signal.

### 8.1 Phase 1A — Delivery Percentage IC Decay

For each stock on each trading day in the IS period:
- Compute the delivery percentage z-score signal at trade time T.
- Compute the forward return at horizons 1, 5, 10, 21, 63 trading days.
- Compute Spearman rank IC between signal and forward return across all (stock, day) observations at each horizon.

**Plot:** IC vs horizon. AND a rolling 12-month IC time series at the peak horizon.

**MANDATORY DUAL-WINDOW IC REPORT (Spike Test Limitation 1 — pre-2010 delivery data quality):**

Phase 1A reports IC statistics on **two windows separately**:
- **Full IS window:** 2004-01-01 → 2014-12-31 (11 years)
- **Clean sub-window:** 2010-01-01 → 2014-12-31 (5 years, post-quality-improvement)

**Pass criterion (must hold on BOTH windows):**
- IC > 0.03 at at least one horizon
- IC sign agreement between the two windows
- IC positive in at least 70% of rolling 12-month windows within each window separately

**If IC sign disagrees between the two windows** — e.g. positive in 2010-2014 sub-window, flat or negative in 2004-2009 sub-window — the signal **fails Phase 1A regardless of the IC magnitude in either window individually**. The dual-window agreement is the empirical check that the signal is not driven by pre-2010 data-quality artifacts.

### 8.2 [CANCELLED / DROPPED] Phase 1B — FII/DII Flow Correlation

This phase is cancelled and dropped (see 2026-05-19 ADDENDUM).

### 8.3 Phase 1C — F&O Expiry Event Study

For each of the ~132 expiry events in IS:
- Compute average return of high-OI stocks in [-5, -1] trading days before expiry and [+1, +5] days after.
- t-test on the event-study return distribution.

**Pass criterion:**
- Mean pre-expiry OR post-expiry return statistically significant at p < 0.05
- Consistent sign across at least 70% of individual expiry events

### 8.4 Phase 1 Exit Rule

At least one signal must pass its Phase 1 criterion before Phase 2 begins. If zero signals pass Phase 1, the substrate is **CLOSED FAILED at Phase 1** — same discipline as the PEAD contract where Phase 1b is not triggered if Phase 1a produces zero survivors.

If multiple signals pass Phase 1, all of them proceed to Phase 2. The trial count for DSR deflation remains 22 regardless of how many Phase 1 survivors there are.

---

## 9. Phase 2 — Strategy Design

Everything in Phase 2 is written down **before OOS data is touched**.

### 9.1 Portfolio Construction Rules

**For delivery percentage (cross-sectional strategy):**
- Long top quintile or decile by delivery percentage z-score
- Short bottom quintile or decile
- Equal weight within each bucket
- Rebalance at Phase 1 peak-IC holding period
- Maximum position size 2% per stock (concentration cap)
- Short-leg borrow cost 50 bp/year flat (documented explicitly; Indian shorting via SLB is more expensive than US — this is acknowledged as optimistic in §14)

**For FII/DII flow (market timing strategy):**
- [CANCELLED / DROPPED]

**For F&O expiry (event-driven strategy):**
- Enter positions in the 3-day or 5-day pre-expiry window (Phase 1 determines which)
- Exit in the corresponding post-expiry window
- Universe restricted to stocks with OI ≥ 50th percentile of their own 252-day OI history

### 9.2 Cost Model Wiring

The cost model defined in §6 is wired into the backtest engine from day one. Every fill pays brokerage + GST + STT (on sells only) + exchange + SEBI + stamp duty (on buys only) + impact. Costs are deducted per-fill in cash, not as a flat post-hoc Sharpe haircut.

---

## 10. Phase 3 — Full Gauntlet

**Objective:** Run the pre-committed five-gate gauntlet on OOS data for all Phase 1 survivors. No modifications. Honest verdict.

The gauntlet kernel reuses the equity event-driven engine (`alphaforge-python/backtest/event_driven/`) read-only, adapted for Indian-market hours (9:15 IST → 15:30 IST) and the Indian cost model.

**Three additions vs the equity gauntlet:**

1. **STT in cost model** — wired per §6.
2. **Four-factor residualization** — wired per §7.
3. **Gate 5 regime stress** — 4-of-4 stress periods + 60%-positive-months per §5.5.

**Phase 3 output:** `research/GAUNTLET_VERDICT.md` with full trial-by-trial breakdown, gate-by-gate pass/fail per trial, and the substrate verdict.

**Three possible verdicts:**
- **CLOSED FAILED:** 0 trials pass all five gates. Substrate is documented and closed. Same discipline as the prior five verdicts.
- **CONDITIONAL:** ≥1 trial passes Gates 1-4 but fails Gate 5 (regime stress). Survivor is documented but NOT deployable. Substrate is closed unless Gate 5 can be passed on a strategy-design refinement that respects the pre-commit.
- **DEPLOY-READY:** ≥1 trial passes all five gates. Proceeds to Phase 4.

---

## 11. Phase 4 — Live Paper Trading (Survivor-Conditional)

Only triggered if Phase 3 produces a DEPLOY-READY survivor.

**Infrastructure:** adapt `alphaforge-execution/` for NSE — `jugaad-trader` for live data, kill-switch + risk logic adapted for 9:15-15:30 IST hours, SQLite persistence for fills + positions.

**Paper trading period:** minimum 60 NSE trading days (≈ 3 months given Indian holiday calendar).

**Go/no-go for real capital:**
- Live Sharpe within ±1 SE of backtest Sharpe
- No gate failures during paper period
- Signal distribution in live data consistent with historical (no detected regime break)

**Limitation acknowledged:** 60 days is short for statistical confidence on a 5-21 day holding-period strategy (≈ 3-12 round trips). **Phase 4 outcome is informational + sanity-check, not a deflated re-gauntlet.** Real-capital deployment requires founder approval on top of Phase 4 PASS.

---

## 12. Decision Matrix

| Phase 1 result | Phase 3 result | Outcome |
|---|---|---|
| 0 signals pass | n/a | CLOSED FAILED at Phase 1 (substrate #6 closed) |
| ≥1 signals pass | 0 trials pass all 5 gates | CLOSED FAILED at Phase 3 |
| ≥1 signals pass | ≥1 trial passes Gates 1-4 only | CONDITIONAL — survivor documented, not deployable |
| ≥1 signals pass | ≥1 trial passes all 5 gates | DEPLOY-READY — proceed to Phase 4 |
| Phase 4 PASS | — | Founder-approval gate for real capital |
| Phase 4 FAIL | — | Survivor closed; substrate closed |

---

## 13. Timeline (Wall-Clock Estimate)

| Week | Deliverable |
|---|---|
| Week 1 | Nifty 500 PIT universe construction — the most error-prone task. Do not rush. |
| Week 2 | Bhavcopy + MTO + unified download with checkpointing. CA adjustment. Parquet storage. Expiry calendar. |
| Week 3 | Phase 0 certification (INDIA_PHASE0_CERTIFIED.md + SHA-256 anchor). Phase 1A delivery percentage IC decay. |
| Week 4 | Phase 1C F&O expiry. Phase 1 verdict. Phase 2 strategy design (if survivors). |
| Week 5-6 | Phase 3 gauntlet on OOS. Verdict document. |
| Week 7+ | Phase 4 paper trading (if DEPLOY-READY survivor). Otherwise substrate closes. |

Timeline is wall-clock estimate, not a hard deadline. The microstructure substrate (#4) takes priority when its book-data clock closes (≈ 2026-06-17).

---

## 14. Honest Limitations — Pre-Committed Before Research Runs

These are documented HERE, in the contract, before any signal is computed. They cannot be re-discovered post-hoc as a Phase 1 failure rationalization.

### 14.1 Pre-2010 delivery percentage data quality
Pre-2010 MTO files have known format inconsistencies and occasional missing values. Any result heavily dependent on pre-2010 data should be treated with additional skepticism. Phase 1A's mandatory dual-window report is the empirical control.

### 14.2 Survivorship bias residual risk
NSE historical constituent data is less comprehensively documented than S&P 500 changes. There may be addition/removal events that are not captured in publicly available sources. Same risk profile as the 25% OHLCV gap in the S&P 500 universe — documented honestly and reported in every downstream metric.

### 14.3 ISIN absence in bhavcopy (Spike Test Finding 3)
Neither bhavcopy format includes ISIN. Symbol continuity across renames and share-class splits is handled via a separate ISIN master file + circular-archive rename graph in `universe/pit.py`. This is structurally more fragile than the CIK-based equity-stack differ. The Phase 0 universe correlation ≥ 0.98 check is the empirical control; if it fails, the rename graph is incomplete.

### 14.4 Cost model optimism
Parametric cost model has been shown to underestimate real costs by 3-4× in US equity Tier 1/2 testing. Indian-equity Nifty 500 spreads are tighter than US mid-caps but wider than S&P 500 large caps. Gate 4 doubling is the empirical control but may itself be optimistic. Corwin-Schultz calibration check (§6) is the Phase 0 sanity check.

### 14.5 [CANCELLED / DROPPED] FII/DII aggregation noise
This limitation is no longer applicable as the FII/DII signal family has been dropped.

### 14.6 F&O expiry small sample
~264 events over 22 years. Phase 1C and Phase 3 Gate 2 use event-study bootstraps with 5-day blocks rather than the daily-block bootstrap used for delivery percentage. CI widths will be wider on this signal.

### 14.7 Short-leg borrow cost
50 bp/year flat is documented as optimistic. Indian SLB market is structurally smaller and more expensive than US institutional shorting. Gate 4 doubling should be interpreted as also covering short-leg cost risk.

### 14.8 Four-factor residualization incompleteness
Indian factor stack is missing direct equivalents for HML, RMW, CMA, UMD. The four available factors (market, risk-free, size, liquidity) are the best available from free data. A signal whose alpha is captured by HML or UMD will NOT be detected by the four-factor residualization.

### 14.9 22-trial deflation denominator understates effective search
The signal *families* themselves represent a pre-screened selection from a larger candidate set of Indian-specific signals (we did not enumerate every possible signal). Effective search space is ~2-3× the 22-trial count. DSR results should be interpreted with that understatement in mind.

### 14.10 Two-era loader engineering complexity
The pre-2020 legacy+MTO join introduces an engineering surface that the post-2020 unified read does not. Cross-check (`TOTTRDQTY == QUANTITY_TRADED`) mismatches are quarantined to `_disagreements.parquet`. If the mismatch rate is high (>1% of (date, symbol, series) tuples), the substrate may have to operate on the post-2020 era only — which would cut IS coverage from 11 years to ~5 years and is documented as a potential Phase 0 finding.

### 14.11 Reduced-IP run risk
The downloader is intended to be run from an Indian IP. The spike test was run from a US sandbox and passed; full-history pulls at scale may behave differently. The checkpointing protocol mitigates but does not eliminate the risk of a mid-run ban.

### 14.12 FII/DII Daily Series Drop
As detailed in the 2026-05-19 ADDENDUM, historical daily FII/DII data is not freely accessible. While current day data is available via `/api/fiidiiTradeReact`, historical data endpoints return 404 or SSL failure. Dropping this signal family reduces the trial set from 31 to 22.

---

## 15. Hard Rules — What Cannot Be Modified Post-Phase-1

Frozen at Phase 1 start. Any edit to these rules after Phase 1 begins constitutes peeking and invalidates the gauntlet.

1. **Trial set §4.** No additions. No silent drops. Trials that error count as failures.
2. **OOS split §3.** Embargo unchanged. Boundaries unchanged.
3. **Gate criteria §5.** DSR hurdle, bootstrap CI threshold, sign-agreement requirement, cost-doubling factor, regime period definitions, 4-of-4 + 60%-positive-months — all frozen.
4. **Cost model §6.** Full Indian regulatory stack. Numbers frozen. Stress multiplier (2×) frozen.
5. **Residualization §7.** Four-factor model. HC0 SEs. t-stat threshold frozen.
6. **Phase 1 dual-window IC mandate §8.1.** Sign-agreement requirement frozen.
7. **Decision matrix §12.** Outcome categories frozen.

Permitted post-Phase-1 edits (audit-friendly only):
- Typo corrections.
- Adding **ADDENDUM** sections (in the style of PEAD §2.2 ADDENDUM) that document in-place engineering discoveries — discoveries that change implementation but NOT the substantive contract. Any such addendum must be explicitly labeled and SHA-256-anchored separately.

---

## 16. SHA-256 Anchor

The Phase 1 orchestrator will refuse to run unless the SHA-256 of this file matches the anchor recorded in `research/INDIA_PHASE0_CERTIFIED.md`. The certification document records the hash at Phase 0 close.

Anchor recorded: see `INDIA_PHASE0_CERTIFIED.md` (created at Phase 0 close).

---

## 17. ADDENDUM: Dropping FII/DII Daily Series

**Finding:** FII/DII historical daily data is not freely accessible from NSE. The `/api/fiidiiTradeReact` endpoint returns the current day only regardless of date parameter. All historical archive paths return 404 or SSL failure. The spike test covered 12 URL patterns across 5 dates from 2008 to 2025.

**Decision:** FII/DII signal family dropped from substrate #6. Trials 19-27 in the pre-committed trial set are cancelled. DSR deflation denominator reduced from 31 to 22 trials.

**Contract classification:** Engineering discovery ADDENDUM per §15 allowed-edits clause. Not a gate relaxation. Not a post-hoc threshold change. The remaining 22 trials are unaffected.

**Direction of effect:** Dropping 9 trials reduces the multiple-testing burden marginally. This makes the remaining signals easier to pass DSR deflation, not harder. Documented as a known limitation — the true search space including FII/DII exploration is larger than the 22-trial denominator reflects.

**Date:** 2026-05-19. SHA of `INDIA_DESIGN.md` at time of addendum: `81153990fa64b4f7ddf210df7ba0bd5ab81eee3aa91c605033b2a22d8094765b`.
