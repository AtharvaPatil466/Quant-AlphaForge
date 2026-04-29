# AlphaForge

**A quantitative alpha research platform built as the foundational stack for a future hedge fund.**

AlphaForge is an end-to-end system for discovering, validating, and trading equity signals — spanning data infrastructure, factor research, multi-agent reinforcement learning, portfolio optimization, and live execution. The distinguishing feature is not the strategies; it's the statistical discipline applied to evaluating them.

> **Current status:** Executing *Tier 1 — Methodology Validation*. A binary gate determines whether any signal in this universe survives a deflation-aware, cost-honest gauntlet. If none does, the writeup documents that honestly. See [TIER1_STATUS.txt](TIER1_STATUS.txt) for the full plan.

---

## What This Project Demonstrates

### 1. Survivorship-Bias-Free Universe Construction
Built a **point-in-time S&P 500 membership log** (2010–2026) by walking 2,811 Wikipedia revisions, parsing multi-format constituent tables across 15 years of wikitext format drift, and resolving corporate identity via SEC EDGAR CIK numbers. The result: **837 membership events** (407 removals, 352 additions, 78 renames) validated against 12 hand-verified spot-check fixtures and cross-checked against an independent Wikipedia changes table (84% match). [Design memo →](alphaforge-python/data/market/PIT_UNIVERSE_DESIGN.md)

### 2. Honest Statistical Evaluation
Every factor goes through the same gauntlet:
- **Information Coefficient** analysis with decay curves at 5 horizons
- **Quintile-spread long-short backtest** with square-root market impact, Corwin-Schultz bid-ask spread, and borrow fees
- **Deflated Sharpe Ratio** (Bailey & López de Prado, 2014) across the full trial set — DSR > 0.95 required
- **Hansen SPA** (2005) and **White's Reality Check** (2000) for data-snooping adjustment
- **Purged + embargoed k-fold CV** (López de Prado, 2018) to prevent label leakage
- **Sector-neutral variant** and **held-out OOS window** with 21-day embargo

### 3. Architecturally Correct Backtesting
The event-driven backtest engine enforces no-look-ahead (raises on future data access), no same-bar fills (requires next-bar timestamps), and per-fill cash costs. This is a deliberate architectural constraint, not just good practice — the engine makes it physically impossible to write a backtest with the most common biases.

### 4. Multi-Agent RL with Honest Self-Assessment
Neuroevolution (NSGA-II) + PPO + MAML + HMM regime detection. The rigor report's headline finding: **0% of agents beat equal-weight on the same window.** This is reported honestly, not hidden. The absolute Sharpe of ~1 is entirely beta to a bull market. [Rigor report →](alphaforge-marl/research/out/marl_rigor_report.md)

### 5. Production Execution Infrastructure
Live paper trading via Alpaca with a 6-trigger kill switch (drawdown, single-day loss, consecutive losing days, slippage drift, cumulative fill-error drag, liquidity) and a 3-stage unwind ladder. Re-arming requires a human `ACK:` — no automated recovery from blowups. *Currently paused* pending Tier 1 validation.

---

## Architecture

```
alphaforge-python/          Research engine — the intellectual core
  data/                       PRNG, synthetic data, real-market parquet store
  data/market/pit/            Point-in-time S&P 500 universe (Phase 1)
  factors/                    11 alpha factors with BaseFactor ABC + registry
  backtest/                   JS-parity synthetic demo + event-driven engine
  backtest/event_driven/      Canonical no-look-ahead backtest engine
  optimizer/                  Markowitz mean-variance (SLSQP, Ledoit-Wolf)
  research/                   Factor study, capacity study, TSMOM, pairs, FF5
  strategies/                 Time-series momentum, cointegration pairs
  api/                        FastAPI serving all of the above

alphaforge-marl/            Multi-agent RL framework
  env/                        Gymnasium TradingEnv (57-dim obs, 5/10 actions)
  agents/                     ActorCritic, PPO, MAML, DQN, Ensemble
  evolution/                  NSGA-II, speciation, adaptive mutation
  bandit/                     HMM regime detector + Thompson sampling
  research/                   Rigor report, ablation ladder

alphaforge-execution/       Live paper trading [PAUSED]
  execution/                  Daily loop, Broker ABC, Paper + Alpaca
  risk/                       Pre-trade limits, circuit breakers, kill switch
  strategy/                   Momentum composite, MARL strategy bridge

index.html + *.js           Vanilla JS frontend (no build step, 5 tabs)
```

---

## Quickstart

```bash
git clone <this-repo> alphaforge && cd alphaforge

# Install each sub-project's deps
cd alphaforge-python   && pip install -r requirements.txt && cd ..
cd alphaforge-marl     && pip install -r requirements.txt && cd ..
cd alphaforge-execution && pip install -r requirements.txt && cd ..

# Run the full test matrix (~750 tests across 3 sub-projects)
make tests

# Populate the market-data parquet store (one-off, ~15 min)
cd alphaforge-python && python3 sync_market_data.py && cd ..

# Rebuild every headline research report from deterministic seeds
make all
```

