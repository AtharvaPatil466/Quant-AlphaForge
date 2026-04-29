# AlphaForge — Research Methodology & Results

*A deflation-aware, cost-honest evaluation of equity signals on the S&P 500.*

**Author:** Atharva Patil
**Date:** April 2026
**Status:** Tier 1 Phase 3 in progress; legacy results on 50-name universe reported below. PIT S&P 500 re-run pending FF5 residualization gate.

---

## 1. Thesis

Thirty years of cross-sectional asset pricing research has documented a short list of signals with apparent predictive power for equity returns: momentum, short-term reversal, volume-based measures, volatility anomalies, and post-earnings drift. A parallel literature in portfolio construction (time-series momentum, statistical arbitrage via cointegration) offers structurally different return profiles.

**The question this project tries to answer is not "do these signals work?" — it's narrower and harder:**

> On a specific universe, with a specific cost model, after deflating for the full number of signals tested, does any single or combined signal produce a Sharpe ratio whose 95% confidence interval excludes zero on held-out data?

This is a high bar. Most published research does not clear it. The purpose of this document is to report the methodology and results honestly, whether they pass or fail.

---

## 2. Universe

### 2.1 Legacy Universe (Results Below)

50 US large-caps spanning Technology, Healthcare, Finance, Consumer, and Energy. Today's survivors — AAPL, MSFT, NVDA, JPM, etc. Adjusted OHLCV from yfinance, stored as parquet. Period: 2016-01-04 → 2025-12-31 (~2,500 trading days). First 252 days consumed as warmup for the 12-month momentum lookback.

**Known bias:** This universe exhibits survivorship bias. Every name in it is a company that has survived and grown over the study period. Long-only baselines are biased upward by an estimated 1–2% per year compared to a point-in-time universe.

### 2.2 PIT Universe (Tier 1 — In Progress)

Point-in-time S&P 500 membership reconstructed from Wikipedia revision history and SEC EDGAR CIK data. 837 membership events (2010–2026), 881 ever-member tickers, 655 with OHLCV on disk. Monthly return correlation 0.9895 vs the S&P 500 Equal Weight Index. See [LESSONS_LEARNED.md](docs/LESSONS_LEARNED.md) for the engineering details.

All Tier 1 Phase 4–6 work will use this universe exclusively. Legacy results are reported below for completeness but are not the basis for any capital-allocation claim.

---

## 3. Signals Evaluated

### 3.1 Cross-Sectional Factors (11)

| # | Factor | Formula | Horizon | Academic Source |
|---|---|---|---|---|
| 1 | Momentum (12-1) | `p[t-21] / p[t-252] − 1` | 12 mo | Jegadeesh & Titman (1993) |
| 2 | Mean Reversion (5d) | `−(p[t] / p[t-5] − 1)` | 5 d | Lo & MacKinlay (1990) |
| 3 | Volume Surge | `(vol5 − vol20) / vol20` | 20 d | Campbell, Grossman & Wang (1993) |
| 4 | RSI Divergence | `(RSI14 − 50) / 50` | 14 d | Wilder (1978) |
| 5 | Earnings Drift | 10-day return proxy | 10 d | Ball & Brown (1968) |
| 6 | Low Volatility | `−σ(returns, 60)` | 60 d | Baker, Bradley & Wurgler (2011) |
| 7 | Amihud Illiquidity | `mean(|r| / $vol, 20) × 10⁶` | 20 d | Amihud (2002) |
| 8 | Idiosyncratic Vol | `−σ(residual, 60)` vs EW market | 60 d | Ang, Hodrick, Xing & Zhang (2006) |
| 9 | Residual Reversal | `−Σ residual_t, t ∈ last 5d` | 5 d | Blitz, Huij, Lansdorp & Verbeek (2011) |
| 10 | Risk-Managed Mom | `mom_12_1 / σ_63` | 12 mo | Barroso & Santa-Clara (2015) |
| 11 | Long-Horizon Reversal | `−(p[t-21] / p[t-1029] − 1)` | 48 mo | De Bondt & Thaler (1985) |

