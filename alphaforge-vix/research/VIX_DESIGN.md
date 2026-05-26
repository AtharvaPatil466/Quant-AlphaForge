# AlphaForge VIX / Variance Risk Premium — Pre-Committed Design

**Status:** PRE-COMMITMENT. Written 2026-05-20. No CBOE data has been downloaded. No signal has been computed. No backtest has been run.

**This document is the contract.** It defines, before any data infrastructure code runs at scale, the substrate window, the signal definitions, the trial set, the deflation hurdle, the cost model, the residualization protocol, and the decision matrix. **No edit to this document is permitted after Phase 1 begins.** Edits after Phase 1 starts would constitute peeking — the discipline that produced six credible negative verdicts (equity Tier 1, Tier 2, crypto carry, PEAD, India, and the methodology-bug retest) requires this contract stay frozen.

Pairs with `alphaforge-vix/CLAUDE.md` (sub-project context) and the top-level `CLAUDE.md` (substrate landscape).

---

## 0. Context — Why VIX, Why Now

VIX/VRP is the **seventh substrate attempt** in this project. The six prior attempts:

| # | Substrate | Verdict | Date | Diagnosis |
|---|---|---|---|---|
| 1 | Equity Tier 1 (PIT S&P 500 cross-section) | CLOSED FAILED | 2026-05-02 | Mode A — real signal, deflation kills it |
| 2 | Equity Tier 2 (lower-turnover variant) | CLOSED FAILED | 2026-05-02 | Mode B — short-horizon-specific, doesn't transport |
| 3 | Crypto USDT-M funding-rate carry | CLOSED FAILED | 2026-05-15 | Mode A — IC ≈ 0.5, costs + DSR win |
| 4 | Microstructure (BTC-USDT L2 + tape) | IN PROGRESS | 2026-05-17 → +30d | — (Phase 0 book-data accumulation) |
| 5 | PEAD (EDGAR XBRL on PIT S&P 500) | CLOSED FAILED | 2026-05-17 | Mode A — "real but weak", 0/10 cleared DSR |
| 6 | India (NSE bhavcopy + delivery + F&O) | CLOSED FAILED | 2026-05-20 | Mode C — sign inversion, 0/18 cleared, all OOS Sharpes negative |

**The structural finding from six substrates:** the row-2 / Mode A failure pattern — and its variants B (horizon-bound) and C (sign inversion) — is **geographic-agnostic AND signal-class-agnostic** within the constraints we've imposed: free public data, parametric retail cost model, deflation-aware gauntlet. Six substrates testing six different "whats" produced three distinct failure modes; the *unifying truth* is that at retail-data-grade, the anomalies are post-arbitrage.

**Substrate #7 is the first constraint shift of the project.** All six prior substrates shared one structural assumption: alpha comes from *prediction*. Predicting cross-sectional returns. Predicting carry. Predicting post-earnings drift. Predicting expiry mean-reversion. **VIX/VRP breaks that assumption.** This substrate does not try to predict anything. It tries to harvest a structural premium — the gap between implied volatility and subsequent realized volatility — that exists because investors systematically overpay for portfolio insurance. The edge is not better forecasting; it is *being the insurance writer*.

**Why this is structurally different from substrates 1-6:**
- Prior substrates asked "does this signal predict returns?" — and failed when prediction didn't hold OOS.
- VIX/VRP asks "does this structural premium survive costs, tail risk, and regime stress after honest accounting?"
- The premium's existence is not in dispute. It has been documented for 30+ years (Bondarenko 2004, Carr & Wu 2009). The question is whether it survives an honest gauntlet at retail scale.

**The two known risks that distinguish this substrate:**
1. **Catastrophic tail risk.** February 5 2018 ("Volmageddon"): XIV lost 90% of NAV in one day. March 2020: VIX spiked from 15 to 85 in three weeks. These are *features* of short-volatility strategies, not anomalies to exclude.
2. **Disguised factor exposure.** Short volatility is correlated with short-term reversal, carry, and low-volatility equity factor returns. A "VRP alpha" that is actually disguised equity beta + factor exposure must be flagged by residualization before being called real.

**Substrate #7 is the override of the §7 reset cooldown** that was originally locked until 2026-06-01. This is the fourth override — after crypto (2026-05-15), PEAD (2026-05-17), India (2026-05-18). The first three overrides each closed FAILED. The justification for this fourth override is the constraint-shift framing: VIX/VRP is not "let me try one more substrate at the same constraint set" — it is a deliberate move to a *different class of edge* (premium harvest vs predictive alpha). If this also fails, the next move is not substrate #8 at the same constraints; it is either a paid-data constraint break or a category move outside systematic alpha.

VIX/VRP is **not** a reopening of any frozen sub-project. The equity stack (`alphaforge-python/factors/`, `-marl/`, `-execution/`) stays frozen. `.halt` stays engaged on the execution loop regardless of VIX outcome. This is a net-new sub-project with its own data, signals, and pre-commit gauntlet.

---

## 1. The Hypothesis

Three pre-committed signal candidates. All three exploit the same structural mechanism (variance risk premium) at different levels: directly (VRP), structurally (term structure), and tactically (mean reversion).

### 1.1 The Economic Mechanism (Read Before Any Code)

**Why the variance risk premium exists:** Portfolio managers need to hedge downside risk. They buy puts and call spreads. This buying pressure pushes implied volatility above what realized volatility will turn out to be. The difference — implied minus realized — is the premium that accrues to whoever is on the other side of that trade. Historically, the 30-day VIX has averaged 4-5 vol points above subsequent realized SPX volatility. That gap is the premium being harvested.

**Why it persists.** Pure arbitrage capital cannot eliminate the premium because short-volatility strategies occasionally blow up catastrophically (Volmageddon 2018, March 2020). Tail events keep the premium structurally above zero — investors writing volatility require compensation for bearing the spike risk. **The premium is not free money.** It is payment for a specific, known, catastrophic risk. The gauntlet must treat tail events as features of the strategy, not anomalies to exclude.