---

## Research Results — Honest Summary

The [factor study report](alphaforge-python/research/out/factor_study_report.md) evaluated 11 cross-sectional factors and 2 portfolio strategies. Key findings:

1. **Momentum (12-1) is the only signal with a clean IC decay curve**, rising from +0.019 at h=1 to +0.043 at h=63.
2. **Transaction costs destroy short-horizon factors.** Mean Reversion, Volume Surge, RSI, and Earnings Drift have net Sharpes that are negative after costs.
3. **Even Momentum does not clear the deflation bar.** Net Sharpe is +0.11 with DSR = 0.14 — far below the 0.95 threshold.
4. **Equal-weight beats every factor overlay** at Sharpe +0.92. The universe's beta is the dominant return source.
5. **MARL agents show zero excess Sharpe over equal-weight** — the absolute Sharpe of ~1 is entirely market beta.

**This is the expected result on a narrow, mega-cap-survivorship-biased universe.** The Tier 1 plan re-runs everything on the PIT S&P 500 with FF5 residualization to test whether alpha exists after stripping style exposure.

---

## Factors

| Factor | Formula | Horizon | Source |
|---|---|---|---|
| Momentum (12-1) | `p[t-21] / p[t-252] − 1` | 12 months | Jegadeesh & Titman (1993) |
| Mean Reversion (5d) | `−(p[t] / p[t-5] − 1)` | 5 days | Lo & MacKinlay (1990) |
| Volume Surge | `(vol5 − vol20) / vol20` | 20 days | Campbell et al. (1993) |
| RSI Divergence | `(RSI14 − 50) / 50` | 14 days | Wilder (1978) |
| Earnings Drift | 10-day return proxy | 10 days | Ball & Brown (1968) |
| Low Volatility | `−σ(returns, 60)` | 60 days | Baker et al. (2011) |
| Amihud Illiquidity | `mean(\|r\| / $vol, 20) × 10⁶` | 20 days | Amihud (2002) |
| Idiosyncratic Volatility | `−σ(residual, 60)` | 60 days | Ang et al. (2006) |
| Residual Reversal (5d) | `−Σ residual_t` | 5 days | Blitz et al. (2011) |
| Risk-Managed Momentum | `mom_12_1 / σ_63` | 12 months | Barroso & Santa-Clara (2015) |
| Long-Horizon Reversal | `−(p[t-21] / p[t-1029] − 1)` | 48 months | De Bondt & Thaler (1985) |

Time-series momentum (Moskowitz, Ooi & Pedersen, 2012) and cointegration pairs trading (Gatev, Goetzmann & Rouwenhorst, 2006) are evaluated as portfolio-level strategies.

---

## Reproducibility

Every headline artifact is regenerable from the local parquet store:

```bash
make all              # rebuild all research reports
make factor-study     # single-factor gauntlet only
make capacity-study   # AUM curve + regime + crowding
make marl-rigor       # MARL trial deflation
make tests            # full test matrix
```

Deterministic seeds are documented in [SEEDS.md](SEEDS.md). The [CI workflow](.github/workflows/research-ci.yml) runs the full test matrix and diffs headline metrics against committed JSON on every push.

---

## Honest Limitations

1. **Survivorship bias** (legacy 50-name universe — being replaced by PIT S&P 500 in Tier 1)
2. **No borrow-fee heterogeneity** — flat 25 bp/yr general collateral
3. **No TAQ-calibrated impact** — square-root k = 15 bps is a literature default
4. **No fundamentals** — value/quality factors approximated from OHLCV
5. **226/881 ever-member tickers have no yfinance data** — delisted/restructured gaps
6. **MARL shows no alpha over equal-weight** — paused pending Tier 1 outcome

These are explicitly documented, not hidden. Fixing 1–4 requires data subscriptions (CRSP/Norgate, IBKR stock loan, TAQ) outside the scope of a public repo.

---

## Documentation

| Document | Purpose |
|---|---|
| [TIER1_STATUS.txt](TIER1_STATUS.txt) | Master plan + phase progress for the hedge-fund-seed validation |
| [RESEARCH_WRITEUP.md](RESEARCH_WRITEUP.md) | Full research narrative and methodology |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design and technical architecture |
| [LESSONS_LEARNED.md](docs/LESSONS_LEARNED.md) | Engineering lessons from building a PIT universe from scratch |
| [PIT_UNIVERSE_DESIGN.md](alphaforge-python/data/market/PIT_UNIVERSE_DESIGN.md) | 634-line design contract for the S&P 500 universe reconstruction |
| [ENGINE_CONSOLIDATION_DESIGN.md](alphaforge-python/backtest/ENGINE_CONSOLIDATION_DESIGN.md) | Design memo for backtest engine consolidation |
| [SEEDS.md](SEEDS.md) | Per-component deterministic seed manifest |

---

## Not Financial Advice

This is a research project, not a trading recommendation. Live paper trading is for methodology validation only. See [LICENSE](LICENSE).