Factors 8 and 9 residualize returns against an equal-weight market return in a 60-day rolling regression. This produces zero scores in the single-ticker fallback (by construction).

### 3.2 Portfolio-Level Strategies (2)

| Strategy | Construction | Source |
|---|---|---|
| **Time-Series Momentum (TSMOM)** | Per-ticker sign × vol-target sizing. Monthly rebalance. | Moskowitz, Ooi & Pedersen (2012) |
| **Pairs Trading** | Engle-Granger cointegration scan. ADF < −2.5. Z-score entry ±2.0, exit ±0.5, stop ±4.0. | Gatev, Goetzmann & Rouwenhorst (2006) |

### 3.3 MARL (Multi-Agent Reinforcement Learning)

Neuroevolution (NSGA-II) + PPO + MAML + HMM regime bandit. Evaluated separately with its own trial-count deflation. See [MARL Rigor Report](alphaforge-marl/research/out/marl_rigor_report.md).

---

## 4. Cost Model

### 4.1 Factor Study (Flat Model — For Cross-Factor Comparability)

All factors share the same cost model so results are directly comparable:

| Component | Value |
|---|---|
| Commission | 1 bp per dollar traded |
| Half-spread | 2 bp |
| Linear impact | 10 bp per unit of rebalance turnover |
| **Total per round-trip** | **~26 bp** (varies with turnover) |

### 4.2 Capacity Study (Square-Root Impact — For AUM Claims)

For the best-performing factor, the capacity study uses a more realistic cost model:

| Component | Formula | Source |
|---|---|---|
| Market impact | 15 bp × √(order_size / ADV_20d) | Almgren & Chriss (2000) |
| Bid-ask spread | Corwin-Schultz High/Low estimator | Corwin & Schultz (2012) |
| Borrow fee (short leg) | 25 bp/yr general collateral | Market convention |

The capacity curve reports net Sharpe at AUM = $1M, $10M, $100M, $1B, $10B. The "capacity" is the largest AUM where the Sharpe 95% CI still excludes zero.

---

## 5. Statistical Methodology

### 5.1 Information Coefficient (IC)

Daily cross-sectional Spearman rank correlation between factor score and forward return at horizons h ∈ {1, 5, 10, 21, 63} days. A factor with a stable, positive IC t-statistic at h ≥ 21 is the minimum bar for a monthly-rebalanced signal.

### 5.2 Quintile-Spread Backtest

At each monthly rebalance (every 21 trading days): rank all tickers by factor score, long the top quintile, short the bottom quintile, equal-weight within each leg. Portfolio held constant between rebalances. Transaction costs applied per dollar of turnover.

### 5.3 Deflated Sharpe Ratio (DSR)

*Bailey & López de Prado (2014).* Accounts for the fact that the highest Sharpe among K factors is an order statistic whose expected value under the null is positive even when no signal exists.

SR₀ (the expected maximum Sharpe under the null) is computed from the number of trials K, the length of the return series T, and the skewness/kurtosis of the return distribution. DSR is the probability that the true Sharpe exceeds zero after this deflation.

**Threshold: DSR > 0.95.**

### 5.4 Hansen's Superior Predictive Ability (SPA) Test

*Hansen (2005).* Null: no model in the candidate set has positive expected performance after accounting for the fact that we selected the best one ex-post.

Uses stationary-bootstrap (mean block length 21 days, 2,000 reps) to build the distribution of the studentized maximum across K candidates. Hansen's recentering (each candidate's resampled mean shifted by max(mean, 0)) provides tighter power than White's Reality Check.

**SPA p < 0.05 means at least one candidate shows performance that cannot be explained by data-snooping.**

### 5.5 White's Reality Check (RC)

*White (2000).* Same framework as SPA but with naive observed-mean recentering. Strictly more conservative than SPA — harder to reject. Reported alongside SPA as a robustness check.