### 1.2 Signal 1 — VRP Carry (Primary)

**Construction:** On each trading day, compute the variance risk premium as

```
VRP_t = VIX_t − realized_vol_t(L)
```

where `realized_vol_t(L)` is the trailing L-day realized volatility of SPY daily log returns, annualized.

When VRP > 0 (implied above realized), the premium is rich → signal is short-volatility. When VRP < 0, premium is absent or inverted → signal is flat or long-volatility.

**Economic rationale:** Mean reversion in VRP. When implied vol is above realized, options are expensive relative to historical experience; selling them (short vol) earns the convergence.

**Holding period:** 21 trading days (one VIX futures roll cycle), unless exit rule triggers earlier (see §9.3).

### 1.3 Signal 2 — Term Structure Slope (Secondary)

**Construction:** The slope of the VIX futures term structure. Two slope measures pre-committed:

```
slope_3M = VIX3M / VIX        (contango ratio)
slope_6M = VIX6M / VIX        (longer-dated contango ratio)
slope_diff = VIX3M − VIX      (additive slope in vol points)
```

When the curve is in steep contango (slope > 1.05), short front-month VIX futures earn roll yield as the futures decay toward spot. When the curve is flat or inverted (slope ≤ 1), roll yield is zero or negative.

**Economic rationale:** Roll yield is *structural*, not predictive. Contango → positive carry to the short side. The signal is not "the market will fall"; it is "while contango persists, the short position earns the term-structure decay."

**Holding period:** Monthly roll — enter at the start of each calendar month, exit at front-month VIX futures expiry (third Wednesday).

### 1.4 Signal 3 — VIX Mean Reversion (Tertiary)

**Construction:** When VIX > MA63 + k·σ63 (k = 1.5 or 2.0, where σ63 is the 63-day stdev of VIX), the spike is signal that the curve will mean-revert. Signal is *long volatility* during the spike (defensive — protects the short positions from worsening) and *short volatility* when VIX is in a normal or low regime.

**Economic rationale:** VIX spikes are driven by fear and forced hedging demand. Once the forcing function passes, implied volatility mean-reverts toward realized. This signal is primarily a *regime filter* (sizing modifier on signals 1+2) rather than a standalone alpha source.

**Holding period:** Event-driven. Enter on spike threshold breach; exit when VIX returns to within one σ63 of MA63, or returns fully to MA63 (two exit variants pre-committed).

---

## 2. Phase 0 — Data Collection and Validation

**Objective:** Download, validate, and store all required data before signal code runs. Phase 1 is blocked until Phase 0 cert is filed.

### 2.1 VIX Futures Settlement Prices

**Source:** CBOE historical settlement files at `cboe.com/us/futures/market_statistics/historical_data/`. Free, no account required. Available 2004-03 to present (VIX futures launched March 2004).

**Schema:** date, futures_symbol (e.g. `VX/F4`), settlement_price, open, high, low, total_volume, open_interest, expiry_date, days_to_expiry.

**Validation:** cross-check 10 random (date, futures_symbol) settlement prices against published CBOE records. Continuity check: no gaps > 3 trading days within a contract's life.

### 2.2 VIX Term Structure Indices

**Source:** CBOE indices download — VIX1D, VIX9D, VIX, VIX3M, VIX6M.

**Schema:** date, VIX1D, VIX9D, VIX, VIX3M, VIX6M (wide format, one row per trading day).

**Validation:**
- No gaps > 3 trading days.
- Cross-check 20 random dates against the CBOE indices page directly.
- Sanity: VIX3M ≥ VIX more often than VIX > VIX3M (long-run contango bias).

### 2.3 SPY Returns and Realized Volatility

**Source:** yfinance (existing infrastructure in this project).

**Computed columns:**
- `daily_log_return = ln(close_t / close_{t-1})`
- `realized_vol_10 = std(daily_log_return, window=10) × √252`
- `realized_vol_21 = std(daily_log_return, window=21) × √252`
- `realized_vol_63 = std(daily_log_return, window=63) × √252`

**Validation:** realized-vol spikes in well-known events must be present:
- September-October 2008 (Lehman): realized_vol_21 should exceed 60.
- May 6 2010 (Flash Crash week): one-day return < -3.5%.
- August 24 2015: gap-down open, realized_vol_21 spike.
- February 5 2018 (Volmageddon): realized_vol_21 spike from ~10 to >30 within days.
- March 16 2020 (COVID Monday): daily return < -10%, realized_vol_21 > 80.

If any of these fail, the SPY series has a data error and Phase 0 is blocked.

### 2.4 VXX and SVXY Price History

**Source:** yfinance.

**VXX:** launched 2009-01-30. Records expense ratios and rebalancing events.
**SVXY:** launched 2011-10-04 as -1× exposure. **2018-02-27 restructuring:** SVXY's exposure changed from -1× to -0.5× following Volmageddon. This is not a data anomaly; it is a *structural product change*. Pre and post 2018-02-27 SVXY must be treated as two different instruments in any backtest that uses SVXY as the live-execution proxy.

**Validation:** check that SVXY's 2018-02-05 / 2018-02-06 returns reflect the ~80-90% loss before restructuring.

### 2.5 Phase 0 Exit Criteria — All Five Must Pass

1. **VIX futures** settlement table from 2004-03 to present, validated 10-date spot-check.
2. **VIX term structure indices** (VIX1D/9D/30/3M/6M) from 2004-01 to present, validated 20-date spot-check.
3. **SPY return + realized-vol series** from 2004-01 to present, all five known volatility events captured.
4. **VXX history** (2009-01-30 onward) and **SVXY history** (2011-10-04 onward), with 2018-02-27 restructuring metadata recorded.
5. **`VIX_PHASE0_CERTIFIED.md`** filed in `research/` with SHA-256 anchor of this `VIX_DESIGN.md`.

---

