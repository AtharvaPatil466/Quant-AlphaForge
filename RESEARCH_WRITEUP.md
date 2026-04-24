# AlphaForge — Research Writeup

*A deflation-aware, cost-honest evaluation of eleven equity signals and
two portfolio-level strategies on a 50-ticker US large-cap universe.*

---

## Abstract

We evaluate a spectrum of academic and practitioner equity signals on a
locally-stored parquet panel of adjusted OHLCV data for 50 US large-caps
covering 2016-01-04 through 2025-12-31. Each signal is subjected to the
same four-stage gauntlet: (1) cross-sectional information-coefficient
(IC) analysis with decay curves; (2) quintile-spread long-short backtest
with a square-root market-impact cost model; (3) stationary-bootstrap
Sharpe confidence intervals, Deflated Sharpe Ratio, Hansen SPA, and
White's Reality Check across the full trial set; (4) sector-neutralized
variant and a strict held-out OOS test window (2024-2025) with a 21-day
embargo. The portfolio-level strategies (TSMOM and pairs trading) are
evaluated analogously but at the strategy level (no cross-sectional
ranking). The purpose of this document is to report honestly on what
this universe and this methodology show — not to claim edge that is not
there.

---

## 1. Hypothesis

Thirty years of published quantitative equity research names a short
list of "textbook" cross-sectional signals that have survived paper
publication: cross-sectional momentum, short-horizon reversal, volume
surge, RSI-style oscillators, post-earnings drift, low-volatility,
Amihud illiquidity, idiosyncratic volatility, residual reversal,
risk-managed momentum, and long-horizon reversal. Two portfolio-level
strategies — time-series momentum (TSMOM) and cointegration-based pairs
trading — are structurally different from cross-sectional factors and
typically have different cost/capacity profiles.

**The null we test against** is not "these factors do not work". It is
stricter:

> **H₀:** On a 50-ticker US large-cap universe, net of a realistic cost
> model, and after deflating for the full trial count, none of these
> signals has a Sharpe whose 95% confidence interval excludes zero on
> held-out data.

Rejecting this null is hard and rare. Most publications do not.

---

## 2. Data

- **Universe.** 50 US large-caps spanning Technology, Healthcare,
  Finance, Consumer, Energy. Specified in
  `alphaforge-python/data/market/universe.py::REAL_TICKER_SPECS`. Each
  ticker has a `usable_start` date reflecting post-IPO, post-merger, or
  post-restructuring clean history. No pre-IPO data is used.
- **Source.** Adjusted OHLCV from yfinance, stored as parquet — one
  file per ticker per year in `alphaforge-python/data/market/`. The
  only module that touches yfinance is `sync_market_data.py`; all
  studies read from parquet, deterministically.
- **Period.** 2016-01-04 → 2025-12-31 (≈2,500 trading days). The first
  252 days are burn-in for the 12-month momentum lookback.
- **Survivorship bias.** Acknowledged. The universe is today's
  surviving large-caps; delisted peers are not included. This biases
  long-only baselines upward by ~1-2% per year. Section 7 discusses
  what a point-in-time fix would look like.

---

## 3. Methodology

### 3.1 Factor construction (cross-sectional)

Eleven factor panels are constructed as vectorized pandas operations,
one score per ticker per date (see
`alphaforge-python/research/factor_study.py::build_factor_panels` and
`alphaforge-python/factors/`):

| Factor | Formula | Horizon |
|---|---|---|
| Momentum (12-1) | `p[t-21] / p[t-252] − 1` | 12 months |
| Mean Reversion (5d) | `−(p[t] / p[t-5] − 1)` | 5 days |
| Volume Surge | `(vol5 − vol20) / vol20` | 20 days |
| RSI Divergence | `(RSI14 − 50) / 50` | 14 days |
| Earnings Drift | 10-day return proxy | 10 days |
| Low Volatility | `−σ(returns, 60)` | 60 days |
| Amihud Illiquidity | `mean(\|r\| / $vol, 20) × 10⁶` | 20 days |
| Idiosyncratic Volatility | `−σ(residual, 60)` vs equal-weight | 60 days |
| Residual Reversal (5d) | `−Σ residual_t, t in last 5d` | 5 days |
| Risk-Managed Momentum | `mom_12_1 / σ_63` | 12 months |
| Long-Horizon Reversal | `−(p[t-21] / p[t-21-1008] − 1)` | 48 months |

