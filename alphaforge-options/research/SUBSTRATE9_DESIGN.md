# AlphaForge Options — Substrate #9 Pre-Committed Design
# VRP Iron Condor via SPY Options

**Status:** PRE-COMMITMENT. Written 2026-05-26. No options backtest has been run. No B-S reconstruction P&L has been computed. No gauntlet result exists.

**This document is the contract.** It defines, before any signal or backtest code runs, the instrument, the strategy structure, the trial set, the deflation hurdle, the cost model, the residualization protocol, and the decision matrix. **No edit to this document is permitted after Phase 1 begins.** Edits after Phase 1 starts constitute peeking — the same discipline that produced eight credible verdicts across seven substrates (six predictive CLOSED FAILED, one premium-harvest CLOSED FAILED at both §9.1 and 20× sizing) requires this contract stay frozen.

Pairs with `alphaforge-options/CLAUDE.md` (sub-project context) and the top-level `CLAUDE.md` (substrate landscape).

---

## 0. Context — Why Substrate #9, Why Options

### 0.1 What the Prior Eight Verdicts Established

| # | Substrate | Verdict | Date | Diagnosis |
|---|---|---|---|---|
| 1 | Equity Tier 1 (PIT S&P 500 cross-section) | CLOSED FAILED | 2026-05-02 | Mode A — real signal, deflation kills it |
| 2 | Equity Tier 2 (lower-turnover variant) | CLOSED FAILED | 2026-05-02 | Mode B — short-horizon-specific |
| 3 | Crypto USDT-M funding-rate carry | CLOSED FAILED | 2026-05-15 | Mode A — IC ≈ 0.5, costs + DSR win |
| 4 | Microstructure (BTC-USDT L2 + tape) | IN PROGRESS | 2026-05-17 → +30d | Phase 0 accumulating |
| 5 | PEAD (EDGAR XBRL on PIT S&P 500) | CLOSED FAILED | 2026-05-17 | Mode A — "real but weak", 0/10 cleared |
| 6 | India (NSE bhavcopy + delivery + F&O) | CLOSED FAILED | 2026-05-20 | Mode C — sign inversion |
| 7 | VIX/VRP via SVXY/VXX ETPs (§9.1 sizing) | CLOSED FAILED | 2026-05-21 | Mode D → Mode A revisited (Sharpe invariant to scaling) |
| 8 | VIX/VRP via SVXY/VXX ETPs (20× sizing) | CLOSED FAILED | 2026-05-21 | Mode A confirmed — OOS Sharpe ~0.5, insufficient for 28-trial DSR |

**The Mode A / Sharpe-invariance finding from #7 and #8 combined.** Substrate #8 proved that linear scaling of the SVXY ETP position does not change the Sharpe ratio — mean and standard deviation of returns both scale by the same factor k, so k cancels. The correct diagnosis across #7 and #8: the VRP signal via ETP execution has a genuine but modest OOS Sharpe (~0.3-0.5 best case) that cannot clear DSR > 0.95 against a 28-trial pre-commit at ~5-year OOS sample length, at any ETP sizing.

**What Substrate #7 Phase 1 did establish (and this remains valid):** The VRP signal (VIX − realized_vol) has genuine predictive content. Peak IC = +0.180 at h=21. 10 of 18 pre-committed trials passed signed-positive IC. The premium exists. The Phase 1 evidence was not invalidated by Phase 3 — it was Phase 3's ETP *implementation* that failed, not the underlying economic mechanism.

### 0.2 Why Options Are Structurally Different from ETPs

The Mode A failure of substrates #7 and #8 is specific to the ETP execution path. SVXY and VXX track the VIX futures roll yield — a near-linear, continuously-compounded return series. The Sharpe of this series is bounded by the IC of the underlying signal at the relevant horizon, and that IC (+0.18 at h=21) produces a Sharpe too modest to clear DSR against 28 trials.

**The iron condor is a different instrument with a fundamentally different P&L structure.**

An iron condor (sell 16Δ put + 16Δ call, buy 5Δ put + 5Δ call at the same expiry) generates returns via:

1. **Theta decay** — options lose value over time even if the underlying doesn't move. This is quadratic, not linear: theta accelerates in the final 21 days, which is why rolling at 21 DTE captures the steepest decay curve without the gamma risk near expiry.

