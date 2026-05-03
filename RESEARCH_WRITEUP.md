# AlphaForge — Final Research Methodology & Verdict

*A deflation-aware, cost-honest evaluation of equity signals on the S&P 500.*

**Author:** Atharva Patil  
**Date:** May 2026  
**Status:** **CLOSED FAILED**. Tier 1 and Tier 2 methodology validation concluded with 0 surviving strategies. The project is currently on a 30-day cooldown before any substrate pivot.

---

## 1. Thesis & Objective

Thirty years of cross-sectional asset pricing research has documented a short list of signals with apparent predictive power for equity returns: momentum, short-term reversal, volume-based measures, volatility anomalies, and post-earnings drift. 

**The question this project tried to answer was not "do these signals work?" — it was narrower and harder:**

> On a point-in-time universe, with a realistic cost model, and after residualizing against the standard factor model, does any single or combined signal produce a Sharpe ratio whose 95% confidence interval excludes zero and survives multiple-testing deflation (DSR > 0.95) on held-out data?

This is a high bar. The purpose of this document is to honestly report the methodology, what we used, and why every tested strategy failed this gauntlet.

---

## 2. Infrastructure & Data Used

### 2.1 Point-in-Time S&P 500 Universe
The single largest defect in typical factor studies is survivorship bias. We reconstructed a **point-in-time S&P 500 membership log** by walking 2,811 Wikipedia revisions and enriching them with SEC EDGAR CIK data.
- **Output:** 837 membership events (2010–2026).
- **Coverage:** 476 tickers × 2,514 trading days from 2016-01-04 to 2025-12-31, using yfinance OHLCV data. 

### 2.2 Risk Model Residualization (FF5 + UMD)
Every Information Coefficient (IC) and Sharpe Ratio in the final evaluation was computed on **Fama-French 5 + Momentum (UMD) residualized returns**.
- We built a local replica of the FF5+UMD factors to validate against Ken French's published returns.
- Returns were residualized using a no-look-ahead 252-day rolling OLS regression.
- **Why:** To ensure we were measuring true *alpha*, not just static beta or style exposures (e.g., small-cap or value tilts).

---

## 3. Signals & Combinations Evaluated

We tested **9 cross-sectional factors** and **4 portfolio-level combination strategies**.

### 3.1 Base Factors
1. **Momentum (12-1)**: Trailing 12-month return excluding the most recent month.
2. **Mean Reversion (5d)**: Inverse of 5-day return.
3. **Volume Surge**: Short-term vs long-term volume moving average.
4. **RSI Divergence**: Standard 14-day RSI minus 50.
5. **Earnings Drift**: 10-day return proxy.
6. **Low Volatility**: Inverse realized 60-day volatility.
7. **Amihud Illiquidity**: Absolute return divided by dollar volume.
8. **Idiosyncratic Volatility**: Residual volatility against an EW market proxy.
9. **Residual Reversal (5d)**: 5-day mean reversion residualized against the market.

### 3.2 Combinations (Phase 5)
1. **EWE**: Equal-Weight Ensemble of all 9 factors.
2. **ICW**: IC-Weighted Ensemble.
3. **ICW-flip**: Sign-corrected IC-Weighted Ensemble.
4. **MV**: Markowitz Mean-Variance overlay with covariance-aware weights frozen on the training window.

---

## 4. The Statistical Gauntlet & Cost Model

Every strategy had to survive a strict evaluation pipeline:

- **Cost Model:** 1 bp commission, 2 bp half-spread, and 10 bp linear impact per unit of turnover.
- **Stationary-Bootstrap Sharpe CI:** 2,000 reps, mean block 21 days.
- **OOS Windows:** Two strictly held-out, non-overlapping windows: **OOS-A (2022–2023)** and **OOS-B (2024–2025)**.
- **Deflated Sharpe Ratio (DSR):** Deflated against the full 24-trial set to account for multiple testing.

**The Binary Gate:** To pass, a strategy required DSR > 0.95, a bootstrap 95% CI excluding zero, and sign agreement across *both* OOS windows.

---

## 5. Tier 1 Results: How We Failed

**Headline:** 0 of 9 single factors and 0 of 4 combination strategies cleared the gate.

### 5.1 Single Factors Destroyed
Once evaluated on the PIT universe with FF5+UMD residualized returns and realistic costs, **every single factor produced a negative full-period Sharpe**. The alpha seen in early raw-return tests was entirely beta/style exposure.

### 5.2 The MV Combination False Hope
The Markowitz (MV) combination yielded highly positive alpha-residual OOS Sharpes: **+3.06 in OOS-A** and **+2.43 in OOS-B**. 
- The alpha was statistically significant (t > 3).
- The signal was genuinely orthogonal to FF5+UMD (R² < 16%).
- Its mechanism was "short everything": placing negative weights on 8 of the 9 structurally decaying factors.

**However, it failed the deflation gate.** The DSR landed at 0.92 in OOS-A and 0.70 in OOS-B, falling short of the 0.95 hurdle. 

**Tier 1 Diagnosis:** We hypothesized this was a Row 2 failure: *"Real signal, eaten by costs and multiple-testing deflation."* The logic was that the 21-day turnover was too high, destroying the otherwise valid alpha.

---

## 6. Tier 2 Verdict: Why We Failed

Tier 2 was designed specifically to test the Tier 1 hypothesis: if the MV signal was real but killed by turnover, lowering the rebalance frequency should preserve or amplify the alpha (since cost drag scales linearly with turnover).

We tested the MV recipe at **quarterly (63-day)** and **semi-annual (126-day)** rebalance horizons. 

**The result conclusively falsified the hypothesis:**

| Strategy | OOS-A α-residual | OOS-B α-residual |
|---|---:|---:|
| MV-21 (Tier 1 baseline) | **+3.06** | **+2.43** |
| MV-63 | +0.79 | +1.97 |
| MV-126 | +0.95 | +0.11 |

Lowering the turnover **destroyed the alpha**. 

### 6.1 The Final Conclusion
The MV-21 alpha was not a robust cross-sectional anomaly trapped behind a cost wall. It was a **fragile, short-horizon-specific phenomenon** (likely a 21-day residualized mean-reversion artifact) that completely failed to transport to longer horizons or survive rigorous statistical deflation.

The combination of rigorous residualization, a point-in-time universe, honest transaction costs, and multiple-testing deflation left exactly zero alpha from this entire class of textbook cross-sectional signals.

---

## 7. What Comes Next

AlphaForge succeeded as a **methodology and infrastructure validation**. The framework correctly identified that the signals lacked true edge, preventing the deployment of capital into an overfitted strategy.

**Project Status:**
With the failure of the Tier 2 gate on 2026-05-02, the project entered a mandatory 30-day cooldown (until 2026-06-01) per the failure-path pre-commit. No new equity factors, strategies, or MARL runs will be attempted.

The next step is a **Substrate Change Memo** to evaluate whether the founder path should pivot to a new asset class (futures, crypto) or a new frequency (microstructure, event-driven), building upon the robust statistical gauntlet developed here.