### 5.6 Purged + Embargoed K-Fold CV

*López de Prado (2018).* Standard cross-validation leaks information when forward-return labels overlap across training folds. Purge removes training samples whose label window (H days) touches the test fold. Embargo drops a buffer of samples (1% of total) after each test fold.

Configuration: 5 folds, 21-day purge (= label horizon), 1% sample embargo. A naive IC that is inflated relative to its CV counterpart is evidence of label leakage in the study design.

### 5.7 Sector-Neutral Variant

Each factor panel is evaluated after within-sector cross-sectional demean at every rebalance date. The resulting portfolio has zero expected sector tilt. Any Sharpe that survives this operation is not a sector bet.

### 5.8 Held-Out OOS Split

`OOS_START = 2024-01-02` with a 21-day calendar embargo. No parameter, formula, or threshold in this study was chosen using any post-2023 data.

---

## 6. Results (Legacy 50-Name Universe)

### 6.1 IC Decay

| Factor | h=1 | h=5 | h=10 | h=21 | h=63 |
|---|---|---|---|---|---|
| Momentum (12-1) | +0.019 (t=3.0) | +0.021 (t=3.3) | +0.024 (t=4.0) | +0.030 (t=5.2) | +0.043 (t=7.5) |
| Mean Reversion (5d) | −0.003 (t=−0.7) | −0.007 (t=−1.4) | −0.004 (t=−0.9) | −0.006 (t=−1.3) | −0.001 (t=−0.3) |
| Volume Surge | +0.008 (t=2.1) | +0.008 (t=2.2) | +0.002 (t=0.5) | −0.002 (t=−0.6) | −0.001 (t=−0.4) |
| RSI Divergence | +0.010 (t=2.1) | +0.012 (t=2.5) | +0.014 (t=3.0) | +0.007 (t=1.4) | +0.009 (t=2.1) |
| Earnings Drift | +0.003 (t=0.5) | +0.005 (t=1.0) | +0.007 (t=1.4) | +0.004 (t=0.8) | +0.000 (t=0.1) |

**Finding:** Momentum (12-1) is the only factor with an IC that rises monotonically across horizons — the textbook signature of a genuine medium-horizon signal. All other factors decay to noise by h=21.

### 6.2 Net-of-Cost Long-Short Performance

| Factor | Net Sharpe | Bootstrap 95% CI | DSR | Ann. Return | Max DD | Turnover |
|---|---|---|---|---|---|---|
| Momentum (12-1) | +0.11 | [−0.47, +0.73] | 0.14 | −0.48% | −48.2% | 0.94 |
| Mean Reversion (5d) | −0.79 | [−1.35, −0.23] | 0.00 | −16.5% | −88.1% | 3.10 |
| Volume Surge | −0.86 | [−1.53, −0.20] | 0.00 | −13.0% | −78.5% | 3.30 |
| RSI Divergence | −0.53 | [−1.26, +0.16] | 0.00 | −11.7% | −71.2% | 3.19 |
| Earnings Drift | −0.37 | [−0.92, +0.16] | 0.00 | −9.4% | −64.8% | 3.15 |

### 6.3 Baselines

| Baseline | Sharpe | Ann. Return | Max DD |
|---|---|---|---|
| Equal-weight long-only (50 names) | **+0.92** | +17.3% | −37.5% |
| Random long-short (mean of 100 seeds) | +0.01 | — | — |
| Random long-short (95% CI) | [−0.47, +0.52] | — | — |

### 6.4 Key Takeaways

1. **No factor clears the deflation bar.** The best (Momentum, DSR = 0.14) is far below the 0.95 threshold. The bootstrap CI spans zero.

2. **Transaction costs are the dominant destroyer.** Short-horizon factors (Mean Reversion, Volume Surge, RSI, Earnings Drift) have gross Sharpes that are weakly positive but turn sharply negative after costs due to ~3× monthly turnover vs Momentum's ~0.9×.