2. **Bounded payoff** — the maximum loss per cycle is fixed at `wing_width − net_premium_received`. At 16Δ/5Δ strikes with SPY at $560 and VIX at 20: wing width ≈ $17/share, premium ≈ $4.50/share, max loss ≈ $12.50/share. This is known at entry. SVXY has no such bound.

3. **Win rate vs payout asymmetry** — iron condors win on roughly 68-72% of monthly cycles (the underlying stays within ±1σ). The distribution of monthly returns is right-skewed (many small gains, infrequent bounded losses). The Sharpe of this distribution is materially different from a linear ETP return series.

4. **VRP is harvested via IV−RV gap, not futures roll.** When IV (at-entry VIX) exceeds RV (SPY moves during the hold), the options expire worth less than the premium collected. This is the same economic mechanism as #7/#8 but accessed via a non-linear payoff function that produces a higher information ratio per unit of capital employed.

**The key empirical question Substrate #9 tests:** Does the non-linear theta-decay payoff structure of the iron condor produce an OOS Sharpe that clears DSR > 0.95 against 6 pre-committed trials — where the DSR hurdle is far lower than the 28-trial hurdle that killed substrates #7 and #8?

### 0.3 Execution Infrastructure Change

Substrates #7 and #8 used Alpaca (equity ETPs). Substrate #9 uses **IBKR paper trading** for Phase 4, and Black-Scholes reconstruction of options prices for Phases 1-3. The IBKR paper account was opened 2026-05-26. No options fills have been made in paper trading at the time of this pre-commit.

---

## 1. The Hypothesis

**One signal, one structural mechanism, one instrument class.**

The variance risk premium (IV − RV > 0) is a structural premium. Portfolio managers overpay for tail protection. The iron condor is the retail-executable implementation of being the insurance writer with defined maximum loss.

### 1.1 Economic Mechanism

When IV > RV — the normal state of equity markets — selling options and letting them decay is profitable in expectation. The iron condor:
- Captures theta as the underlying moves within the wing range
- Limits tail exposure via the long wings (unlike naked short vol)
- Earns the IV−RV spread without continuous ETP roll cost

**Why the premium persists despite being documented:** The iron condor seller accepts the risk that the underlying gaps outside the wing range in a crash. This tail risk keeps the premium from being arbitraged away — institutional sellers require compensation for bearing it. The premium is not free money; it is payment for a specific, bounded catastrophic risk.

### 1.2 Signal — VRP Filter

On each potential entry date (every 30-45 DTE cycle):

```
VRP_t = VIX_t − realized_vol_t(21d)
```