## 3. Substrate Window

**Universe:** SPX/VIX complex. No multi-asset cross-section — this is a single-instrument premium harvest strategy. Position can be expressed via VIX futures, VXX, SVXY, or SPY options; the backtest uses VIX futures (cleanest data); live execution uses VXX/SVXY ETPs (acknowledged in §14.2).

**Substrate window:** 2004-03-26 (first VIX futures trading day) → present.

**Splits:**
- **In-sample (IS):** 2004-03-26 → 2014-12-31 — ~10.7 years covering 2008 crisis, 2011 debt ceiling, 2013 taper tantrum, recovery, QE eras.
- **OOS-A:** 2015-01-01 → 2019-12-31 — 5 years covering the post-QE low-vol regime + Volmageddon (2018-02-05).
- **OOS-B:** 2020-01-01 → present — ≈ 5.4 years covering COVID crash, recovery, rate cycle, recent regime.
- **Embargo:** 21 trading days at each window boundary.

**Why this split.** OOS-A captures the post-restructuring SVXY regime and includes Volmageddon as a single non-excludable stress event inside the window. OOS-B captures the COVID-era high-vol regime and post-2022 normalization. Sign agreement across OOS-A + OOS-B is structurally meaningful because they test different volatility environments.

---

## 4. Pre-Committed Trial Set

Every parameter variation listed here BEFORE Phase 1 runs. This is the DSR deflation denominator.

### 4.1 VRP Carry trials (18)

| Realized-vol lookback (L) | VRP entry threshold | Holding period (days) |
|---|---|---|
| 10, 21, 63 | VRP > 0, > 2, > 4 vol points | 5, 21 |

3 × 3 × 2 = **18 trials**

### 4.2 Term Structure Slope trials (6)

| Slope measure | Entry threshold |
|---|---|
| `VIX3M/VIX`, `VIX6M/VIX`, `VIX3M − VIX` | ≥ 1.05 (or 0.05 for additive), ≥ 1.10 (or 0.10) |

3 × 2 = **6 trials**

### 4.3 VIX Mean Reversion trials (4)

| Spike entry threshold | Exit threshold |
|---|---|
| `MA63 + 1.5·σ63`, `MA63 + 2.0·σ63` | Return to `MA63 + 1.0·σ63`, return to `MA63` |

2 × 2 = **4 trials**

### Total: 28 pre-committed trials

**DSR deflation denominator = 28 regardless of how many trials actually advance to the gauntlet.** Trials that fail Phase 1 still count.

**Hedged vs unhedged.** Both Variant A (unhedged) and Variant B (hedged with long OTM VIX calls, see §9.2) are run for *each* of the 28 trials. The verdict reports both variants. **The trial-set count of 28 covers signal-parameter combinations only**; the hedge axis is a strategy-design parameter pre-committed (not searched). **Effective search space disclosure:** with 2 hedge variants × 28 signal trials = 56 strategy-trial combinations evaluated. Documented in §14.9 as a known understatement of the DSR denominator (factor of ~2×). If the user wants to be more conservative, deflating against 56 is the alternate framing.

**Hard rule:** no trials added after Phase 1 begins. Trials that error count as fails. No silent drops.

---

## 5. Pass Criteria — Six Gates, All Must Pass