3. **Equal-weight dominates.** On this universe, in this period, the market's beta is the dominant return source. No factor overlay adds credible alpha.

4. **Momentum shows textbook regime dependency.** Low-vol regime: Sharpe +0.76. High-vol regime: Sharpe −0.20. Consistent with Daniel & Moskowitz (2016) on momentum crashes.

5. **MARL shows zero excess Sharpe.** Across 100 generation-level trials, 0% of agents beat equal-weight. The absolute Sharpe of ~1 reported in training logs is entirely market beta. See the [MARL Rigor Report](alphaforge-marl/research/out/marl_rigor_report.md).

---

## 7. What These Results Mean

This is **not** a negative result in the sense that the methodology is wrong. It's the expected result given:

- **50 tickers.** Quintile buckets of 10 names produce noisy cross-sectional rankings. Most factor studies use 500–3,000 names.
- **Survivorship bias.** Today's winners inflate the long-only baseline, making it harder for any overlay to add value.
- **No risk-model neutralization.** Factor returns contain style exposure (beta, sector, size) that inflates gross IC but washes out in cost-adjusted long-short.
- **Modern mega-caps during a bull market.** The 2016–2025 period is dominated by a handful of mega-cap technology stocks. Cross-sectional dispersion is compressed.

**The Tier 1 plan addresses all four of these:**

| Issue | Tier 1 Fix | Phase |
|---|---|---|
| Small universe | PIT S&P 500 (881 ever-members) | Phase 1 ✅ |
| Survivorship bias | Point-in-time membership | Phase 1 ✅ |
| No risk neutralization | FF5 + UMD residualization | Phase 3 🔨 |
| Compressed dispersion | Wider universe + sector-neutral | Phase 4 ⬜ |

---

## 8. Honest Limitations

1. **Survivorship bias (legacy results).** The 50-name universe is today's survivors. Point-in-time membership (Phase 1) addresses this for future results.

2. **No borrow-fee heterogeneity.** A flat 25 bp/yr general-collateral fee is used. Real borrow fees on non-mega-cap names are 100–1,000 bp and can render short-leg alpha negative.

3. **Cost model is one-parameter.** The square-root k = 15 bp is a literature default. TAQ-calibrated impact would make the capacity curve calibration-grade rather than plausible.

4. **No fundamentals.** Value and quality factors are approximated with OHLCV proxies (Long-Horizon Reversal). A real value factor needs book-to-market, earnings yield, or profitability data — which is being staged for Phase 3 via a local characteristics table.

5. **Trials beyond this study.** DSR deflates for the 11 factors tested here. The broader search (MARL hyperparameters, reward mixes, ablations) is a much larger trial set. The MARL rigor report deflates against its own trial count separately.

6. **226 missing tickers in the PIT universe.** Delisted/restructured companies without yfinance data. Phase 4–5 must treat these as known data gaps.

---

## 9. Reproducibility

Every result in this document is regenerable:

```bash
export ALPHAFORGE_GLOBAL_SEED=42
make all        # rebuilds all reports from the local parquet store
make tests      # 750 tests across 3 sub-projects
```

Deterministic seeds are documented in [SEEDS.md](SEEDS.md). The GitHub Actions [CI workflow](.github/workflows/research-ci.yml) runs the full test matrix and diffs headline metrics against committed JSON on every push, catching silent numerical drift from dependency changes.

---

## 10. What Comes Next

### Phase 3 (In Progress): FF5 Residualization
Build Fama-French 5 + UMD factors from the PIT universe. Validate each against Ken French's published returns (target correlation > 0.85). Residualize all factor returns against this risk model so we measure alpha, not style exposure.

### Phase 4: Single-Factor Gauntlet
Re-run all 11 factors on PIT S&P 500 with residualized returns. Apply Hansen SPA, Deflated Sharpe, purged CV, and two non-overlapping OOS windows. A signal must survive both windows.