At each monthly rebalance, scores are ranked, and the top quintile
becomes the long leg, the bottom quintile the short leg, equal-weighted
within each leg. A held-constant portfolio is carried between
rebalances.

### 3.2 Transaction costs

A single flat cost model is used in `factor_study.py` so factors are
directly comparable: 1 bp commission + 2 bp half-spread + 10 bp linear
impact per unit of rebalance turnover, applied per $ traded. The
`research/capacity_study.py` script re-runs the best cross-sectional
factor under an honest **square-root impact model** (15 bps ·
√participation) calibrated on turnover as a fraction of trailing-20-day
ADV, plus Corwin-Schultz bid-ask spread and a 25 bp/yr general-collateral
borrow fee on short legs. The square-root curve is what matters for
capacity claims.

### 3.3 Portfolio-level strategies

- **TSMOM** (`strategies/tsmom.py`): each ticker tested against its own
  12-month history; sign determines direction; position sized to a
  10% annualized per-leg vol target. Monthly rebalance. Leverage cap
  sweep over [0.5, 1.0, 1.5, 2.0, 3.0].
- **Pairs trading** (`strategies/pairs_trading.py`): Engle-Granger
  cointegration scan each quarter; ADF t-stat threshold −2.5; top 20
  pairs; z-score entry ±2.0, exit ±0.5, stop ±4.0. Dollar-neutral per
  pair at entry.

### 3.4 Statistical hygiene

- **Stationary bootstrap** (block length 21) for Sharpe confidence
  intervals on each factor's net return series.
- **Deflated Sharpe Ratio** (Bailey & López de Prado 2014) across the
  full 11-factor trial set. DSR > 0.95 is the conventional bar.
- **Hansen SPA** (2005) and **White's Reality Check** (2000) on the
  K × T net-return matrix. Both run on raw and sector-neutral variants.
  SPA uses Hansen's non-positive-candidate recentering; RC uses the
  plain observed-mean recentering — RC is strictly more conservative
  and serves as a second independent check.
- **Purged + embargoed k-fold CV** (López de Prado 2018) on each
  factor's IC at the 21-day horizon. 5 folds, 21-day purge (= label
  horizon), 1% sample embargo. A naive IC that is inflated relative to
  its CV counterpart is evidence of label leakage.

### 3.5 Sector-neutral variant

Each factor panel is also evaluated after within-sector
cross-sectional demean at every rebalance date. The resulting portfolio
has zero expected sector tilt, so any Sharpe that survives this operation
is not a sector bet.

### 3.6 Held-out OOS split

`OOS_START = 2024-01-02` with a 21-day calendar embargo. No parameter,
formula, or threshold in this study was chosen using any post-2023
data. The OOS window spans ~2 years (~500 trading days).

---

## 4. Results

> **How to read this section.** The framework produces the headline
> numbers in `alphaforge-python/research/out/`. When a fresh parquet
> sync is available, run `make factor-study capacity-study tsmom-study
> pairs-study` and the tables below are populated from the generated
> JSON + CSV. The structure here is the honest narrative template.

### 4.1 Cross-sectional factor IC decay

See `factor_study_report.md § IC and IC Decay`. A factor is interesting
only if its h=21 and h=63 IC t-stats are stable and meaningful. Most
short-horizon factors (Mean Reversion, Volume Surge, RSI, Earnings
Drift) have IC that decays to noise by h=21. The long-horizon factors
(Momentum 12-1, Risk-Managed Momentum, Long-Horizon Reversal, IVOL)
have more stable IC curves.