Six gates. Gates 1-4 are the same as prior substrates. Gate 5 is a max-drawdown gate specific to short-volatility (different from prior substrates' Sharpe-positive Gate 5). Gate 6 is new: Cornish-Fisher Sharpe accounting for non-normality.

### 5.1 Gate 1 — DSR > 0.95

Deflated Sharpe Ratio (Bailey & López de Prado 2014), deflated against all 28 pre-committed trials. **DSR > 0.95 required in BOTH OOS-A and OOS-B independently.**

### 5.2 Gate 2 — Bootstrap CI Excludes Zero

4,000 stationary-bootstrap (Politis & Romano 1994) replications with 21-day mean block. 95% CI of Sharpe must exclude zero independently in both OOS-A and OOS-B.

### 5.3 Gate 3 — Sign Agreement

Sharpe positive in both OOS-A and OOS-B. The windows are regime-distinct (calm vs Volmageddon vs COVID); sign agreement is empirical evidence the strategy is not a single-regime artifact.

### 5.4 Gate 4 — Cost Survival with Doubled Stack

**Baseline costs:**
- VIX futures: 0.05 VIX-point half-spread per contract; 1 bp of notional commission.
- ETP execution: 10 bp round trip (VXX/SVXY).

**Gate 4 stress:** double both. 0.10 VIX-point half-spread + 2 bp commission for futures; 20 bp round trip for ETPs. Strategy must retain positive Sharpe in both OOS windows under doubled costs.

### 5.5 Gate 5 — Regime Stress Test (Max-Drawdown Bound, 4-of-4)

**This gate is materially different from prior substrates' Gate 5.** Short-volatility strategies cannot be evaluated on Sharpe-positive in tail events — a strategy that earns 15% per year but loses 90% in one month is not deployable regardless of annual Sharpe. Gate 5 here is a **maximum-drawdown bound** per stress period.

Four pre-committed stress periods:
1. **2008 financial crisis** (2008-09-01 → 2009-03-31, ~7 months)
2. **2011 debt-ceiling crisis** (2011-07-01 → 2011-10-31, ~4 months)
3. **2018 Volmageddon** (2018-02-01 → 2018-03-31, ~2 months)
4. **2020 COVID crash** (2020-02-01 → 2020-04-30, ~3 months)

**Pass criterion:** in EACH of the four periods, the strategy's peak-to-trough drawdown must be **≤ 30%** of equity entering the period. 4-of-4 required (not 3-of-4 — this is non-negotiable for short-vol).

**Note:** stress periods 1 and 2 fall inside the IS window. The drawdown gate is evaluated on the in-sample portfolio for those two; on the OOS portfolio for periods 3 and 4. The IS evaluation here is not "training data" — it is checking that the *strategy as specified* survives the historical stress, which is a strategy-design test, not a signal-fit test.

### 5.6 Gate 6 — Tail Risk Accounting (Cornish-Fisher Sharpe > 0.5)

New gate, specific to this substrate. Compute the strategy's monthly returns over OOS-A + OOS-B combined. Estimate skewness and excess kurtosis. Compute the **Cornish-Fisher modified Sharpe ratio** (Favre & Galeano 2002):

```
CF-Sharpe = Sharpe / Cornish-Fisher VaR-adjustment factor
```

where the CF adjustment penalizes negative skewness and positive excess kurtosis. **CF-Sharpe > 0.5 required** in both OOS-A and OOS-B independently.

**Why this gate exists.** A strategy with raw Sharpe 1.5 and catastrophic negative skewness has a CF-Sharpe much lower than 1.5. The raw Sharpe overstates the risk-adjusted return. Gate 6 forces the strategy to declare its tail risk in the same numeric framework as its expected return.

---

## 6. Cost Model

### 6.1 Baseline costs (used in default backtest)

**VIX futures execution path:**
- Half-spread: 0.05 VIX points per contract per side. (VIX futures multiplier = $1,000 per point; 0.05 = $50/contract/side.)
- Commission: 1 bp of notional ($1.50 per VX contract at VIX=15).
- Total round-trip: ≈ 0.10 vol points + 2 bp commission ≈ 0.15 vol points + commission.

**ETP execution path (VXX/SVXY):**
- Round-trip cost: 10 bp.

**Carry on margin:** VIX futures require margin posted with the broker. Margin earns the risk-free rate (3-month T-bill, FRED `DGS3MO`). Pre-2022 ZIRP era: ~0% on margin. Post-2022: ~4-5%. Backtest accounts for this explicitly.

**STT / regulatory:** none (US, not India).

### 6.2 Gate 4 stress

All baseline costs doubled. See §5.4.

### 6.3 Honest accounting requirements

- **Slippage** in stress periods must be modeled with a 3× cost widening during pre-committed stress periods (2008/2011/2018/2020). This is empirically observed — bid-ask widens by roughly 3-5× when VIX > 40.
- **Position sizing** (see §9.1) caps notional exposure such that a one-standard-deviation VIX spike from the entry-day VIX level is bounded.

---

## 7. Residualization — Four-Factor Model (Short-Volatility-Specific)

Per the constraint shift to premium-harvest: short volatility is known to be correlated with several equity factors. A "VRP alpha" that is actually disguised equity beta is not new alpha. **Phase 3 hard rule:** alpha intercept must be statistically significant after residualization against this four-factor set.

**Factor 1: SPY return** — equity market beta. Short-vol strategies are short tail-risk insurance, which has correlation with the equity market.

**Factor 2: ΔVIX** — direct change in VIX. Captures any residual delta exposure to spot vol moves.

**Factor 3: ST-Reversal factor** — Kenneth French's daily short-term reversal factor. Known correlation with short-volatility returns (Bondarenko 2014).

**Factor 4: Carry factor** — proxy via FRED 3-month T-bill change, or the Cochrane-Piazzesi cycle factor when available. Captures the term-structure exposure that overlaps with short-volatility carry.

**Protocol:** post-portfolio time-series OLS of daily strategy returns on the four-factor vector + constant intercept. HC0 (White 1980) standard errors. **Hard rule (§7):** alpha intercept t-stat > 1.96 (two-sided p < 0.05) required after residualization for any signal to pass the gauntlet.

**Falloff condition:** if any of the four factors are missing (e.g. Kenneth French data unavailable for a window), Phase 3 reports the available residualization and explicitly notes the missing factor as a §14 known limitation. The verdict is then provisional pending the full factor set.

---

## 8. Phase 1 — Signal Research

**Objective:** Determine whether any pre-committed signal has genuine predictive content on IS data. OOS sealed.

### 8.1 Phase 1A — VRP Decay Analysis

For each VRP trial parameter combination on each IS trading day:
- Compute VRP at the configured lookback.
- Compute forward returns to a short-volatility position (via VIX futures front-month) at horizons {5, 10, 21, 42, 63}.
- Compute Pearson correlation between VRP at trade time and forward return at each horizon.

**Plot:** correlation vs horizon (decay curve). Rolling 12-month correlation at the peak horizon.

**Phase 1A pass criterion:**
- Correlation > 0.05 at at least one horizon.
- Positive sign in at least 8 of 11 IS calendar years.
- **NOT concentrated exclusively in 2008-2009** — at least 6 of the IS years must show positive correlation when 2008+2009 are excluded.

### 8.2 Phase 1B — Term Structure Slope Analysis

Same methodology as Phase 1A applied to the slope signals. Additionally:
- Compute average roll yield earned by holding short front-month VIX futures across all IS months in contango (slope > 1) vs backwardation (slope < 1).
- **Sanity check (not a pass test):** contango months should earn positive roll yield; backwardation months should earn negative. If this fails, the term-structure mechanism is broken in the data and Phase 1 is blocked pending investigation.

**Phase 1B pass criterion:** same as Phase 1A.

### 8.3 Phase 1C — VIX Regime Analysis

Characterize the VIX regime distribution in IS:
- Fraction of IS days with VIX < 15 (low-vol)
- VIX 15-25 (normal)
- VIX 25-35 (elevated)
- VIX > 35 (crisis)

This is a *characterization* of the IS data, not a signal pass test. Used to inform Phase 2 position-sizing.

### 8.4 Phase 1 Exit Rule

At least one signal must pass its Phase 1 criterion before Phase 2 begins. Zero survivors → CLOSED FAILED at Phase 1.

---

## 9. Phase 2 — Strategy Design

**Objective:** Pre-commit position management and risk rules BEFORE OOS data is touched.

### 9.1 Position Sizing (pre-committed, not searched)

Maximum notional short-volatility exposure on any day:

```
max_notional = 0.10 × portfolio_value / VIX_level_t
```

This sizes the position *down* when VIX is elevated — a defensive auto-deleverage. Rationale: a 4σ VIX spike from VIX=15 is much larger in absolute points than from VIX=35; sizing inversely to VIX caps the worst-case dollar loss.

**Implicit leverage acknowledgement.** VIX futures are notionally leveraged. The above formula caps notional, not margin. Margin requirement = futures exchange spec (typically ~10-15% of notional). Backtest tracks both.

### 9.2 Hedging — Two Variants (Both Run)

**Variant A — Unhedged short volatility.** Pure premium harvest. Maximum drawdown risk. Higher expected return. This is what blew up XIV in Volmageddon.

**Variant B — Hedged with long OTM VIX calls.** Short front-month VIX futures + long OTM VIX calls (strike = VIX_spot + 10 vol points, expiry = same as the short futures). The hedge costs premium but caps maximum loss on a spike. Lower expected return; survivable in 2018.

Both variants run for every one of the 28 trials. Verdict reports both. **No post-hoc choice between variants.** The user pre-commits that the deploy candidate (if any) is the variant with the higher Phase 3 verdict pass rate; both must individually pass all six gates.

### 9.3 Exit Rules (pre-committed)

**Hard stop (kill-switch equivalent):** if VIX rises > 40% intraday from previous close, exit ALL short-volatility positions immediately regardless of signal state. Same discipline as `alphaforge-execution/`'s kill-switch.

**Signal exit:** for VRP carry, exit when VRP falls below 0 (premium has collapsed). For term structure slope, exit at front-month futures expiry. For mean reversion, exit per §1.4 thresholds.

**Time-based exit:** any position held > 60 calendar days without a signal-exit trigger is force-closed (prevents stuck positions).

---

## 10. Phase 3 — Full Gauntlet

**Objective:** Run the six-gate gauntlet on OOS-A + OOS-B for every Phase 1 survivor × both hedge variants. Honest verdict.

Gauntlet kernel reuses the equity event-driven engine (`alphaforge-python/backtest/event_driven/`) read-only, adapted for the VIX universe (futures-instrument bookkeeping) and the §6 cost stack.

**Three additions vs the standard gauntlet:**
1. **Gate 5 max-drawdown bound** (§5.5) instead of Sharpe-positive regime test.
2. **Gate 6 Cornish-Fisher Sharpe** (§5.6) — new.
3. **Four-factor short-vol residualization** (§7) wired into the gauntlet output.

**Phase 3 output:** `research/GAUNTLET_VERDICT.md` with per-(trial, variant) breakdown, gate-by-gate detail, and substrate verdict per §11 decision matrix.

---

## 11. Phase 4 — Live Paper Trading (Survivor-Conditional)

Only triggered if Phase 3 produces a DEPLOY-READY survivor.

**Infrastructure:** adapt `alphaforge-execution/` for VIX futures + VXX/SVXY ETPs. Use IBKR paper-trade API.

**Paper trading period:** minimum 60 trading days. Live PnL tracked vs backtest expectation.

**Go/no-go for real capital:**
- Live Sharpe within ±1 SE of Phase 3 Sharpe.
- No Gate 5 drawdown breaches during paper period.
- No kill-switch (§9.3) triggers without recovery.
- Founder approval (this is a real-capital decision, not a methodology decision).

---

## 12. Decision Matrix

| Phase 1 | Phase 3 | Outcome |
|---|---|---|
| 0 signals pass | n/a | CLOSED FAILED at Phase 1 |
| ≥1 signals pass | 0 variant-trial pairs pass all 6 gates | CLOSED FAILED at Phase 3 |
| ≥1 signals pass | ≥1 pair passes Gates 1-4 but fails 5 or 6 | CONDITIONAL — documented, not deployable |
| ≥1 signals pass | ≥1 pair passes all 6 gates | DEPLOY-READY → Phase 4 |
| Phase 4 PASS | — | Founder-approval gate for real capital |
| Phase 4 FAIL | — | Survivor closed; substrate closed |

---

## 13. Timeline (Wall-Clock Estimate)

| Day | Deliverable |
|---|---|
| 1 | VIX_DESIGN.md committed (this doc). CBOE + yfinance Phase 0 data download. `VIX_PHASE0_CERTIFIED.md` filed with SHA anchor. |
| 2 | Phase 1A VRP decay analysis. Phase 1C regime characterization. |
| 3 | Phase 1B term-structure analysis. Phase 1 verdict. |
| 4 | Phase 2 strategy-design pre-commit (position sizing + hedge variants + exits) frozen. |
| 5-6 | Phase 3 gauntlet on OOS for all Phase 1 survivors × both variants. |
| 7 | Verdict document written. Honest result regardless. |

Timeline is wall-clock estimate; not a hard deadline. Microstructure (#4) and any other in-flight substrate retain priority on data + compute.

---

## 14. Honest Limitations — Pre-Committed Before Research Runs

### 14.1 Catastrophic tail risk is a feature, not a bug
The unhedged variant lost 90% in one day in February 2018. Any backtest that doesn't show this is either using the hedged variant or has a bug. Pre-committed: the verdict will report Volmageddon performance even when reporting positive aggregate Sharpe.

### 14.2 Execution instrument mismatch
Backtest uses VIX futures (cleanest data); live execution uses VXX/SVXY ETPs (real tradeable retail instruments). The ETPs have management fees (VXX 0.89%, SVXY 0.95%), tracking error, and rebalancing slippage that the futures-based backtest does not capture. **Backtest Sharpe overstates live Sharpe by an unknown amount; the gap could be 20-50% of Sharpe.**

### 14.3 Implicit leverage in short-vol
Short-vol is implicitly leveraged. A VIX spike of 20 points on a one-contract short position is $20,000 loss against ~$10,000 margin posted. Position sizing per §9.1 caps notional, but margin calls during spikes can force closures at the worst prices.

### 14.4 SVXY restructuring is a real regime break
2018-02-27 — SVXY changed from -1× to -0.5× exposure. Pre-2018-02-27 results using SVXY as proxy do not transfer to post-restructuring. Backtest treats pre/post as two separate instruments.

### 14.5 The premium may be partially disguised factor exposure
Short-vol returns correlate with short-term reversal, low-vol equity factor, and carry. §7 residualization is the empirical control. If alpha t-stat fails after residualization, the "premium" is leveraged factor exposure.

### 14.6 Post-2018 regime change
The ETP complex was restructured after Volmageddon. The short-vol microstructure changed materially. Results from pre-2018 data may not fully transfer; OOS-B starting 2020 captures the post-restructuring regime and addresses this partially.

### 14.7 Margin financing rate is regime-dependent
Pre-2022 ZIRP era earned ~0% on margin; post-2022 earns 4-5%. The cost-of-carry profile of the strategy is regime-dependent and the backtest must use the actual T-bill series, not a constant.

### 14.8 Stress-period slippage is modeled, not measured
The 3× cost widening during stress periods (§6.3) is an estimate, not a measurement. Real slippage during 2008 and 2020 was potentially worse. Gate 4's cost-doubling is the safeguard, but live execution in stress periods could still be worse than backtest.

### 14.9 Effective search space is 2× the deflation denominator
The 28-trial DSR denominator (§4) covers signal-parameter combinations only. Two hedge variants × 28 = 56 strategy-trial combinations are actually evaluated. The deflation denominator understates the effective multiple-testing burden by ~2×. Conservative interpretation: a borderline DSR result should be discounted accordingly.

### 14.10 The premium may be arbitraged away post-2020
Post-Volmageddon retail participation in short-vol dropped. Whether the remaining premium is sufficient to clear costs after a more institutional-only counterparty mix is an open question. OOS-B is the empirical test.

### 14.11 Cornish-Fisher is a parametric approximation
Gate 6's Cornish-Fisher adjustment is a fourth-order Taylor approximation. It is informative but not a substitute for non-parametric tail estimation (e.g. EVT). The gauntlet uses CF for tractability; a passing CF-Sharpe is necessary but not sufficient for true tail-robustness.

---

## 15. Hard Rules — What Cannot Be Modified Post-Phase-1

Frozen at Phase 1 start. Any edit to these constitutes peeking and invalidates the gauntlet.

1. **Trial set §4.** No additions. No silent drops. Errors count as fails.
2. **Substrate window + splits §3.** Embargo unchanged. Boundaries unchanged.
3. **Gate criteria §5.** DSR > 0.95, bootstrap CI threshold, sign-agreement, cost-doubling factor, 30% max-drawdown per stress period, 4-of-4 stress, CF-Sharpe > 0.5 — all frozen.
4. **Cost model §6.** Half-spreads, commissions, ETP round-trip, stress widening factor — frozen.
5. **Residualization §7.** Four-factor model, HC0 SEs, t-stat threshold — frozen.
6. **Position sizing §9.1, hedge variants §9.2, exit rules §9.3.** All frozen.
7. **Decision matrix §12.** Outcome categories frozen.

Permitted post-Phase-1 edits (audit-friendly only):
- Typo corrections.
- **ADDENDUM** sections (in the style of PEAD §2.2 and India §17 addenda) that document in-place engineering discoveries — discoveries that change implementation but NOT the substantive contract. Any such addendum must be explicitly labeled, dated, and SHA-256-anchored separately.

---

## 16. SHA-256 Anchor

The Phase 1 orchestrator will refuse to run unless the SHA-256 of this file matches the anchor recorded in `research/VIX_PHASE0_CERTIFIED.md`. The certification document records the hash at Phase 0 close.

Anchor recorded: see `VIX_PHASE0_CERTIFIED.md` (filed at Phase 0 close).

---

## 17. ADDENDUM — Phase 0 Data-Source Discovery (2026-05-21)

**Finding.** A two-round spike test on 2026-05-20/21 (`/tmp/vix_spike/`) probed every data source listed in §2 across 22 candidate URLs. The CBOE indices (§2.2) and yfinance equity sources (§2.3, §2.4) are reachable as expected. **The CBOE VIX futures historical settlement data (§2.1) is no longer freely available.** All five candidate URL patterns return HTTP 403:

- `/data/us/futures/market_statistics/historical_data/products/csv/VX/VX_*.csv`
- `/data/us/futures/market_statistics/historical_data/`
- `/api/global/futures/symbols/VX`
- `/data/us/futures/market_statistics/eod_summary/*`
- Yahoo `VX=F` / `VIX=F` continuous tickers return 0 rows ("possibly delisted").

CBOE migrated this data set to their paid DataShop product post-2024. StooQ's alternative is captcha-gated. There is no free historical VIX futures settlement source reachable from this environment.

A secondary finding: **VXX via yfinance covers only 2018-01-25 → present**, not the 2009-01-30 launch date claimed in §2.4. The original Barclays VXX matured in January 2019; yfinance carries only the post-relaunch instrument issued by Barclays Bank under the VEQTOR Sigma SP framework. SVXY remains 2011-10-04 → present, covering its full history including the 2018-02-27 restructuring.

**Decision.** Substrate window UNCHANGED (2004-03-26 → present). Trial set UNCHANGED (28 trials). Gates UNCHANGED. Decision matrix UNCHANGED. The execution-instrument layer is re-scoped to SVXY-only (with VXX as the hedge instrument post-2018), and the slope-signal economic mechanism is re-stated as an index-ratio proxy. Specifics:

**17.1 §1.3 slope signal — economic-mechanism re-statement.**
The original §1.3 described roll yield as "earning the spread between where you sell (higher back month) and where the futures converge to (lower front month)." Without VIX futures data, the slope is measured exclusively as the **VIX3M/VIX index ratio** (and the VIX6M and additive variants pre-committed in §4.2). The mechanism is approximated, not directly observed in futures prices. This is a *measurement* change, not a contract change — the same parameter trials are evaluated, just on index ratios instead of futures slopes.

**17.2 §2.1 — VIX futures settlement download is REMOVED from Phase 0.**
The Phase 0 exit checklist drops from five items to four:
1. ~~VIX futures settlement table~~ — REMOVED (not freely obtainable).
2. VIX term-structure indices — UNCHANGED.
3. SPY return + realized-vol series — UNCHANGED.
4. VXX + SVXY history — UPDATED per §17.3.
5. `VIX_PHASE0_CERTIFIED.md` filing — UNCHANGED.

**17.3 §2.4 — execution-instrument coverage corrected.**
- **SVXY: 2011-10-04 → present.** Used for the short-volatility position in both variants. Pre-2018-02-27 SVXY is -1× exposure; post-restructuring is -0.5×. Treated as two instruments with the restructuring date as the regime boundary (already pre-committed in §14.4).
- **VXX: 2018-01-25 → present** (post-relaunch instrument). Used as the long-volatility hedge instrument in Variant B. Pre-2018 VXX is unavailable.

**17.4 §9.2 hedged variant — hedge instrument re-specified.**
Original §9.2 specified "long OTM VIX calls" as the hedge. Without VIX option chain data, the hedge is re-specified as **long VXX** at a pre-committed notional ratio (10% of SVXY notional, frozen — no search). VXX gains when VIX rises, providing imperfect tail protection. The hedge is imperfect (VXX has its own contango drag) but uses fully available data and matches real retail execution.

**Pre-2018 hedged-variant testability.** Because VXX is unavailable pre-2018, Variant B is evaluated only on the post-2018 portion of the backtest. The verdict reports:
- Variant A (unhedged): evaluated across full SVXY history (2011-10-04 → present).
- Variant B (hedged with VXX): evaluated 2018-01-25 → present only.

This is a reduction in evidence for Variant B (the hedge of interest precisely because Variant A is the one that blew up in 2018). Documented as a §14 limitation.

**17.5 Phase 1 signal-research window unchanged.**
The Phase 1 IC + decay analysis uses VIX spot + SPY realized-vol only — both available 2004-onward. The full 2004-2014 IS window is preserved for signal research. Only the Phase 3 backtest is effectively constrained to 2011-10-04 onwards (SVXY launch).

**17.6 §14 — new known limitations.**
- **§14.12 VIX futures unavailability.** The original §1.3 economic mechanism is approximated via the VIX3M/VIX index ratio, not directly measured. The roll-yield rationale is preserved as theoretical motivation but the empirical signal is index-based.
- **§14.13 SVXY-only execution.** The backtest cannot run against VIX futures directly. SVXY is the execution instrument throughout. Live-Sharpe overstatement risk per §14.2 still applies and is, if anything, larger.
- **§14.14 Hedged-variant evidence is post-2018 only.** Variant B has roughly half the OOS evidence of Variant A. Conservative interpretation: borderline Variant B verdicts should be discounted.

**Contract classification.** ADDENDUM-level engineering discovery per §15 allowed-edits clause. Not a gate relaxation. Not a post-hoc threshold change. The trial set, gates, residualization protocol, decision matrix, and substrate window are all UNCHANGED. The contract is the same; the implementation path is constrained.

**Direction of effect.** Strictly reduces the strength of evidence for both variants (Variant B more than Variant A). Makes passing the gauntlet HARDER, not easier. Per pre-commit discipline this is the right direction for an ADDENDUM.

**Date:** 2026-05-21.
**SHA at time of addendum:** `22d468ce34260da2fcd4130878ba47a1d8966dc327cb5a5167d21481b1af91cf`.

---

## 17.7 ADDENDUM — Phase 1 VRP Forward-Return Proxy (2026-05-21)

**Finding.** §8.1 specifies that for each IS trading day, the VRP IC is computed by correlating VRP at trade time against "forward returns to a short-volatility position (via VIX futures front-month) at horizons {5, 10, 21, 42, 63}." The §17.2 ADDENDUM removed VIX futures from Phase 0 (CBOE moved settlements to paid DataShop). §17.5 then explicitly preserves Phase 1's full 2004-2014 IS window by stating that "the Phase 1 IC + decay analysis uses VIX spot + SPY realized-vol only — both available 2004-onward." This leaves the forward-return proxy under-specified: the §17.5 sentence implies the proxy is constructable from VIX spot alone, but the precise mathematical form was not pinned down.

**Decision.** Forward return for VRP IC is defined as the **negative log-change in spot VIX over horizon h**:

```
forward_return_{t,h} = -log(VIX_{t+h} / VIX_t)
```

Positive when VIX falls (which is what a short-volatility position profits from). Computed at the §8.1 horizons {5, 10, 21, 42, 63} trading days. Pearson correlation of VRP_t with this forward return is the §8.1 IC.

**Rationale.** Three candidates were considered before Phase 1 ran:

1. **-Δlog(VIX) spot** — chosen. Pure VIX-spot proxy. Covers the full IS window. Nothing inferred from missing data.
2. **-Δlog(VIX) + realized-vol drag term** — adds a modeled term beyond pure spot. Closer to futures-economics but introduces a parameter (drag-loading factor) that is not pre-committed and would itself need an addendum.
3. **SVXY return post-2011** — most realistic for the live-execution P&L, but collapses the IS window from 2004-2014 → 2011-2014 (loses ~70% of IS evidence). Direct conflict with §17.5's preservation of the full IS window.

The chosen proxy is option 1. The user (founder) approved the choice on 2026-05-21 before any Phase 1 code executed against the data.

**Direction of effect.** Spot VIX is a noisier short-vol return signal than the front-month VIX futures price. Futures have a built-in convexity term (roll yield + decay-toward-spot) that mechanically amplifies returns on the short side when contango persists. Using spot VIX *strictly understates* the IC magnitudes that the contracted-but-unavailable futures-based proxy would produce. **Direction of effect: makes Phase 1 pass criteria HARDER, not easier.** Per the §15 ADDENDUM discipline, this is the correct direction for an in-place engineering discovery.

**Pre-commit anti-peek anchor.** This addendum is filed BEFORE Phase 1 code runs against the data. No IC numbers exist at the time of this commitment. The Phase 1 orchestrator (built next) will SHA-anchor against the *post-§17.7* design-doc hash. The Phase 0 cert will be re-anchored to the new hash; the cert content is unchanged (Phase 0's PASS/SKIP set does not depend on the forward-return proxy choice — Phase 0 validates data availability, not signal definitions).

**§14.15 (new known limitation).** The Phase 1 IC measured against -Δlog(VIX) is a *lower bound* on the IC that would be obtained against the contracted-but-unobtainable VIX futures front-month. If a signal *fails* Phase 1, this addendum's IC understatement does NOT exonerate the signal — a near-miss should be discounted, not promoted. If a signal *passes* Phase 1, the §14.13 SVXY-execution overstatement still applies in Phase 3.

**Contract classification.** ADDENDUM-level engineering discovery per §15 allowed-edits clause. Not a gate relaxation. Not a post-hoc threshold change. The trial set, gates, residualization protocol, decision matrix, and substrate window are all UNCHANGED. The contract is the same; the implementation path is specified where §17.5 left it implicit.

**Date:** 2026-05-21.
**SHA at time of addendum (pre-§17.7):** `56d745e73f415ab822e4f8019404bd5a2302d5c272aab4bb3248e2bd2a8c51d3`.

---

## 17.8 ADDENDUM — Phase 3 Cash-Carry Zeroing (2026-05-21)

**Finding.** First Phase 3 gauntlet execution against the SHA-anchored §17.7 stack (`66a6c45a…`) produced an implausible result: **18 of 28 (trial × variant) combos cleared all six gates AND the §7 residualization on the first run**, with OOS Sharpes ranging +2.8 to +11.6. The output is the inverse of the prior six substrate verdicts, all of which closed FAILED. Inspection of the per-trial detail revealed the cause: the §9.1 sizing formula

```
max_notional = 0.10 × portfolio_value / VIX_level_t
```

evaluates to **$5,000 of short-vol notional at VIX=20 on a $1M portfolio (0.5% of NAV)**. Combined with §17.3 (SVXY-only execution, fully cash-funded — no margin posting), the strategy holds **~99.5% of NAV in cash on every day**. The §6 / §14.7 carry-on-cash implementation in `gauntlet/costs.py` then credits the cash balance with the FRED-DGS3MO-or-fallback risk-free rate (post-2022 fallback = 450 bp annualized). The resulting NAV trajectory is dominated by the cash carry — the VRP/MR signal contributes a tiny PnL overlay on top of an essentially riskless cash position. Daily-return standard deviation is dominated by the carry's near-constant drift, so Sharpe explodes (low variance × steady drift × √252).

Confirming evidence:
- Volmageddon 2018 max-drawdown reported as 0.81% (real short-vol XIV lost ~90% in one day).
- 2008 financial crisis max-drawdown reported as 0.00% — but SVXY didn't exist in 2008; the strategy can't have traded, so the "0%" reflects pure cash carry through the period.
- Gate 4 (cost-double) Sharpes are nearly identical to baseline — costs are negligible because trades are small.
- Residualization alpha t-stats of 16-35 on essentially riskless returns.

**Diagnosis.** The §6 / §14.7 carry was designed for **margin posted with a futures broker** (per §6.1 "VIX futures require margin posted with the broker. Margin earns the risk-free rate"). The §17.2 ADDENDUM removed the futures path entirely. Under §17.3 (SVXY ETP via cash), there is no margin to post — the SVXY position is paid for outright. Free cash in a retail brokerage account typically earns 0% on commodity balances. The original §6 carry intent does NOT translate to the ETP path; applying it produces a degenerate gauntlet result.

**Decision.** `gauntlet.costs.CarryTable` is set to return 0 bp annualized for all dates in the Phase 3 gauntlet implementation. Strategy returns are computed entirely from position PnL net of fill costs — no cash-carry contribution. The §14.7 fallback table remains in the module for future use cases (e.g., if a futures-execution path is ever revived); it is simply not consumed by the runner.

**Implementation:** the `run_gauntlet.py` constructs its `Backtest` with `carry_table=costs_mod.CarryTable(fred_series=pd.Series([0.0], index=[pd.Timestamp("1990-01-01")]))` — a one-row series of 0 that forward-fills to 0 for every date.

**Direction of effect.** **Strictly REDUCES strategy returns and SHARPLY REDUCES Sharpes.** Makes Phase 3 HARDER, not easier. Per the §15 ADDENDUM discipline, this is the right direction for an in-place engineering discovery.

**§14.17 (new known limitation).** The §9.1 sizing formula produces position sizes that are extremely small fractions of NAV (~0.5% at VIX=20). Under any realistic short-vol return process, the strategy as specified can only generate small dollar gains and losses. The Phase 3 verdict therefore tests "does VRP/MR show a *small but consistent* signal at the §9.1 sizing?" rather than "can VRP/MR be capacity-meaningful?". A passing verdict at §9.1 sizing implies the SIGNAL exists; whether it scales to deployment size is a Phase 4 / capacity-analysis question beyond the §10 gauntlet's scope.

**Contract classification.** ADDENDUM-level engineering discovery per §15 allowed-edits clause. Not a gate relaxation. Not a post-hoc threshold change. Trial set, gates, residualization protocol, decision matrix, and substrate window are all UNCHANGED. The contract is the same; the cash-carry interpretation is corrected to match the §17.2/§17.3 execution path.

**Date:** 2026-05-21.
**SHA at time of addendum (pre-§17.8):** `66a6c45a90bdda5879cc37348ac01bc7aea59e5c8403531592c3d9509cdabb0b`.