where `realized_vol_t(21d)` is the trailing 21-day realized volatility of SPY log returns, annualized, in VIX-percent units (matching Substrate #7 §17.7 ADDENDUM methodology).

**Entry filter:** open a new iron condor cycle only when `VRP_t > threshold`. When VRP ≤ threshold, the premium is not rich enough to compensate for tail risk — skip the cycle and stay flat (collect no premium, incur no risk).

**This is not a directional prediction.** The filter is "is the VRP currently positive enough to enter?" not "will SPY go up or down?".

---

## 2. Phase 0 — Data Certification

**Objective:** Certify all required data before any signal or backtest code runs. Phase 1 is blocked until Phase 0 cert is filed.

### 2.1 SPY Daily OHLCV

**Source:** yfinance (existing infrastructure). SPY history from 1993-01-29 to present.

**Required columns:** date, open, high, low, close, volume. Adjusted for splits and dividends.

**Validation:**
- No gaps > 3 trading days.
- 5-spike validator (same events as Substrate #7 §2.3): 2008 Lehman, 2010 Flash Crash, 2015 August gap, 2018 Volmageddon, 2020 COVID Monday.
- Cross-check: SPY close on 2020-03-16 must be < $240 (historical low that day ≈ $225).

**Status:** Already downloaded in `alphaforge-vix/data/etps/SPY.parquet` (Substrate #7 artifact). Phase 0 reads from this path — no re-download unless the parquet is stale (< 2024-01-01 last row).

### 2.2 VIX Daily Index

**Source:** CBOE via `alphaforge-vix/ingest/cboe.py` (Substrate #7 artifact). Already on disk at `alphaforge-vix/data/vix_indices/`.

**Required:** date, VIX (spot), VIX3M (optional — used for entry-filter variant only).

**Validation:**
- VIX must cover 2004-01-02 → present with no gap > 3 trading days.
- Sanity: VIX3M ≥ VIX on > 85% of dates (long-run contango bias confirmed at 92.3% in Substrate #7 Phase 0).

**Status:** Already certified in Substrate #7 Phase 0. Re-read from existing parquet.

### 2.3 FRED Risk-Free Rate (DGS3MO)

**Source:** FRED `DGS3MO`. Used as discount rate in Black-Scholes pricing.

**Fallback constants (if FRED network unavailable, same as Substrate #7 §14.7):**
- 2004-2008: 3.5% annualized
- 2009-2015: 0.1%
- 2016-2021: 1.5%
- 2022-present: 4.5%

**Status:** Available from `alphaforge-vix/ingest/fred.py`.

### 2.4 Phase 0 Exit Criteria — All Three Must Pass

1. **SPY OHLCV** from 2004-01-02 to present, 5-spike validator passes.
2. **VIX index** from 2004-01-02 to present, spot-check 10 random dates against CBOE.
3. **`SUBSTRATE9_PHASE0_CERTIFIED.md`** filed in `research/` with SHA-256 anchor of this document.

No new data downloads required — all three sources exist from Substrate #7. Phase 0 is primarily verification + SHA anchoring.

---

## 3. Substrate Window

**Instrument:** SPY options (American-style, quarterly + monthly expiries). SPY is the most liquid single-name options market — typical bid-ask on ATM monthly options is $0.05-0.10/share.

**Substrate window:** 2004-01-02 → present. Aligned with Substrate #7 for regime comparability.

**Splits:**
- **In-sample (IS):** 2004-01-02 → 2014-12-31 (~10.9 years). Covers 2008 crisis, 2010 Flash Crash, 2011 debt ceiling, 2013 taper tantrum, QE era.
- **OOS-A:** 2015-01-01 → 2019-12-31 (5 years). Post-QE low-vol regime, Volmageddon 2018-02-05.
- **OOS-B:** 2020-01-01 → present (~6.4 years). COVID crash, recovery, rate cycle, recent regime.
- **Embargo:** 21 trading days at each window boundary.

**Why the same window as #7/#8.** Direct comparability of regimes. Volmageddon (OOS-A) and COVID (OOS-B) are the two key stress tests for any short-vol strategy. Identical splits allow side-by-side comparison of options vs ETP outcomes.

---

## 4. Black-Scholes Reconstruction Methodology

**This section is load-bearing for the pre-commit.** Because historical SPY options chains are not freely available, all backtest P&L is reconstructed from Black-Scholes using VIX as the implied volatility input. The methodology, known biases, and their direction must be declared before any code runs.

### 4.1 Input Parameters

On each options entry date `t` at DTE `T` (= 30 calendar days = ~21 trading days):

```
S    = SPY_close_t                          (underlying price)
r    = DGS3MO_t / 100                       (annualized risk-free, daily interpolated)
σ    = VIX_t / 100                          (annualized implied vol, flat surface assumed)
T    = DTE / 252                            (time to expiry in years)
```

### 4.2 Strike Selection

For a given delta target Δ_target:

```python
def find_strike_for_delta(S, r, sigma, T, delta_target, option_type):
    # Solve: BS_delta(S, K, T, r, sigma) = delta_target
    # BS call delta = N(d1), BS put delta = -N(-d1)
    # Numerically: bracket and bisect on K
    # d1 = (ln(S/K) + (r + 0.5*sigma**2)*T) / (sigma*sqrt(T))
```

Pre-committed delta targets:
- **Short leg (16Δ):** `|Δ| = 0.16` → d1 ≈ −1.0 for puts, +1.0 for calls
- **Short leg (20Δ, Trial 4 only):** `|Δ| = 0.20` → d1 ≈ −0.84 / +0.84
- **Long leg (5Δ):** `|Δ| = 0.05` → d1 ≈ −1.645 for puts, +1.645 for calls
- **Long leg (10Δ, Trial 5 only):** `|Δ| = 0.10` → d1 ≈ −1.28 / +1.28

### 4.3 Premium and P&L Computation

**Net premium collected at open (per share of SPY):**
```
premium = BS_call(S, K_call_short, T, r, σ)
        + BS_put(S, K_put_short, T, r, σ)
        − BS_call(S, K_call_long, T, r, σ)
        − BS_put(S, K_put_long, T, r, σ)
```

**P&L at roll (21 DTE = T_roll = 9 calendar days remaining) or expiry:**
```
cost_to_close = BS_call(S_t2, K_call_short, T_roll, r_t2, σ_t2)
              + BS_put(S_t2, K_put_short, T_roll, r_t2, σ_t2)
              − BS_call(S_t2, K_call_long, T_roll, r_t2, σ_t2)
              − BS_put(S_t2, K_put_long, T_roll, r_t2, σ_t2)

cycle_pnl = premium − cost_to_close − transaction_costs
```

**At expiry (if held to T=0):**
```
payoff = max(0, S_expiry − K_call_short) − max(0, S_expiry − K_call_long)
       + max(0, K_put_short − S_expiry) − max(0, K_put_long − S_expiry)

cycle_pnl = premium − payoff − transaction_costs
```

### 4.4 Known Biases — Direction Declared Before Code Runs

**Bias 1 (conservative — favors failing):** Black-Scholes assumes flat implied vol surface. In reality, OTM puts (the short and long put legs) are priced with higher IV than ATM (the volatility smile/skew). Real put premiums for 16Δ and 5Δ strikes are 20-40% higher than BS with flat VIX-σ.

*Effect on strategy:* BS UNDERESTIMATES the premium collected on the short puts AND the cost of long puts. Net effect is ambiguous but empirically the short-leg premium effect dominates (the 16Δ put is closer to ATM than the 5Δ long put, so the relative underestimation is larger for the short leg). **Direction: BS reconstruction likely UNDERESTIMATES net premium collected → understates strategy P&L → conservative bias (makes strategy HARDER to pass gauntlet).**

**Bias 2 (directionally ambiguous):** VIX measures 30-day implied vol for ATM SPX options. SPY options have slightly different implied vol due to ETF-vs-index basis. This bias is small (typically < 1 vol point) and directionally ambiguous.

**Bias 3 (conservative — favors failing):** Roll at T_roll = 9 calendar days uses closing VIX and closing SPY price. Real roll execution happens intraday with bid-ask friction. BS mid-price ignores the bid-ask spread on the closing position, which is separately captured in the transaction cost model. The BS mid-price reconstruction at roll is slightly optimistic vs real mid-price; the transaction cost correction should offset this.

**Net declared bias direction: conservative (makes the strategy HARDER to pass the gauntlet, not easier).** A borderline result should not be promoted on the grounds that "real options are richer than BS" — this is a known limitation, not a correction factor.

---

## 5. Pre-Committed Trial Set

Six trials. All six pre-committed before Phase 1 runs. DSR deflation denominator = **6** (vs 28 in substrates #7/#8).

**Why 6, not 28.** The signal direction is pre-validated by Substrate #7 Phase 1 (IC +0.180 at h=21, 10/18 VRP trials positive). The parameter space for iron condors is also more constrained than the ETP parameter space — strike selection has a natural range (10-25Δ for short legs in standard practice), and DTE is fixed at 30-45 by the theta-decay curve argument. Pre-committing 6 trials is not "searching less" — it is correctly specifying the relevant parameter space for this instrument class.

**DSR implication.** With 6 trials, a raw OOS Sharpe of ~0.85-1.0 is sufficient to clear DSR > 0.95 at a 5-year OOS window (vs ~1.8-2.0 needed for 28 trials). Historical iron condor strategies on SPX have documented Sharpe of 0.8-1.2. The gate is attainable.

| Trial | Short strike Δ | Long strike Δ | VRP threshold | VIX filter | Roll rule |
|-------|---------------|---------------|---------------|------------|-----------|
| T1 (base) | 16Δ | 5Δ | VRP > 0 | None | 21 DTE |
| T2 | 16Δ | 5Δ | VRP > 2 vol pts | None | 21 DTE |
| T3 | 16Δ | 5Δ | VRP > 0 | VIX < 30 | 21 DTE |
| T4 | 20Δ | 5Δ | VRP > 0 | None | 21 DTE |
| T5 | 16Δ | 10Δ | VRP > 0 | None | 21 DTE |
| T6 | 16Δ | 5Δ | VRP > 2 vol pts | VIX < 30 | 21 DTE |

**No additional trials may be added after this document is SHA-anchored.** Errors count as fails. Trials that produce zero entries in an OOS window (e.g., VRP filter always active during a window) count as fails for that trial.

---

## 6. Pass Criteria — Six Gates, All Must Pass

Gates 1-4 are inherited from Substrate #7 `VIX_DESIGN.md` §5 with one modification (Gate 1 DSR denominator = 6). Gate 5 is modified for the defined-risk profile of the iron condor. Gate 6 is unchanged.

### 6.1 Gate 1 — DSR > 0.95

Deflated Sharpe Ratio (Bailey & López de Prado 2014). **DSR denominator = 6 (not 28).** DSR > 0.95 required independently in **both OOS-A and OOS-B.**

### 6.2 Gate 2 — Bootstrap CI Excludes Zero

4,000 stationary-bootstrap (Politis & Romano 1994) replications with 21-day mean block. 95% CI of Sharpe excludes zero independently in both OOS-A and OOS-B.

### 6.3 Gate 3 — Sign Agreement

Raw Sharpe positive in both OOS-A and OOS-B independently.

### 6.4 Gate 4 — Cost Survival with Doubled Stack

Transaction costs doubled (see §7 cost model). Strategy must retain positive Sharpe in both OOS windows under doubled costs.

### 6.5 Gate 5 — Regime Stress Test (Max-Drawdown Bound, 3-of-3 Covered Periods)

**Modified from Substrate #7 to reflect defined-risk profile.**

Pre-committed stress periods:
1. **2008 financial crisis** (2008-09-01 → 2009-03-31, ~7 months)
2. **2018 Volmageddon** (2018-02-01 → 2018-03-31, ~2 months)
3. **2020 COVID crash** (2020-02-01 → 2020-04-30, ~3 months)

**Pass criterion:** in EACH covered period, peak-to-trough drawdown ≤ **40%** of NAV entering the period. 3-of-3 required.

**Why 40% not 30%.** The iron condor has defined maximum loss per cycle: `wing_width − net_premium`. At 16Δ/5Δ strikes (≈$17 wing width, ≈$4.50 premium), max per-cycle loss is ≈$12.50/share. At 20% NAV notional, a single maximum-loss cycle = 20% × ($12.50/$4.50) / ($560/share) = approximately 10% NAV per cycle in the worst case. A 40% drawdown cap corresponds to roughly 4 consecutive worst-case cycles — a severe but survivable scenario. The 30% cap from Substrate #7 was calibrated for unlimited-loss ETP strategies; the iron condor's defined risk warrants the adjusted bound.

**2011 debt-ceiling stress period excluded.** 2011-07 → 2011-10 falls entirely within IS. Gate 5 is an OOS-only test (evaluating the strategy as designed against real OOS data, not IS fitting). The 2011 event informs IS strategy development but is not an OOS gate.

**Coverage classification.** If a trial has zero entries during a stress period (VRP filter blocks all entries), the period is classified as NO_DATA for that trial. Gate 5 requires 3-of-3 COVERED periods to pass. A trial with 2 COVERED + 1 NO_DATA is evaluated on 2-of-2 coverage only — not penalized for NO_DATA, but not given credit for surviving a period it never traded.

### 6.6 Gate 6 — Cornish-Fisher Sharpe > 0.5

Inherited from Substrate #7 §5.6. Monthly return series over OOS-A + OOS-B combined. CF-Sharpe (Favre & Galeano 2002) must exceed 0.5 in both OOS-A and OOS-B independently.

---

## 7. Cost Model

**Options-specific. Fundamentally different from the ETP cost model in Substrate #7.**

### 7.1 Baseline Transaction Costs

Per **cycle** (one open + one close/roll of a 4-leg iron condor), per contract (= 100 SPY shares):

```
Bid-ask cost:     4 legs × 2 transactions × $0.08/share × 100 = $64/contract
Commission:       8 fills × $0.65/fill = $5.20/contract
Total per cycle:  $69.20/contract
```

**As a percentage of premium collected:** At typical VIX=20, 30 DTE, 16Δ/5Δ condor on SPY≈$560:
- Net premium ≈ $4.50/share × 100 = $450/contract
- Cost as % of premium: $69.20 / $450 ≈ **15.4%**

This is a high cost fraction — much higher than the ~2-5% typical for equity factor strategies. It is intentionally honest. For the strategy to survive Gate 4, it must earn enough premium to cover 2× this cost stack.

**Position sizing at 20% NAV on a $1M portfolio:**
- NAV notional = $200,000
- One contract notional = SPY × 100 = ~$56,000
- Number of contracts ≈ $200,000 / $56,000 ≈ 3 contracts
- Total cost per cycle ≈ 3 × $69.20 = $207.60 ≈ 0.021% of NAV

### 7.2 Gate 4 Stress — Doubled Costs

Bid-ask doubled to $0.16/share, commission unchanged ($0.65/fill). Total per cycle per contract = $128 + $5.20 = $133.20. As % of premium ≈ 29.6%.

### 7.3 Stress Period Cost Widening

During pre-committed stress periods (2008 crisis, 2018 Volmageddon, 2020 COVID), SPY options bid-ask widens by 3-5×. Baseline bid-ask cost multiplied by **3×** during these windows. Commission unchanged.

### 7.4 No Cash Carry

Free cash earns 0% in this model. Per Substrate #7 §17.8 ADDENDUM (cash-carry zeroing finding), carry on uninvested cash produces degenerate results and is not credited. The strategy's return is entirely from options P&L net of costs.

---

## 8. Residualization — Four-Factor Model (inherited from Substrate #7 §7)

Post-portfolio time-series OLS of monthly strategy returns on four factors + constant intercept. HC0 (White 1980) standard errors. Alpha intercept t-stat > 1.96 (two-sided p < 0.05) required.

**Factor 1: SPY monthly return** — equity market beta.
**Factor 2: ΔVIX monthly** — direct vol exposure.
**Factor 3: Short-term reversal factor** — Kenneth French's daily ST-Rev factor (monthly aggregated).
**Factor 4: Carry proxy** — FRED 3-month T-bill monthly change.

Same falloff condition as §7: if any factor is unavailable for a window, residualization reports as provisional with the available subset and notes the missing factor explicitly.

---

## 9. Phase 1 — Signal Research

**Objective:** Confirm that the Substrate #7 Phase 1 finding (VRP IC +0.180 at h=21) is meaningful in the options context. OOS remains sealed.

**Phase 1 for Substrate #9 is abbreviated** relative to prior substrates because:
- Substrate #7 Phase 1 already validated the VRP signal at h=21 with IC +0.180 across full IS data
- The 6-trial set is derived from the Substrate #7 Phase 1 survivors (VRP > 2% threshold family outperformed VRP > 0 family in #7 Phase 1)
- Phase 1 here validates that the iron condor P&L is positively correlated with the VRP signal in the IS window

### 9.1 Phase 1 Analysis

For each IS monthly cycle (2004-01 → 2014-12):
- Compute VRP_t at entry date
- Compute iron condor cycle P&L for T1 (base trial, 16Δ/5Δ, no filter) using the §4 B-S reconstruction
- Compute Pearson correlation between VRP_t and cycle_pnl

**Phase 1 pass criterion (applies to T1 only — Phase 1 does not run on all 6 trials):**
- Correlation between VRP and cycle P&L > 0 in IS
- Positive sign in at least 7 of 11 IS calendar years
- NOT concentrated exclusively in 2008-2009 (positive in at least 5 of IS years ex-2008/09)

If T1 fails Phase 1, ALL 6 trials close FAILED at Phase 1. The trial set is structured so that T1 (base, no filter) is the most permissive version — if it doesn't pass IS, the more restrictive variants won't either.

### 9.2 Phase 1 Exit Rule

T1 passes or CLOSED FAILED at Phase 1. No partial advancement.

---

## 10. Phase 2 — Strategy Specification

**Objective:** Freeze the exact iron condor execution specification before any OOS data is touched.

### 10.1 Position Sizing

```
contracts = floor(NAV × SIZING_FRACTION / (SPY_close × 100))

where:
    SIZING_FRACTION = 0.20        (20% of NAV notional, frozen — no search)
    NAV             = current portfolio value in dollars
    SPY_close × 100 = notional per contract
```

Minimum: 1 contract. If `NAV × 0.20 / (SPY × 100) < 1`, the cycle is skipped (insufficient capital to trade at minimum size). This is recorded as a NO_FILL for the cycle, not a loss.

**VIX auto-deleverage (pre-committed):** When VIX ≥ 30 on the entry date (for trials without a VIX < 30 filter), halve the sizing: `SIZING_FRACTION = 0.10`. This is NOT a new trial variant — it is a risk management rule applied uniformly to trials T1, T2, T4, and T5. Trials T3 and T6 (VIX < 30 filter) skip the cycle entirely above VIX=30 rather than halving.

### 10.2 Entry Protocol

On the first trading day of each monthly cycle:
1. Compute VRP_t. Apply VRP filter per trial spec.
2. If VRP filter passes: compute Δ-targeted strikes per §4.2.
3. Compute net BS premium per §4.3.
4. If net premium ≤ 0: skip cycle (degenerate pricing — no trade).
5. Record entry: date, S, VIX, K_put_long, K_put_short, K_call_short, K_call_long, premium, contracts.

### 10.3 Exit Protocol

**Standard roll (21 DTE):** On the trading day when 9 calendar days remain to expiry, compute cost_to_close per §4.3 using current S and VIX. Record cycle_pnl = premium − cost_to_close − transaction_costs.

**Intraday stop-loss (hard stop, pre-committed):** If SPY intraday moves > 3× the cycle's expected daily realized vol (estimated as VIX_entry / √252 × 3), close the position immediately at closing prices. This protects against gap events (Flash Crash, Volmageddon). The stop-loss triggers are evaluated once per day at market open using prior-day data — no intraday monitoring modeled (conservative for backtesting).

**VIX spike stop (pre-committed):** If VIX on any day during the cycle rises > 40% from the cycle's entry-day VIX, close immediately. Same threshold as Substrate #7 §9.3.

**Expiry (if not rolled or stopped):** At expiry, compute payoff per §4.3 and deduct from premium.

### 10.4 Hedge Variant

**This substrate runs ONE variant (no hedge).** The iron condor's long wings ARE the hedge — the 5Δ options limit maximum loss to wing_width − premium. There is no separate "hedged vs unhedged" axis because the defined-risk structure is intrinsic to the strategy.

Running a separate "naked strangle" variant (no long wings) would be a distinct strategy with unlimited tail risk. This is not pre-committed and would require a separate substrate.

---

## 11. Phase 3 — Full Gauntlet

**Objective:** Run all six gates on OOS-A + OOS-B for each of the 6 trials. Honest verdict.

**Implementation:** `gauntlet/run_gauntlet.py` (to be built in Phase 3 session). Must:
1. Refuse to execute unless SHA-256 of this document matches anchor in `research/SUBSTRATE9_PHASE0_CERTIFIED.md`
2. Run all 6 trials independently (no cross-trial information sharing)
3. Evaluate all 6 gates + residualization for each trial
4. Write `research/GAUNTLET_RESULTS.json` (machine output) + `research/GAUNTLET_VERDICT.md` (human verdict)

**Phase 3 output — per trial, per gate:**
- Baseline OOS-A Sharpe, OOS-B Sharpe
- DSR-A, DSR-B
- G1-G6 pass/fail per OOS window
- Residualization alpha t-stat
- DEPLOY-READY flag (all 6 gates + residualization pass in both OOS windows)

**Stress period coverage:** Report whether each stress period is COVERED, PARTIAL, or NO_DATA for each trial. Gate 5 evaluation is on COVERED periods only.

---

## 12. Phase 4 — IBKR Paper Trading (Survivor-Conditional)

Only triggered if Phase 3 produces at least one DEPLOY-READY trial.

**Infrastructure:** IBKR paper trading account (opened 2026-05-26). `ib_insync` Python API connecting to TWS/IB Gateway running locally. Iron condor orders as 4-leg combo orders (IBKR native multi-leg support).

**Paper trading period:** minimum 60 trading days (≈ 3 monthly option cycles).

**Go/no-go for real capital:**
- Live Sharpe within ±1 SE of Phase 3 Sharpe over the paper period.
- No Gate 5 drawdown breach during paper period.
- No intraday stop or VIX spike stop triggered more than once (confirms the stop-loss rule doesn't over-fire).
- Founder approval (real-capital decision, not a methodology decision).

---

## 13. Decision Matrix

| Phase 1 T1 | Phase 3 | Outcome |
|---|---|---|
| T1 fails | n/a | CLOSED FAILED at Phase 1 |
| T1 passes | 0 of 6 trials pass all 6 gates | CLOSED FAILED at Phase 3 |
| T1 passes | ≥1 trial passes G1-G4 but fails G5 or G6 | CONDITIONAL — documented, not deployable |
| T1 passes | ≥1 trial passes all 6 gates | DEPLOY-READY → Phase 4 |
| Phase 4 passes | — | Founder-approval gate for real capital |
| Phase 4 fails | — | Substrate closed |

---

## 14. Timeline (Wall-Clock Estimate)

| Day | Deliverable |
|-----|-------------|
| 1 | SUBSTRATE9_DESIGN.md committed (this doc). Phase 0 data verification. `SUBSTRATE9_PHASE0_CERTIFIED.md` filed with SHA anchor. |
| 2 | Build `ingest/bs_pricer.py` (B-S pricer, delta-targeting, premium computation). Build Phase 1 analysis for T1. Phase 1 verdict. |
| 3 | Build `gauntlet/backtest.py` (cycle-based, monthly, 6 trials). Build `gauntlet/stats.py` (reuse from Substrate #7 where possible). |
| 4 | Build `gauntlet/run_gauntlet.py` (SHA-anchored master runner). Run Phase 3. Write verdict. |
| 5 | IBKR TWS setup + `execution/ibkr_broker.py` scaffold (Phase 4 plumbing, only if Phase 3 DEPLOY-READY). |

Timeline is wall-clock estimate. Microstructure (#4) retains first-call priority on the Mumbai machine data accumulation; this substrate runs on a separate compute path (no shared I/O).

---

## 15. Known Limitations — Pre-Committed Before Research Runs

### 15.1 Black-Scholes flat-surface bias (conservative)
BS ignores the vol smile. OTM options are more expensive in reality than BS predicts. The bias direction is declared in §4.4: conservative (understates net premium collected → understates strategy P&L). A near-miss should not be promoted on the grounds of this bias. A borderline fail is a fail.

### 15.2 No intraday fill simulation
The backtest uses daily closing prices and closing VIX for all entries, exits, and rolls. Real execution has intraday timing risk. The gap between "open the condor at the open" vs "open at the close" can be material on high-vol days. This is a known source of overstatement for the backtest.

### 15.3 SPY options vs SPX options
SPY options are American-style (early assignment risk). SPX options are European-style (cash-settled, no assignment). The backtest does not model early assignment — it uses European-style payoff functions. For deep-in-the-money situations near expiry, this could understate losses. In practice, early assignment risk on SPY iron condors is low (long wings cap the ITM depth), but it is a non-zero risk not captured.

### 15.4 Single-name vs index basis
The VIX measures SPX implied vol. SPY options have their own implied vol surface, which differs slightly from VIX (typically ±0.5-1.5 vol points). Using VIX as the σ input for SPY option pricing introduces a small systematic bias. Direction is ambiguous.

### 15.5 Options liquidity crisis risk
In extreme events (2008, 2020), options markets can become illiquid — wide bid-ask, no fills at quoted prices. The 3× cost widening in §7.3 models this partially but not fully. Real slippage in March 2020 on SPY options was occasionally 5-10× normal.

### 15.6 Capital below minimum contract threshold
The backtest records NO_FILL cycles when NAV × 0.20 < SPY × 100 (< 1 contract). For small NAV, this biases the return series — the strategy sits flat in favorable markets rather than participating. This is a realistic limitation for small-account implementations.

### 15.7 Interaction with Microstructure #4
This substrate is entirely independent of Microstructure (#4). They use different data, different brokers (IBKR vs Binance), and different time horizons. No shared state.

---

## 16. Hard Rules — What Cannot Be Modified Post-Phase-1

Frozen at Phase 1 start (T1 analysis completes). Any edit constitutes peeking and invalidates the gauntlet.

1. **Trial set §5.** All 6 trials. No additions. No silent drops. Errors count as fails.
2. **B-S reconstruction methodology §4.** Flat surface, VIX as σ, delta-targeting formula — frozen.
3. **Substrate window + splits §3.** Boundaries and embargo unchanged.
4. **Gate criteria §6.** DSR > 0.95, bootstrap threshold, sign-agreement, cost-doubling factor, 40% drawdown bound, 3-of-3 covered stress periods, CF-Sharpe > 0.5 — all frozen.
5. **Cost model §7.** Bid-ask, commission, Gate 4 doubling factor, 3× stress widening — frozen.
6. **Sizing §10.1, entry §10.2, exit §10.3.** All frozen. VIX auto-deleverage rule is part of this and is frozen.
7. **Residualization §8.** Four-factor model, HC0 SEs, t-stat threshold — frozen.
8. **Decision matrix §13.** Outcome categories frozen.

Permitted post-Phase-1 edits (audit-friendly only):
- Typo corrections.
- **ADDENDUM** sections that document in-place engineering discoveries that change implementation but NOT the substantive contract. Any addendum must be labeled, dated, and SHA-256-anchored separately.

---

## 17. SHA-256 Anchor

The Phase 0 orchestrator and Phase 3 master runner will refuse to execute unless the SHA-256 of this file matches the anchor recorded in `research/SUBSTRATE9_PHASE0_CERTIFIED.md`.

Anchor recorded: see `SUBSTRATE9_PHASE0_CERTIFIED.md` (filed at Phase 0 close).

**Date:** 2026-05-26.