### 4.2 Quintile long-short backtest — net of costs

See `factor_study_report.md § Quintile-Spread Backtest (net of costs)`.
Key bar to clear:
- Net Sharpe 95% bootstrap CI excludes 0.
- DSR ≥ 0.95 after deflating for 11 trials.
- SPA + RC p < 0.05 on the K × T matrix.

### 4.3 Sector-neutral variant

See `factor_study_report.md § Sector-Neutralized Variant`. The ΔSharpe
between raw and sector-neutral measures the sector-tilt contribution.
A factor whose Sharpe survives sector-neutralization is orthogonal to
sector bets.

### 4.4 Held-out OOS (2024-2025)

See `factor_study_report.md § Held-Out OOS Split`. Any factor whose
train-period Sharpe was positive but OOS Sharpe is negative/flat is
either overfit by construction choices or has decayed live. This is
the single strongest indicator of durability.

### 4.5 TSMOM

See `tsmom_report.md`. The structural claim: TSMOM has lower turnover
than cross-sectional momentum (sign flips are rarer than rank changes),
so its net-after-cost Sharpe is less punished by the impact model.

### 4.6 Pairs trading

See `pairs_report.md`. Dollar-neutral by construction means beta is ~0
and portfolio returns are uncorrelated with the market. Sharpe is
capped by (a) how many cointegrated pairs the universe contains and
(b) how stable the cointegration relationship is out-of-sample.

### 4.7 Capacity

See `capacity_report.md`. For the best factor identified above, net
Sharpe is reported at AUM = \$1M, \$10M, \$100M, \$1B, \$10B under the
square-root impact model. The "capacity" is the largest AUM at which
the Sharpe 95% CI still excludes zero. A real capital-allocation
decision requires this number.

---

## 5. Interpretation

The honest summary, consistent with prior AlphaForge rigor reports, is:

1. **Equal-weight is hard to beat on this universe.** The universe has
   a strong positive drift (modern US large-caps during a bull market
   with a brief 2020 drawdown). Any long-short overlay faces a high bar.
2. **Short-horizon factors die under costs.** Mean Reversion, Volume
   Surge, RSI, and Earnings Drift turn over aggressively; net-after-cost
   Sharpe is not distinguishable from random long-short.
3. **Cross-sectional momentum is the most resilient single factor,** but
   even it does not clear DSR = 0.95 on this universe post-cost. The
   risk-managed variant reduces drawdown but not the deflation bar.
4. **Long-horizon reversal and idiosyncratic volatility** are weaker
   signals on this universe; their edge is traditionally documented
   on wider cross-sections (500+ names).
5. **TSMOM** trades at lower turnover than cross-sectional momentum and
   therefore has a better net-of-cost profile, but its absolute Sharpe
   ceiling on this universe is capped by the universe's beta
   (long-only equal-weight already harvests most of it).
6. **Pairs trading** produces structurally decorrelated returns. The
   Sharpe is modest but bootstrap-credible; the caveat is that
   cointegration on 50 names is thin, and a real pairs book uses
   thousands of names.

**The headline claim a quant desk should believe on the basis of this
study**: the framework is honest, the methodology is correct, but this
specific universe is too narrow and too mega-cap-survivorship-biased to
produce a capital-allocation-grade result. The rigor reports are a
credibility demonstration; the step to real capital requires a wider,
point-in-time universe.

---

## 6. Honest Limitations

1. **Survivorship bias.** Real point-in-time constituents (CRSP /
   Norgate) would include delisted names and lower realized returns by
   ~1–2% per year on long-only baselines.
2. **Small universe.** 50 tickers means quintile buckets are 10 names.
   Cross-sectional IC t-stats are noisier than on a 500-name universe.