### Phase 5: Factor Combination
IC-weighted ensemble or Markowitz overlay with factor-blended expected returns. Turnover-penalized construction. Sector + beta neutralization. Capacity number under the square-root impact model. Full gauntlet on the combined signal.

### Phase 6: The Decision
If the gate passes: LP-grade research memo, live paper trading of the survivor signal, Tier 2 planning.

If the gate fails: equally rigorous failure memo documenting what was tested, what didn't survive, and what the failure tells us about the inefficiency space. This document is the credibility artifact regardless of outcome.

---

## References

- Almgren, R. & Chriss, N. (2000). Optimal execution of portfolio transactions. *Journal of Risk*, 3(2), 5–39.
- Amihud, Y. (2002). Illiquidity and stock returns. *Journal of Financial Markets*, 5(1), 31–56.
- Ang, A., Hodrick, R. J., Xing, Y. & Zhang, X. (2006). The cross-section of volatility and expected returns. *Journal of Finance*, 61(1), 259–299.
- Bailey, D. H. & López de Prado, M. (2014). The Deflated Sharpe Ratio. *Journal of Portfolio Management*, 40(5), 94–107.
- Baker, M., Bradley, B. & Wurgler, J. (2011). Benchmarks as limits to arbitrage: Understanding the low-volatility anomaly. *Financial Analysts Journal*, 67(1), 40–54.
- Ball, R. & Brown, P. (1968). An empirical evaluation of accounting income numbers. *Journal of Accounting Research*, 6(2), 159–178.
- Barroso, P. & Santa-Clara, P. (2015). Momentum has its moments. *Journal of Financial Economics*, 116(1), 111–120.
- Blitz, D., Huij, J., Lansdorp, S. & Verbeek, M. (2011). Short-term residual reversal. *Journal of Financial Markets*, 16(3), 477–504.
- Campbell, J., Grossman, S. & Wang, J. (1993). Trading volume and serial correlation in stock returns. *Quarterly Journal of Economics*, 108(4), 905–939.
- Corwin, S. A. & Schultz, P. (2012). A simple way to estimate bid-ask spreads from daily high and low prices. *Journal of Finance*, 67(2), 719–760.
- Daniel, K. & Moskowitz, T. (2016). Momentum crashes. *Journal of Financial Economics*, 122(2), 221–247.
- De Bondt, W. F. & Thaler, R. (1985). Does the stock market overreact? *Journal of Finance*, 40(3), 793–805.
- Fama, E. F. & French, K. R. (1993). Common risk factors in the returns on stocks and bonds. *Journal of Financial Economics*, 33(1), 3–56.
- Gatev, E., Goetzmann, W. N. & Rouwenhorst, K. G. (2006). Pairs trading: Performance of a relative-value arbitrage rule. *Review of Financial Studies*, 19(3), 797–827.
- Hansen, P. R. (2005). A test for superior predictive ability. *Journal of Business & Economic Statistics*, 23(4), 365–380.
- Harvey, C. R., Liu, Y. & Zhu, H. (2016). …and the cross-section of expected returns. *Review of Financial Studies*, 29(1), 5–68.
- Hou, K., Xue, C. & Zhang, L. (2020). Replicating anomalies. *Review of Financial Studies*, 33(5), 2019–2133.
- Jegadeesh, N. & Titman, S. (1993). Returns to buying winners and selling losers. *Journal of Finance*, 48(1), 65–91.
- Lo, A. W. & MacKinlay, A. C. (1990). When are contrarian profits due to stock market overreaction? *Review of Financial Studies*, 3(2), 175–205.
- López de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley.
- Moskowitz, T. J., Ooi, Y. H. & Pedersen, L. H. (2012). Time series momentum. *Journal of Financial Economics*, 104(2), 228–250.
- White, H. (2000). A reality check for data snooping. *Econometrica*, 68(5), 1097–1126.
- Wilder, J. W. (1978). *New Concepts in Technical Trading Systems*. Trend Research.