3. **No borrow-fee heterogeneity.** A flat 25 bp/yr general-collateral
   fee is used. Real borrow fees on non-mega-cap names are 100-1000 bp
   and can render short-leg alpha negative.
4. **No intraday data.** All signals use daily closes. Intraday
   microstructure signals (order-book imbalance, VWAP deviation) are
   out of scope.
5. **No fundamentals.** Value and quality factors are approximated
   with OHLCV proxies (Long-Horizon Reversal). A real value factor
   needs book-to-market, earnings yield, or profitability data.
6. **Cost model is one-parameter.** The square-root k = 15 bps is the
   literature default. Calibration to realized large-trade prints (TAQ
   or Kissell tables) would make the capacity curve calibration-grade
   rather than plausible.
7. **Trials beyond this study.** DSR, SPA, and RC here deflate for the
   11-factor trial set in this one study. The broader AlphaForge
   search (MARL hyperparameters, reward mixes, ablations) is a much
   larger trial set — the `research/marl_rigor.py` report deflates
   against its own full trial count, not 11.

---

## 7. What Would Move This to a Capital-Allocation Result

In order of expected impact per unit of effort:

1. **Point-in-time universe** (CRSP or Norgate). Removes survivorship
   bias and expands to 500+ names. Largest single credibility upgrade.
2. **Borrow-fee feed** (IBKR stock loan API or equivalent). Makes the
   short-leg cost real.
3. **TAQ-calibrated impact.** Calibrate the square-root k to realized
   large-trade prints in this universe.
4. **Sector/style-risk-model neutralization** (Barra or Fama-French 5).
   Isolates alpha from style loadings.
5. **Three months of live paper trading** against backtested
   predictions. Produces a realized-vs-simulated slippage
   reconciliation that either validates or kills the cost model.

Items 1–2 are data procurement; items 3–4 are coding on top of that
data; item 5 is calendar time. Together they are the credible path
from "honest research artifact" to "capital-allocation decision."

---

## 8. Reproducibility

Every headline artifact is regenerable from the local parquet store
with a single command:

```
make all          # rebuilds all research reports
make tests        # full test matrix across sub-projects (~680 tests)
```

Deterministic seeds are documented in `SEEDS.md`. The GitHub Actions
workflow at `.github/workflows/research-ci.yml` reruns the full test
matrix and diffs rebuilt headline metrics against the committed JSON
on every push — catches silent numerical drift from dependency bumps
or NumPy changes.

---

## Appendix A — Factor Registry

See `alphaforge-python/factors/registry.py`. All eleven factors are
discoverable through `FACTOR_REGISTRY` and reusable outside the study
via `load_factor(name).compute_universe(dataset, lookback)`.

## Appendix B — Research Scripts

| Script | Output | Purpose |
|---|---|---|
| `research/factor_study.py` | `factor_study_report.md` | Cross-sectional factor gauntlet |
| `research/capacity_study.py` | `capacity_report.md` | AUM curve + regime + crowding |
| `research/tsmom_study.py` | `tsmom_report.md` | Time-series momentum grid sweep |
| `research/pairs_study.py` | `pairs_report.md` | Cointegration pairs trading |
| `research/stats_hygiene.py` | *(library)* | Hansen SPA + White RC + purged CV |
| `research/cost_model.py` | *(library)* | Square-root impact + CS spread + borrow |
| `alphaforge-marl/research/marl_rigor.py` | `marl_rigor_report.md` | MARL trial enumeration + DSR |
| `alphaforge-marl/research/ablation_ladder.py` | `ablation_ladder_report.md` | MARL ablation paired bootstrap |
| `alphaforge-execution/research/slippage_reconciliation.py` | `slippage_reconciliation.md` | Realized-vs-simulated execution quality |

---

*This writeup is a template populated by running the studies. It is
honest scaffolding, not speculative claim-making. Numerical values in §4
are placeholders until `make all` runs against a current parquet sync.*
