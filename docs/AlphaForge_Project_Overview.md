# AlphaForge

An End-to-End Quantitative Research and Execution Stack

Point-in-time event-driven backtesting, deflation-aware statistical evaluation, evolutionary multi-agent reinforcement learning, and live paper-trading execution — applied across ten pre-committed substrates spanning US equities, crypto perpetual futures, BTC microstructure, EDGAR-driven post-earnings drift, NSE event-driven flow, CBOE variance-risk-premium harvest, SPY iron-condor options, and Kalshi prediction markets.

**Status (2026-06-19):** Eight substrate evaluations have CLOSED FAILED under the project's pre-committed gauntlet. Substrate #10 (Kalshi favorite-longshot bias) is Phase-1 INCONCLUSIVE (underpowered on free data) and is now accumulating a live forward paper-trade record; substrate #4 (BTC-USDT microstructure) is re-collecting Phase 0 book data after a stale-collector break. The June 2026 work added a canonical, version-pinned evaluation gauntlet (`afgauntlet`) and a power calibration that measures the gauntlet's own minimum detectable effect (MDE@80% ≈ 2.4 annualized Sharpe at 28 trials over 5-year windows) — separating ‘no alpha’ from ‘instrument too blunt’. The methodology has rejected every signal that does not survive honest deflation, including one with statistically significant raw alpha (MV-21 OOS Sharpe +3.06 / +2.43) and one with a clear underlying variance-risk-premium IC of +0.180.

- **SUBSTRATES INITIATED** — **10** across 6 asset classes
- **CLOSED FAILED** — **8** under DSR-deflated gates
- **OPEN** — **2** #4 recollecting · #10 forward
- **TESTS GREEN** — **1,000+** across 11 sub-projects
- **CROSS-SECTIONAL FACTORS** — **9** 5 JS-parity + 4 Python-only
- **PIT EVENT LOG** — **837** S&P 500 membership changes
- **PARQUET COVERAGE** — **16y** equity OHLCV, daily
- **INDIA SUBSTRATE** — **7.76M** NSE rows, 2004–2026

---

**Repository:** *Quant Alpha* · **Generated:** 2026-06-19 · **Build:** `make overview` (pandoc)

---

#### Abstract

AlphaForge applies the full systematic-trading lifecycle — data ingestion, factor construction, point-in-time event-driven backtesting, transaction-cost modelling, deflation-aware statistical evaluation, multi-agent reinforcement learning, and live paper-trading execution — to a series of pre-committed substrates of increasing methodological distinctness. Across **ten initiated substrates** (US equities Tier 1 + Tier 2, Binance USDT-M crypto carry, BTC-USDT microstructure, EDGAR XBRL post-earnings drift, NSE event-driven flow, CBOE variance-risk premium, a follow-up VIX-baseline-anchored sizing study, SPY iron-condor options, and Kalshi prediction-market favorite-longshot bias), **eight have CLOSED FAILED** under the same five-to-six gate gauntlet: Deflated Sharpe > 0.95, stationary-bootstrap 95% CI excludes zero, out-of-sample sign agreement, cost-doubling survival, regime-stress stability, and (for premium-harvest substrates) Cornish-Fisher Sharpe > 0.5 with max-drawdown limit per stress period. Substrate #10 is Phase-1 INCONCLUSIVE (underpowered on free data) and is accumulating a live forward paper-trade record; substrate #4 is re-collecting Phase 0 data. The June 2026 work consolidated the per-substrate statistics into one canonical, version-pinned gauntlet (`afgauntlet`, with binary/calibration extensions for prediction markets), added a power calibration that measures the gauntlet's own minimum detectable effect, and reconciled assumed vs realized transaction costs from live fills. The project's contribution is the methodology and infrastructure that produced these honest negative results: a research-grade stack that refuses to deploy capital against signals which do not survive multiple-testing deflation, no-look-ahead enforced by the type system (`BarHistory` raises if queried past `as_of`), per-fill cash-accounted commission and slippage, and a kill-switch-driven live execution loop currently halted by configuration.

## Contents

| § | Section |
|---|---|
| 1 | Executive Summary |
| 2 | Project Architecture — Eleven Components |
| 3 | Data Infrastructure — PIT Universes and Parquet Stores |
| 4 | Alpha Engine — Factors, Scoring, and Event-Driven Backtest |
| 5 | Statistical Methodology — The Gauntlet |
| 6 | Transaction-Cost Modelling — Honest Frictions |
| 7 | MARL Framework — Neuroevolution + PPO + MAML |
| 8 | Live Execution — Daily Loop, Risk, and Kill Switch |
| 9 | JavaScript Frontend — Parity-Tested Terminal UI |
| 10 | Substrate #1–2 — US Equity Tier 1 and Tier 2 (CLOSED FAILED) |
| 11 | Substrate #3 — Crypto USDT-M Carry (CLOSED FAILED) |
| 12 | Substrate #4 — BTC-USDT Microstructure (IN FLIGHT) |
| 13 | Substrate #5 — PEAD via EDGAR XBRL (CLOSED FAILED) |
| 14 | Substrate #6 — NSE Event-Driven + Flow (CLOSED FAILED) |
| 15 | Substrate #7 — CBOE Variance-Risk Premium (CLOSED FAILED) |
| 16 | Substrate #8 — VIX-Baseline-Anchored Sizing (CLOSED FAILED) |
| 17 | Failure-Mode Taxonomy — What the Verdicts Mean Together |
| 18 | Engineering Highlights — Tests, Parity, CI, Reproducibility |
| 19 | Honest Limitations and Process Disclosures |
| 20 | June 2026 Update — Substrates #9–#10, Gauntlet + MDE |
| 21 | Forward Path — The Strategy-Class Decision Window |

## 1. Executive Summary

**Headline.** AlphaForge is a working end-to-end systematic-trading research stack — not a single strategy. It has been used to evaluate ten pre-committed substrates against the same rigorous gauntlet; eight have CLOSED FAILED, substrate #10 (Kalshi favorite-longshot bias) is Phase-1 inconclusive and accumulating a live forward record, and substrate #4 (microstructure) is re-collecting Phase 0 book data. The infrastructure has detected and rejected signals that would pass naive statistical bars: the closest near-miss (a Markowitz overlay on nine factor return streams) produced alpha-residual OOS Sharpe **+3.06 / +2.43** with HC0 t-statistics 4.33 / 3.43 and FF5+UMD R² 16% / 8% — statistically significant under any conventional bar, but failing the Deflated Sharpe hurdle (0.92 / 0.70 vs 0.95) once honestly penalised against the 24-trial search space.

**What the project does.** Eight things, all working: (1) constructs a true point-in-time S&P 500 membership graph from Wikipedia revisions + EDGAR CIK enrichment, 837 events across 2010–2026; (2) loads aligned OHLCV from a local Parquet store, 16 years of daily history for 655 of 881 ever-member tickers; (3) computes nine cross-sectional alpha factors, four pre-committed linear combinations, and a Markowitz mean-variance overlay; (4) runs all signals through an event-driven backtest engine that architecturally enforces no-look-ahead (`BarHistory` raises past `as_of`), next-bar fills (`ExecutionHandler` rejects same-bar fills), and per-fill cash-accounted costs; (5) applies the statistical gauntlet (DSR, SPA, Reality Check, purged-embargoed K-fold, stationary bootstrap, FF5+UMD post-portfolio alpha residualisation) to every variant; (6) trains a multi-agent RL ensemble (NSGA-II + PPO + FOMAML + HMM regime bandit) on the same substrate and audits it against the same gauntlet; (7) operates a daily live-trading loop against Alpaca paper with a six-trigger kill-switch and three-stage unwind ladder; and (8) extends every layer to four further substrates (crypto, microstructure, PEAD, India, VIX) each with their own SHA-256-anchored pre-commit contract.

**What the project demonstrates.** That a methodologically honest research process can produce credible *negative* verdicts at scale, and that the absence of surviving signals is itself a scientifically informative outcome. Across ten substrates, six asset classes, and two strategy classes (predictive cross-sectional alpha and structural premium harvest), no construction within the tested parameter space — using free public data, parametric retail-grade cost models, and DSR deflation against pre-committed trial counts — produces a deployable signal. The methodology did its job; the data and constraint set did theirs.

#### At-a-Glance Substrate Ledger

| # | Substrate | Asset class | Strategy class | Outcome | Date |
|---|---|---|---|---|---|
| 1 | Equity Tier 1 | US large-cap | X-section factor | CLOSED FAILED | 2026-05-02 |
| 2 | Equity Tier 2 | US large-cap | Lower-turnover X | CLOSED FAILED | 2026-05-02 |
| 3 | Crypto USDT-M Carry | Crypto perp | X-section funding | CLOSED FAILED | 2026-05-15 |
| 4 | BTC-USDT Microstructure | Crypto spot L2 | Order-flow | PHASE 0 (recollect) | in flight |
| 5 | PEAD via EDGAR XBRL | US large-cap | Event-driven | CLOSED FAILED | 2026-05-17 |
| 6 | NSE Event-Driven + Flow | Indian equity | Flow / delivery % | CLOSED FAILED | 2026-05-20 |
| 7 | CBOE VIX/VRP harvest | US vol | Premium harvest | CLOSED FAILED | 2026-05-21 |
| 8 | VIX-baseline-anchored sizing | US vol | Premium harvest | CLOSED FAILED | 2026-05-21 |
| 9 | SPY Iron-Condor Options | US options | Premium harvest | CLOSED FAILED | 2026-05-26 |
| 10 | Kalshi Favorite-Longshot | Prediction mkt | Calibration / FLB | PH1 INCONCL. | 2026-06-17 |

#### Platform Metrics

- **11 sub-projects.** JS frontend, `alphaforge-python`, `-marl`, `-execution`, `-crypto`, `-microstructure`, `-pead`, `-india`, `-vix`, `-options`, `-prediction`, plus the shared `alphaforge-gauntlet` evaluation package. Each has its own CLAUDE.md, test suite, and SHA-256-anchored design contract.
- **1,000+ tests green.** incl. 531 `alphaforge-python`, 237 `-vix`, 371 `-india`, 157 `-prediction`, 86 `alphaforge-gauntlet`, plus -marl / -execution / -crypto / -pead / -microstructure / -options suites.
- **837 PIT membership events.** 407 REMOVE + 352 ADD + 78 RENAME, built from 2,811 Wikipedia revisions + EDGAR CIK enrichment, validated to 0.9895 monthly correlation against `^SP500EW`.
- **16 years of equity OHLCV** in `data/quarantine/market/`, 655 of 881 PIT ever-members on disk; 5 years of Binance USDT-M funding + OHLCV; 7.76M NSE bhavcopy rows (2004–2026, 5,527 dates) with 100% delivery-percentage coverage on Nifty-500 ever-members.
- **Architectural no-look-ahead enforcement.** `BarHistory` raises if asked for any row past its `as_of`; `ExecutionHandler` rejects fills whose timestamp is not strictly later than the originating order. PIT enforced by the type system, not by reviewer vigilance.
- **End-to-end reproducibility.** `make all` rebuilds every headline research artefact (factor study, capacity study, MARL rigor, ablation ladder) from the Parquet store in ~5 minutes. GitHub Actions diffs rebuilt JSON against committed artefacts to catch silent numerical drift.

## 2. Project Architecture — Eleven Components

AlphaForge is organised as eleven loosely-coupled sub-projects plus the shared `alphaforge-gauntlet` evaluation package. The equity factor / RL / execution surfaces are frozen; eight substrate sub-projects are CLOSED FAILED audit trails; `-prediction` (#10) is accumulating a live forward paper-trade record and `-microstructure` (#4) is re-collecting Phase 0 book data. The JS frontend remains parity-tested and connected to the Python data layer.

| Component | Status | Role |
|---|---|---|
| JavaScript Frontend | MAINTAINED | Vanilla-JS single-page terminal UI; PRNG / factor / backtest numerical parity to Python. |
| alphaforge-python | FROZEN (research) / READ-ONLY (data) | Equity factor engine, event-driven backtester, optimizer, statistical hygiene library, FastAPI. |
| alphaforge-marl | FROZEN | Neuroevolution + PPO + FOMAML population, HMM regime bandit, walk-forward validator. |
| alphaforge-execution | HALTED | Daily Alpaca paper-trading loop; `.halt` engaged; six-trigger kill-switch enforces unwind. |
| alphaforge-crypto | CLOSED | Binance USDT-M carry research (CLOSED FAILED 2026-05-15); basis-study stub not auto-activated. |
| alphaforge-microstructure | ACTIVE | Phase 0: BTC-USDT L2 + tape book-data accumulation; Phase 1–3 contracts pre-committed. |
| alphaforge-pead | CLOSED | EDGAR XBRL post-earnings drift on PIT equity substrate; 0/10 trials cleared (2026-05-17). |
| alphaforge-india | CLOSED | NSE bhavcopy + delivery-% + F&O expiry; 0/18 trials cleared, universal OOS sign inversion (2026-05-20). |
| alphaforge-vix | CLOSED | CBOE VIX/term-structure + SPY realized vol + ETPs; 0/28 in both substrates #7 and #8 (2026-05-21). |

#### Inter-component contracts

- **Equity stack.** `alphaforge-marl/env/trading_env.py` dynamically adds `alphaforge-python/` to `sys.path` and consumes the same parquet store and PIT validator. The two sub-projects share zero in-process state but are version-locked.
- **Execution stack.** `alphaforge-execution` consumes the parquet store read-only and writes orders, snapshots, and signals to SQLite. The kill-switch reads its config from `execution_config.yaml` and writes pager events to a human-acknowledgeable file.
- **Substrate isolation.** India, microstructure, PEAD, VIX, and crypto each maintain their own data flow and never touch `data/quarantine/market/`. This is a hard architectural constraint: a failed substrate cannot contaminate the next one.
- **SHA-256 anchored design contracts.** Every substrate writes its design contract before any data is looked at; the runner refuses to execute if the file's SHA mismatches. Substrate #7 anchored on SHA `54e53be9...`, #8 on `2194b7b2...`, India on `3b397262...`.

## 3. Data Infrastructure — PIT Universes and Parquet Stores

Every substrate is anchored on a local, version-controlled, network-isolated dataset. Only a small number of explicitly named scripts touch the network (one yfinance puller, one Wikipedia revision walker, one Binance public REST/WebSocket client, one NSE archive fetcher, one EDGAR Company Facts client, one CBOE/Stooq downloader). Everything downstream reads from the resulting Parquet files; training, research, and execution all run offline.

#### Point-in-Time S&P 500 universe

The `data/market/pit/` module rebuilds membership history end-to-end from public sources. It enumerates 2,811 Wikipedia revisions of the S&P 500 constituents article, applies a hybrid byte-delta plus comment-keyword filter to select 837 substantive change-events, and resolves each event through SEC EDGAR's CIK directory with a custom `.↔-` share-class normaliser. The differ enforces action-precedence (REMOVE before ADD on the same date) and runs a suspect-pair guard against same-CIK ADD/REMOVE collisions.

| Component | Description |
|---|---|
| enumerate_revisions.py | Wikipedia revision-walker; byte-delta + comment-keyword filter; 2,811 → 837 substantive events. |
| fetch_content.py | Batched-50 wikitext fetcher with retries and content-hash caching. |
| parser.py | Multi-format constituents-table parser; caption / ref-tag / header-shift defences. |
| cik.py | EDGAR ticker→CIK resolver; share-class punctuation normalisation. |
| differ.py | CIK-based ADD/REMOVE/RENAME differ; action-precedence + suspect-pair guard. |
| changes_parser.py | Parses Wikipedia's curated 'Selected changes' table for cross-check (84% agreement). |
| validator.py | Canonical `membership_on_date(events, baseline, date)→set[ticker]` accessor. |
| history.py | Membership-aware panels over `data/quarantine/market/`. |
| sector_map.py | Static ever-member ticker→sector map for sector-neutral factor studies. |

**Outputs.** `_event_log.parquet` (837 rows), `_baseline_2010-01-10.parquet` (500 tickers, revision `339455897`), per-session audit JSONs. A 12-fixture regression test (`test_pit_universe_fixture.py`) gates the construction against hand-verified spot checks. Membership is reconciled to 0.9895 monthly return correlation against the published `^SP500EW` equal-weight index.

**Coverage gap (disclosed in every metric).** 226 of 881 PIT ever-member tickers have no yfinance OHLCV — mostly delisted, restructured, or pre-IPO at the request date. Every downstream metric reports this as a known limitation; CRSP-grade data would close the gap but is outside the project's free-data budget.

#### Per-substrate data flow

| Substrate | Source | Egress | Materialisation |
|---|---|---|---|
| Equity (#1–2 + PEAD) | yfinance | `data/quarantine/market/<TICKER>/<YEAR>.parquet` | Per-ticker per-year Parquet, 655 tickers. |
| Wikipedia | Wikipedia revisions API | `data/market/pit/_event_log.parquet` | Append-only event log + sessioned audits. |
| Crypto carry | Binance public REST | `alphaforge-crypto/data/binance/` | Funding + 1m + 1d OHLCV for top-25 perps. |
| Microstructure | Binance WS + REST | `alphaforge-microstructure/data/` | 100 ms book snapshots + per-trade tape (accumulating). |
| PEAD | SEC EDGAR Company Facts | `alphaforge-pead/data/edgar/` | XBRL fact tables joined to PIT equity panel. |
| India | NSE archives | `alphaforge-india/data/` | 7.76M bhavcopy rows + MTO delivery + F&O expiry. |
| VIX/VRP | CBOE + Stooq + yfinance | `alphaforge-vix/data/` | VIX, VIX9D, VIX3M, VIX6M, SPY OHLCV, SVXY/VXX. |

## 4. Alpha Engine — Factors, Scoring, and Event-Driven Backtest

#### Factor library (nine cross-sectional signals)

| Factor | Construction |
|---|---|
| Momentum (12-1) | Trailing 12-month total return, skipping the most recent month (Jegadeesh-Titman 1993). |
| Mean Reversion (5d) | Negated 5-day return. |
| Volume Surge | Short-term volume MA divided by long-term volume MA. |
| RSI Divergence | Standard 14-day Relative Strength Index minus 50. |
| Earnings Drift | Post-earnings drift proxy (10-day return) — frontend parity factor. |
| Amihud Illiquidity | Absolute return divided by dollar volume (Amihud 2002). |
| Idiosyncratic Volatility | Negated 60-day rolling residual vol vs equal-weight market (Ang-Hodrick-Xing-Zhang 2006). |
| Residual Reversal (5d) | Negated 5-day sum of residuals against the equal-weight market. |
| Low Volatility | Negated annualised 60-day log-return standard deviation. |

Each factor implements `BaseFactor.compute()` (enhanced) and `compute_js()` (bit-for-bit parity with the JS frontend), registered through `FACTOR_REGISTRY`. Residual Reversal and Idiosyncratic Volatility additionally override `compute_universe` to compute the equal-weight market return once per call and reuse it across tickers, eliminating O(N) duplicated regressions.

#### Cross-sectional scoring pipeline

`factors/scoring.py` implements the canonical cross-sectional z-score pipeline (`compute_factor_scores_js`) shared by the optimizer, the correlation/IC harness, the JS scanner, the MARL environment, and the execution-loop strategy. The function lives outside `backtest/` so callers can score factors without pulling in the engine module. Defensive numerics (`safe_div`, `sanitize_number`, `clamp`, `validate_series`) guarantee NaN / Inf cannot propagate.

#### Linear combinations and Markowitz overlay

- **EWE.** Equal-weight ensemble of nine standardised factor scores.
- **ICW.** IC-weighted ensemble, weights estimated on an expanding IS window with strict no-look-ahead.
- **ICW-flip.** Sign-flipped ICW variant to demonstrate the directional dependence of the gauntlet result.
- **MV.** Markowitz mean-variance overlay implemented in `optimizer/` using SciPy SLSQP, Ledoit-Wolf covariance shrinkage, and factor-score-blended expected returns. Modes: long-only, long-short, market-neutral. *MV-21 was the closest near-miss in Tier 1 — alpha-residual OOS Sharpe +3.06 / +2.43, killed by DSR deflation (0.92 / 0.70 vs 0.95).*

#### Event-driven backtest engine

`alphaforge-python/backtest/event_driven/` implements an event-driven simulation engine that replaces the legacy vectorised panel engine retired in Phase 2 (the legacy `real_engine.py` was architecturally wrong: same-bar fills, daily clamp, flat post-hoc cost deduction). The current engine architecturally enforces:

- **No-look-ahead.** `BarHistory` raises `LookaheadError` if asked for any row past its current `as_of` timestamp.
- **No same-bar fills.** `ExecutionHandler` rejects any `FillEvent` whose fill timestamp is not strictly later than the originating `OrderEvent`.
- **Per-fill cash-accounted costs.** Slippage (basis points or square-root impact) and commission are deducted on each `FillEvent`, not as a flat post-hoc bps reduction.
- **Mark-to-market that fails loudly.** `Portfolio` raises if asked to mark a position whose price is missing.

Components: `events.py` (Event hierarchy), `data_handler.py` (`DataHandler` + PIT `BarHistory`), `strategy.py` (`Strategy` ABC plus reference `MomentumLongShort` and `PanelStrategy` implementations), `execution.py` (`ExecutionHandler`, `FlatSlippageModel`, `SameBarCloseExecutionHandler`), `portfolio.py` (cash + positions + NAV), and `core.py` (`EventDrivenEngine`).

`backtest/synthetic_demo.py` remains as the JS-parity demo surface and must stay bit-for-bit aligned with the frontend; `backtest/event_driven_adapter.py` bridges the legacy backtest API schema to the canonical event-driven engine for real-data API requests.

## 5. Statistical Methodology — The Gauntlet

The same statistical hygiene kernel is applied to every substrate before any verdict is filed. The components are pre-committed in each substrate's design contract; thresholds are frozen before the first data is looked at; SHA-256 hashes anchor the contract so the runner refuses to execute against a modified design.

#### Core gates (pre-committed, SHA-anchored)

| Gate | Construction | Threshold |
|---|---|---|
| G1 — DSR | Deflated Sharpe Ratio (Bailey & López de Prado 2014), deflated against pre-committed trial count. | > 0.95 |
| G2 — Bootstrap CI | Stationary-bootstrap Sharpe CI (Politis-Romano 1994), 2,000–4,000 reps, 21-day mean block. | 95% excludes 0 |
| G3 — Sign agreement | Out-of-sample window A and window B agree on sign. | Same sign in both |
| G4 — Cost-double survival | Double the parametric cost model (commission + half-spread + impact) and re-run. | Same Sharpe sign |
| G5 — Regime stress | Run on 2008 crisis, 2013 taper tantrum, 2020 COVID, 2022 rate cycle. | 4-of-4 positive months |
| G6 — CF-Sharpe | Cornish-Fisher-adjusted Sharpe; sensitivity to higher moments (VRP only). | > 0.5 |

#### Supporting statistical machinery

- **Hansen Superior Predictive Ability (SPA, 2005).** Tests the null that the best-in-sample trial has no edge over a benchmark, after multiple-testing correction. Reported on the full K×T net-return matrix per OOS window.
- **White's Reality Check (2000).** Naive bootstrap variant, strictly more conservative than SPA — reported alongside as a sanity check on Hansen's p-values.
- **Purged + Embargoed K-fold CV (López de Prado 2018).** K-fold cross-validation with overlap-purging and an embargo interval around each held-out fold to prevent label leakage.
- **Stationary-bootstrap Sharpe CI (Politis-Romano 1994).** Block-bootstrap with random block length drawn from a geometric distribution to preserve serial dependence.
- **Post-portfolio FF5+UMD alpha residualisation.** `compute_portfolio_alpha` runs each strategy's daily returns through a time-series regression on Mkt-RF, SMB, HML, RMW, CMA, UMD, with HC0 SEs on the intercept and bootstrap CI on the residual Sharpe.
- **21-day embargo around every OOS boundary.** No training data within 21 trading days of an OOS window is permitted to influence the model for that window.

#### Pre-commit discipline

Every substrate writes a design contract before any data is examined and before any signal code is run. The contract specifies: the substrate window, the IS/OOS split, the embargo, the trial set (enumerated with parameter values), the gate thresholds, the cost model, the decision matrix for each outcome, and the hard rules for what is and is not permitted post-execution. The runner computes the contract's SHA-256 and refuses to execute if the anchor does not match.

**Override audit.** The pre-committed §7 reset cooldown has been explicitly overridden four times — for crypto, PEAD, India, and VIX-as-constraint-shift. **All four overrides have closed FAILED.** The override discipline itself is now an audit-able fact of the project.

## 6. Transaction-Cost Modelling — Honest Frictions

`cost_model.py` in each sub-project implements the explicit cost surface used by that substrate. The kernels and parameters are documented and frozen in each design contract; no post-hoc tuning is permitted once a verdict is being computed.

#### Equity cost components

- **Commission:** 1 bp per side (parametric).
- **Half-spread:** 2 bps parametric, *or* Corwin-Schultz (High/Low based) estimator, documented as 7–8 bps median across windows. Tier 1 / Tier 2 used the parametric model with the Corwin-Schultz divergence disclosed.
- **Linear impact:** 10 bps per unit turnover (quintile spread backtests).
- **Square-root impact (`SquareRootImpactModel`):** k·√participation; used in the capacity study and available to the event-driven engine.
- **Borrow costs:** `BorrowCostTable` with annualised bps defaults and a Hard-to-Borrow override map. Currently populated with general-collateral defaults; non-mega-cap short leg materially under-estimated. Disclosed in §19.

#### Crypto carry costs

- **Taker fee:** 4 bps per side (Binance default).
- **Half-spread:** 1 bp per side.
- **Funding payments:** 8-hour funding-rate accrual per open position, honestly added/subtracted.
- **Linear impact:** 5 bps per unit turnover.

Carry study OOS realised turnover was **1701% annualised** vs an IS-implied gate at <800%; the gate fired correctly and contributed to the CLOSED FAILED verdict.

#### India cost surface

- STT (Securities Transaction Tax): 10 bps on sell side (delivery).
- Exchange + SEBI + stamp duty: ~2 bps per side.
- Brokerage: 3 bps per side (parametric).
- Half-spread + impact: 5–10 bps per side (size-dependent).

Total round-trip cost: ~35.9 bps + 10 bps impact at base; 2× stress (G4): 71.8 bps + 20 bps impact.

#### VIX/VRP execution costs

- ETP (SVXY/VXX) bid-ask: 5 bps per side.
- ETP commission: 1 bp per side.
- Carry on free cash: **zero** per §17.8 ADDENDUM — the original §6 carry assumed it applied to posted margin on VIX futures; §17.2 removed futures from the implementation, and §17.8 zeroed cash carry as a result. *The first Phase 3 run apparently passed 18/28 on cash carry; the zeroing produced 0/28. The discipline caught its own false-pass.*

## 7. MARL Framework — Neuroevolution + PPO + MAML

`alphaforge-marl` trains a population of multi-agent reinforcement-learning policies and audits them under the same deflation-aware statistical gauntlet as the single-factor study. The framework is now FROZEN: the rigor report concluded that existing checkpoints have negative baseline-excess Sharpe (mean −1.13) and learned beta to the equal-weight basket, not alpha. It is retained as infrastructure that could be redirected to support roles (execution, sizing, regime-routing) in a future Tier 3.

#### Pipeline

`TradingEnv → AgentPool → EvolutionaryEngine (NSGA-II + speciation + MAML) → RegimeBandit (HMM) → Ensemble`

- **TradingEnv.** Gymnasium env, 57-dim observation, 5 discrete actions *or* 10-dim continuous weights. Dense reward shaping: rolling Sharpe delta + drawdown penalty + participation, plus Sharpe-based terminal reward. Curriculum scheduler ramps transaction costs, leverage, stops, and episode length. `env/real_data.py` sources aligned OHLCV from the shared parquet store — training never touches the network.
- **Agents.** `BaseAgent` wraps an `ActorCriticNetwork` with multi-head attention over per-ticker features. Variants: `ContinuousActorCritic`, `DQNHead`, `PPOTrainer` (GAE + clipped surrogate), `MAMLTrainer` (FOMAML), `EnsemblePolicy`, `ParetoFront`, `AgentPool`.
- **Evolution.** Per-generation: evaluate under common random numbers → PPO fine-tune → periodic MAML → NSGA-II select on (Sharpe, drawdown, turnover) → speciated reproduction (Jensen-Shannon distance) → per-parameter adaptive mutation.
- **Regime bandit.** HMM regime detector (K-means init + Baum-Welch). Thompson sampling per (regime, agent) feeds a capital allocator.
- **Walk-forward validator.** Anchored splits, strict temporal isolation, reports overfitting ratio and val/test correlation.

#### Rigor report

`research/marl_rigor.py` scans every `training.jsonl` and summary JSON in the MARL tree, enumerates the full trial count, and applies the same statistical hygiene as the single-factor study. Headline numbers:

| Metric | Value |
|---|---|
| Total generation-level trials enumerated | 100 |
| OOS mean stability Sharpe (2 seeds, 251 days) | +0.72 |
| OOS stability DSR (deflated for 100 trials) | 0.038 |
| Reward-mix trials beating equal-weight | 0 / 60 |
| Mean baseline-excess Sharpe | −1.13 |
| Best individual trial baseline-excess Sharpe | −0.669 |

**Reading:** the agents learned beta to equal-weight, not alpha. Adding more training would not address the underlying problem. Detailed report: `alphaforge-marl/research/out/marl_rigor_report.md`; ablation ladder at `research/ablation_ladder.py`.

## 8. Live Execution — Daily Loop, Risk, and Kill Switch

`alphaforge-execution` implements the daily Alpaca paper-trading loop. The loop is **currently halted**: `.halt` is engaged and `run_daily.sh` exits with `HALTED` on every cron fire. The 10 paper positions held across the momentum and MARL accounts were flattened on 2026-04-26. Re-launch requires the four conditions in `docs/TIER1_PAUSE.md`; with Tier 1 + Tier 2 closed failed, those conditions cannot be met from the current state.

#### Daily loop

Fetch prices → momentum ranking → pre-trade risk checks → order execution → snapshot recording → circuit breakers → kill-switch end-of-day evaluation.

- **Brokers.** `PaperBroker` (local simulation with slippage), `AlpacaBroker` (paper-trading API).
- **Strategy.** `strategy/momentum.py` implements a composite of 5-day momentum (40%), 21-day momentum (40%), and mean reversion (20%); top-N equal-weight.
- **Risk limits.** `risk/limits.py` enforces position size, total exposure, and turnover caps pre-trade.
- **Storage.** SQLite (`storage/`) with auto-created `orders`, `snapshots`, and `signals` tables.

#### Kill switch (six triggers, three-stage unwind)

`risk/kill_switch.py` enforces the `kill_switch:` block in `execution_config.yaml`. `KillSwitch.end_of_day()` runs after every snapshot.

| Trigger | Threshold (illustrative) |
|---|---|
| Max drawdown | > 8% from peak NAV |
| Single-day loss | > 2% NAV in one trading day |
| Consecutive losing days | ≥ 4 in a row |
| Realised slippage median | > 15 bps over rolling 20 fills |
| Realised cumulative fill-error drag | > 50 bps cumulative NAV |
| Minimum liquid ticker count | < 8 tradeable names |

**Unwind ladder:** 25% of current weights at halt, 50% at +4 hours, 100% by next close. Re-arm requires a human-acknowledged line starting with `ACK:` in the pager file. Full playbook: `docs/kill_switch_playbook.md`.

#### Slippage reconciliation

`research/slippage_reconciliation.py` compares realised slippage in the live SQLite database against the backtest's assumed bps. Emits a distribution summary, a self-contained two-sample KS test (no scipy dependency), and cumulative NAV drag from fill error. Output: `research/out/slippage_reconciliation.md` + JSON. Currently anchored on 7 lifetime fills (pre-halt); not enough for a load-bearing tracking-error number, but the infrastructure exists.

## 9. JavaScript Frontend — Parity-Tested Terminal UI

The frontend is a vanilla-JS single-page application loaded via `<script>` tags — no build step, no transpiler, no package manager. Chart.js is vendored locally as `chart.min.js`. The Python backend mirrors every numerical primitive bit-for-bit; parity tests at the PRNG, factor-scoring, and backtest layers compare against `tests/fixtures/js_reference_output.json` to 10 decimal places.

| Module | Responsibility |
|---|---|
| data.js | Mulberry32 seeded PRNG, synthetic price/volume generation, factor scoring, backtest engine (fallback). |
| app.js | Tab switching, workspace controls, dispatches to modules; loads last and calls each module's `init()`. |
| scanner.js | Factor screening UI; cross-sectional ranking visualisation. |
| correlation.js | Factor correlation, IC, and turnover analysis with sortable tables. |
| ai-engine.js | Recommendations UI fed by the Python optimizer endpoint. |
| marl.js | MARL agent ensemble dashboard. |
| execution.js | Live-execution snapshot view. |

**Communication.** Global state via `AlphaApp.getState()` → `{ sector, lookback, activeTab }`. The primary workflow hits the `alphaforge-python` FastAPI at `:8000` for real-market history from the local Parquet store; the seeded-PRNG synthetic path remains as an offline fallback. Five frontend factors (Momentum 12-1, Mean Reversion 5d, Volume Surge, RSI Divergence, Earnings Drift) are bit-for-bit identical to their Python counterparts.

**Defensive numerics.** The same primitive set used in Python (`safeDiv`, `sanitizeNumber`, `clamp`, `validateSeries`) is mirrored in the JS layer; NaN / Inf cannot propagate through the factor pipeline in either runtime.

## 10. Substrate #1–2 — US Equity Tier 1 and Tier 2 (CLOSED FAILED)

#### Tier 1 — nine factors, four combinations, full PIT

Substrate window: 2,514 trading days (2016-01-04 through 2025-12-31) on the PIT S&P 500 ever-member universe (476 of 877 ever-members with sufficient OHLCV coverage). IS: 2016-2021. OOS-A: 2022-2023. OOS-B: 2024-2025. 21-day embargo at each boundary.

**Trial set.** Nine single factors + four combinations (EWE, ICW, MV, ICW-flip) = 24 strategy-trials, deflated against this count under DSR.

**Verdict.** 0 of 9 single factors and 0 of 4 combinations cleared. The closest result was MV with alpha-residual OOS Sharpe **+3.06 / +2.43**, alpha t-stats 4.33 / 3.43 (HC0), FF5+UMD R² 16% / 8%, bootstrap p_positive = 1.0 in both windows. Failed only on DSR (0.92 / 0.70 vs the pre-committed 0.95).

> "Real signal eaten by costs and multiple-testing" — row 2 of the failure-path matrix, committed as the diagnostic in `PHASE6_WRITEUP.md` §4.

#### Tier 2 — lower-turnover diagnostic

Tier 2 was a pre-committed test of the row-2 hypothesis: if costs and multiple-testing were what killed MV-21, then a lower-turnover variant (rebalance every 63 or 126 days, with optional vol-cap and covariance-shrinkage variants) should preserve the alpha while saving costs.

**Trial set.** 8 strategies: MV-63, MV-126, MV-63-volcap, MV-126-volcap, MV-63-shrunk, MV-126-shrunk, MV-63-ext, MV-126-ext.

**Verdict.** 0 strategies cleared, 0 near-misses. **Lower turnover destroyed the alpha rather than preserving it.** MV-21's OOS-A alpha-residual Sharpe of +3.06 collapsed to +0.79 at 63-day rebalance and +0.95 at 126-day rebalance — the opposite of what the row-2 hypothesis predicted. The revised reading is that MV-21 is a 21-day-specific residualised mean-reversion artefact (Da-Liu-Schaumburg 2014), not a robust cross-sectional anomaly. Full writeup: `TIER2_VERDICT.md`.

#### Methodology footnote — the residualisation bug

During Tier 2 a load-bearing wiring bug was discovered: `prepare_analysis_returns()` was returning raw returns regardless of the residualise flag, and `compute_portfolio_alpha` was not wired into the main gauntlet. The JSON metadata claimed `analysis_returns_mode: residualized` while the actual computation was on raw returns. Fixed in <50 lines; gauntlet re-run; *verdict held but the documented diagnostic shifted*. Pre-fix outputs are preserved as `*_residualized.json` backups for full audit-ability.

## 11. Substrate #3 — Crypto USDT-M Carry (CLOSED FAILED)

After the §7 reset cooldown was overridden on 2026-05-15, the carry study was spun up on the top-25 Binance USDT-M perpetual futures by Average Dollar Volume (2021-2026). The signal: rank perpetuals by trailing K-period funding-rate accrual; long the lowest quintile, short the highest; rebalance at frequency K.

**Pre-commit anchors:** `dbd77ad` (design doc) and `4277eba` (trial log). 32 trials enumerated (including 14 considered-but-not-run alternatives, captured in the log). K_primary = 63. OOS window: 2025-01-08 through 2026-05-14, 1.35 years, 2,952 funding events.

| Gate | Threshold | Realised | Pass? |
|---|---|---|---|
| G1 — Net annualised Sharpe | > 0.5 | +1.48 | ✓ |
| G2 — Bootstrap CI excludes 0 | excludes 0 | [-1.39, +4.33] | × |
| G3 — DSR | > 0.95 | 0.624 (N=32) | × |
| G4 — Annualised turnover | < 800% | 1701% | × |
| G5 — Sign agreement IS vs OOS | same sign | IS +3.55 / OOS +1.48 | ✓ |

**Verdict.** 3 of 5 gates failed. The signal had genuine ex-ante predictive power (IC 0.46–0.59 stable across five purged CV folds at K=21 — an *order of magnitude* larger than equity factor ICs of 0.02–0.05) but the OOS Sharpe of +1.48 sits below the DSR-implied minimum of ~1.6–1.8 estimated in design-doc §11 ahead of time. **The signal is real; the deflation hurdle is what killed it.** Identical row-2 mechanism to equity Tier 1's MV-21 result.

> "The math worked. The cost economics were correctly diagnosed in advance. The strategy had real edge but not enough margin over the deflation penalty." — `CARRY_STUDY_VERDICT.md`

## 12. Substrate #4 — BTC-USDT Microstructure (IN FLIGHT)

Substrate #4 is the active research surface. Phase 0 began on 2026-05-17: a live Binance public-WebSocket collector accumulates 100 ms book snapshots and the per-trade tape for BTC-USDT to local disk. The earliest Phase 1 execution date is 2026-06-17 (≥30 days of book data required; 90 days preferred).

#### Phase 0 exit gates (must all be green)

- ≥30 days of book data on disk.
- `validation/book_snapshot_check.py` reports 0 diffs across 24 sample REST snapshots.
- `validation/temporal_alignment.py` reports trade-vs-book violation rate <0.01%.
- `validation/gap_detector.py` reports gap fraction <0.1%.

#### Phase 1 trial set (pre-committed, frozen)

**Phase 1a (standalone signals, 56 trials).** Two signal families evaluated at seven horizons:

| Family | Parameter | Values | Horizons |
|---|---|---|---|
| Order Book Imbalance (OBI) | depth | 1, 5, 10, 20 | 1s, 5s, 30s, 60s, 5m, 15m, 1h |
| Trade Flow Imbalance (TFI) | window | 10s, 30s, 60s, 300s | 1s, 5s, 30s, 60s, 5m, 15m, 1h |

**Phase 1b (spread-filtered, 112 conditional trials).** Only runs if Phase 1a produces ≥1 SURVIVOR. Pre-commits the full enumeration so the deflation hurdle is anchor-able from day one.

#### Phase 1 gates (pre-committed)

- **G1 — IC magnitude.** |IC| ≥ 0.03 at peak horizon, in BOTH halves of the data.
- **G2 — Sign consistency.** Sign of peak-horizon IC agrees between first half and second half.
- **G3 — Stability.** Peak horizon in the second half is within ±1 step on the horizon grid of the first-half peak.

A signal that passes G1+G2+G3 is reported as a Phase 1 SURVIVOR and proceeds to Phase 2 (strategy design, inventory risk, execution costs, adverse selection). Phase 2 + Phase 3 contracts are also pre-committed: `PHASE2_DESIGN.md`, `PHASE3_DESIGN.md`.

## 13. Substrate #5 — PEAD via EDGAR XBRL (CLOSED FAILED)

Post-Earnings Announcement Drift implemented via SEC EDGAR Company Facts XBRL on the existing PIT equity substrate. Phase 0 produced 614 eligible firms and ~26,908 firm-quarter announcements over 2012-2026, certified in `PEAD_PHASE0_CERTIFIED.md` (SHA-256 `a91e2a07ee...b9f9ae8`).

**Trial set.** 10 pre-committed trials: 5 holding horizons K ∈ {5, 21, 42, 63, 84} × 2 bucket cuts (quintile, decile). IS: 2012-2020. OOS-A: 2021-2023. OOS-B: 2024-2026-05-17. 21-day embargo. Bootstrap: 4,000 reps.

| K | Bucket | OOS-A IC | OOS-B IC | OOS-A Sharpe | OOS-B Sharpe | DSR-A | DSR-B |
|---|---|---|---|---|---|---|---|
| 5 | quintile | 0.051 | 0.050 | +1.36 | +3.68 | 0.29 | 0.88 |
| 21 | quintile | 0.055 | 0.043 | +1.67 | +2.70 | 0.38 | 0.68 |
| 42 | quintile | 0.034 | 0.047 | +1.35 | +3.41 | 0.29 | 0.83 |
| 63 | quintile | 0.036 | 0.059 | +2.29 | +2.49 | 0.58 | 0.62 |
| 84 | quintile | 0.038 | 0.058 | +2.87 | +2.39 | 0.75 | 0.60 |

**Verdict.** 0 of 10 trials cleared. "Real but weak": **OOS IC is uniformly positive across all 10 trials in both OOS windows (0.034 to 0.059)**, peak horizon at K=63–84 aligned with the literature (Livnat-Mendenhall 2006), sign agreement 8 of 10 — but no trial cleared DSR > 0.95 (closest: K=84 quintile, 0.75 / 0.60). The OOS-B window (2.4 years) is too short to tighten the bootstrap CI to a deflation-survivable level.

## 14. Substrate #6 — NSE Event-Driven + Flow (CLOSED FAILED)

The first substrate deliberately chosen to break the cross-sectional-rank failure mode common to substrates 1–5: NSE bhavcopy + monthly trading-to-delivery (MTO) delivery percentages + F&O expiry events on Indian large-caps. Phase 0 CERTIFIED 2026-05-20 with **7.76M EQ rows over 5,527 dates (2004-04 → 2026-05-19), 100% delivery-percentage coverage on Nifty-500 ever-members**.

**Trial set.** 22 trials after the §17 ADDENDUM cancelled the FII/DII branch (data integrity issues): 18 delivery-percentage trials (3 lookbacks × 2 bucket cuts × 3 holding horizons) + 4 F&O expiry trials. IS: 2004-2014. OOS-A: 2015-2019. OOS-B: 2020-2026.

**Verdict.** 0 of 18 evaluated trials cleared even gates 1–4. F&O Phase 3 was skipped — per-event high-open-interest universe data could not be reconstructed from public archives. **Universal OOS sign inversion:** every trial produced negative Sharpe in both OOS windows (range −0.62 to −4.94). Cost-doubling barely moves Sharpe (e.g. −4.80 → −4.88), confirming the signal *direction* reversed OOS rather than being eaten by costs.

> "The delivery-pct anomaly that produced positive IC in 2004-2014 produces actively negative Sharpe in 2015-2026. Same row-2 mechanism as the prior 5 substrates with a sharper edge." — `alphaforge-india/research/GAUNTLET_VERDICT.md`

Phase 1 IS evidence remained legitimate (IC 0.034–0.062, all 22 trials survived G1 signed-positive). The collapse occurred exclusively in OOS, exactly the pattern the gauntlet is designed to catch.

## 15. Substrate #7 — CBOE Variance-Risk Premium (CLOSED FAILED)

**The first deliberate constraint shift of the project.** Substrates 1–6 all shared one structural assumption: alpha comes from prediction. VIX breaks that assumption. The variance-risk premium does not predict; it harvests a structural premium that exists because portfolio managers systematically overpay for insurance (Bondarenko 2004, Carr-Wu 2009). The edge is not better forecasting — it is *being the insurance writer*.

Substrate window: 2004-03-26 → present (CBOE VIX, VIX9D, VIX3M, VIX6M, SPY OHLCV, SVXY/VXX ETPs from 2011 onward). Pre-commit anchor: `VIX_DESIGN.md` SHA-256 `54e53be9...` post-§17 + §17.7 + §17.8 ADDENDA. Phase 2 strategy spec frozen at SHA `18173b6d...`.

#### Phase 1 (Information Coefficient gauntlet)

**10 of 18 VRP trials cleared signed-positive IC.** Strongest result: **peak IC +0.180 at h=21**, monotonic threshold response (thr=0 → 0/6, thr=2 → 4/6, thr=4 → 6/6 clean). 0 of 6 slope trials cleared. 4 mean-reversion trials deferred to Phase 3 per design contract. This was the first substrate of seven to live past Phase 1.

#### Phase 3 (six-gate gauntlet)

Trial set: 28 (trial × hedge-variant) combos = 18 VRP trials + 4 mean-reversion + 6 closed-slope trials remaining in the DSR denominator per §15 hard rules × 2 hedge variants (A: SPY put-protected; B: SPY-neutral).

**Top six positive-direction combos (sorted by combined OOS Sharpe).** 0 cleared G1 (DSR > 0.95) in either window; 0 cleared the deploy gate.

| Trial × variant | OOS-A SR | OOS-B SR | DSR-A | DSR-B | G3 | G4 | G5 | G6 |
|---|---|---|---|---|---|---|---|---|
| `vrp_L63_thr4_hold5_A` | +0.23 | +0.17 | 0.060 | 0.037 | ✓ | ✓ | ✓ | × |
| `vrp_L63_thr4_hold21_A` | +0.10 | +0.20 | 0.033 | 0.041 | ✓ | ✓ | ✓ | × |
| `mr_k2.0_to_MA+1sigma_A` | +0.47 | +0.12 | 0.255 | 0.043 | ✓ | ✓ | ✓ | × |
| `mr_k2.0_to_MA+1sigma_B` | +0.41 | +0.13 | 0.193 | 0.044 | ✓ | ✓ | ✓ | × |
| `vrp_L63_thr2_hold5_A` | +0.04 | +0.38 | 0.026 | 0.070 | ✓ | ✓ | ✓ | × |
| `vrp_L10_thr2_hold5_A` | +0.02 | +0.52 | 0.022 | 0.143 | ✓ | · | ✓ | · |

**Verdict.** 0 of 28 deploy-ready. The first Phase 3 run *appeared* to produce 18/28 passes; inspection revealed the passes were driven by cash carry on the unused 99.5% of NAV (the §9.1 sizing formula `0.10 × pv / VIX` yields ~0.5% NAV exposure at VIX=20). §17.8 ADDENDUM zeroed cash carry (filed pre-rerun, direction-of-effect strictly makes Phase 3 harder); re-run produced 0/28. **The discipline caught its own false-pass.**

> Phase 1 evidence that the VRP premium has positive IC remains valid. Phase 3 evidence that the pre-committed §9.1-sized retail implementation can't extract enough of it to clear DSR/bootstrap/CF gates after deflation against 28 trials is also valid. **Not contradictory.**

## 16. Substrate #8 — VIX-Baseline-Anchored Sizing (CLOSED FAILED)

Substrate #8 was spun up the same day substrate #7 closed, under a fresh SHA-anchored design contract (`SUBSTRATE8_DESIGN.md` SHA `2194b7b2...`). It tested one hypothesis: *if §9.1 sizing is changed so the strategy has measurable dollar exposure, does it clear the same gauntlet against the same 28-trial DSR denominator?* Everything else inherited from substrate #7.

**Sizing rule change.** Substrate #7 §9.1: `max_notional = 0.10 × pv / VIX`. Substrate #8 §9.1: `max_notional = 0.10 × pv × (20 / VIX)`. Exactly 20× substrate #7 at every VIX level; auto-deleverage shape preserved; baseline anchored on the long-run VIX mean, not on substrate-#7 results (no peeking).

**Verdict.** 0 of 28 deploy-ready. **This refuted the substrate-#7 §17.8 secondary diagnosis** (which had claimed "sizing was too small to be measurable"). Sharpe is dimensionless: making positions 20× larger does not move it. The correct diagnosis is Mode A revisited: the VRP / mean-reversion signal has real but modest OOS Sharpe (range −0.77 to +0.55 across 28 combos), and DSR > 0.95 against a 28-trial pre-commit + 5-year OOS sample requires Sharpe in the 1.5–2.5 range. **The signal can't clear the deflation hurdle regardless of position sizing because sizing is irrelevant to Sharpe.**

> "Two substrates closed in one calendar day from one design — that's a methodology stress test. Phase 1 PASS + Phase 3 FAIL on #7 → §17.8 diagnosis → substrate #8 PRE-COMMIT → substrate #8 also FAILS, and reveals the diagnosis was partly wrong. The methodology surfaced its own error in the substrate-#7 §17.8 reasoning." — `SUBSTRATE8_VERDICT.md`

## 17. Failure-Mode Taxonomy — What the Verdicts Mean Together

Across eight substrates the gauntlet has classified four distinct failure modes. The taxonomy below is the analytic deliverable of the multi-substrate programme.

| Mode | Description | Substrates |
|---|---|---|
| A | Real signal eaten by deflation against honest multiple-testing. | #1 (MV-21), #3 (carry), #5 (PEAD), #7+#8 (VRP) |
| B | Horizon-bound: signal exists at one horizon but does not transport to others. | #2 (MV-21 → MV-63/126) |
| C | Sign inversion: IS-positive signal flips sign OOS, indistinguishable-from-noise direction reversal. | #6 (India delivery-%) |
| D | Signal-too-small-to-detect-at-pre-committed-sizing (initial diagnosis on #7; refuted by #8). | #7 (initial), refuted by #8 |

**Mode A is the dominant pattern** (five of seven failed substrates). It is what the project's methodology is specifically designed to detect: a signal that *looks* publishable under naive testing but does not survive once it is honestly penalised for the size of the search space that produced it.

**The asymmetry between "publishable" and "deployable".** Bondarenko 2004 and Carr-Wu 2009 documented the variance risk premium with strategies producing reported Sharpes of 1.0–1.5 *before* multiple-testing deflation. After DSR-28 deflation, those reported Sharpes would also fail the gate. The gauntlet correctly identifies that *publishable* alpha and *deployable* alpha are not the same thing.

**What is pre-arbitraged at this constraint set:** any signal whose OOS Sharpe is below ~1.5–2.0 against 28-trial deflation. That is the empirical bound discovered by the programme. Any future substrate that produces sub-1.5 Sharpe under the same constraints will fail in the same way.

## 18. Engineering Highlights — Tests, Parity, CI, Reproducibility

- **JS / Python numerical parity to 10 decimal places** on PRNG, factor scoring, and backtest paths. Same research expressible in either runtime without numerical drift; enforced by parity-fixture tests against `js_reference_output.json`.
- **Defensive numerics by construction.** A small primitive set (`safe_div`, `sanitize_number`, `clamp`, `validate_series`) is used uniformly across both runtimes; NaN / Inf cannot propagate.
- **Architectural enforcement of no-look-ahead.** `BarHistory` raises if asked for any row past its `as_of`; `ExecutionHandler` rejects fills that aren't strictly later than their originating order.
- **SHA-256-anchored design contracts.** Every substrate freezes its design before any data is examined; the runner refuses to execute if the SHA does not match. India `3b397262...`, VIX `54e53be9...`, Phase 2 spec `18173b6d...`, substrate-#8 `2194b7b2...`, PEAD Phase 0 `a91e2a07...`.
- **Pre- and post-fix output preservation.** Pre-bug-fix Tier 1 outputs are retained as `*_residualized.json` backups alongside post-fix outputs, enabling full audit of the diagnostic shift between runs.
- **One-command reproducibility.** `make all` rebuilds every research artefact in this document from the parquet store in ~5 minutes.
- **CI drift detection on headline metrics.** GitHub Actions matrix re-runs each headline study and diffs rebuilt JSON against the committed artefact. Silent numerical regression fails the build.
- **Per-component CLAUDE.md.** Each sub-project carries its own architecture documentation. The root CLAUDE.md is the cross-cutting summary; each sub-project doc is the authoritative reference for that component.
- **Knowledge-graph backed code review.** The repository is indexed by a Tree-sitter-based code-review knowledge graph (3,087 nodes, 26,157 edges, 328 files); semantic search, impact radius, and review-context queries replace manual grep/read on non-trivial reviews.

## 19. Honest Limitations and Process Disclosures

The framework's methodology is sound; the items below describe specific gaps, choices, and process failures that an auditor or peer reviewer should know about.

- **Residualisation-wiring bug (process failure, fixed 2026-05-02).** `prepare_analysis_returns()` returned raw returns regardless of the residualise flag for an unknown period; the post-hoc `compute_portfolio_alpha` layer existed but was not wired into the main gauntlet. JSON metadata claimed `analysis_returns_mode: residualized` while the computation was on raw returns. Caught during Tier 2; fixed in <50 lines; gauntlet re-run; verdict held but documented diagnostic shifted. An audited institutional pipeline would have caught this via code review or independent reimplementation.
- **Phase 3 FF5 replica gate was soft-passed.** 3 of 6 reference factors (SMB, RMW, CMA) failed the >0.85 correlation threshold against Kenneth French's published series on the 476-ticker substrate (structural — French builds on full CRSP). Decision: use French's published series for residualisation rather than the local replica, sidestepping the failed sub-gate. Documented, but a partial compromise.
- **Tier 2 design contained two no-op variants.** Vol-cap variants are mathematical no-ops because Sharpe and DSR are scale-invariant. Extended-history variants did not actually use extended training data given panel start = 2016. Trial set effectively reduced from 8 to 4 unique strategies. Verdict held under both interpretations.
- **Cost model under-estimates real spreads.** Parametric 2 bp half-spread vs Corwin-Schultz median 7–8 bp across all windows. Direction of effect: makes the row-2 hypothesis look MORE viable than reality, strengthening the verdict, not weakening it.
- **25% data gap on the PIT universe.** 226 of 881 ever-member tickers have no yfinance OHLCV (delisted / restructured). Documented in every metric. CRSP-grade data would close the gap but was out of budget.
- **No live-vs-backtest tracking number.** 7 lifetime fills before the .halt; not enough for KS-test or cumulative-drag analysis. The infrastructure exists; the data does not.
- **No per-name borrow-cost differentiation.** Borrow-cost table supports HTB overrides; currently populated with general-collateral defaults. Material understatement for any non-mega-cap short leg.
- **Trial count is conservative for MARL.** The MARL DSR deflates against 100 generation-level trials; the true search space (architecture, curriculum, reward shaping, selection rule) is larger. Published OOS DSR is an optimistic *upper* bound on credibility.
- **VIX §7 residualisation incomplete.** Only SPY + ΔVIX are wired into the OLS (2 of 4 factors). ST-Reversal and Carry factors are not staged. Per-trial `provisional=True` flag in the machine output.
- **India F&O Phase 3 SKIPPED.** Per-event high-OI universe data could not be reconstructed from public archives; 4 of 22 trials report no Phase 3 result. Counted in the DSR denominator per §17 ADDENDUM.
- **§7 reset cooldown has been overridden four times.** Crypto, PEAD, India, and VIX-as-constraint-shift. All four overrides closed FAILED. The override discipline is itself an audit-able fact of the project.

## 20. June 2026 Update — Substrates #9–#10 and the Canonical Gauntlet

**This section post-dates the original document body** and records the work since 2026-05-22: two further substrates and a consolidation of the evaluation methodology into one audited, version-pinned package with a measured detection floor. Where it conflicts with earlier sections, this section governs.

#### Substrate #9 — SPY Iron-Condor Options (CLOSED FAILED 2026-05-26)

Black-Scholes reconstruction on free VIX + OHLCV. The premium is *real*: 11 of 11 in-sample years positive, mean +$0.19/share per cycle. But the entry-time variance-risk premium has **no predictive power for cycle-level P&L**: corr(VRP_entry, cycle P&L) = −0.0146 (required > 0). **Mode E** — the binary filter (VRP > 0 → positive expectation) works, but the continuous-predictor relationship is absent. Closed at Phase 1, Test 1.

#### Substrate #10 — Kalshi Favorite-Longshot Bias (PHASE 1 INCONCLUSIVE)

The first substrate where **small capacity is the edge, not the handicap**: a ~$40k Kalshi market sits below the size at which crowding and market impact bind, so the capacity constraint that handicaps larger strategies does not apply. The evaluation objective is a credible live track record, not large-scale alpha. Phase 0 CERTIFIED (292 volume-bearing resolved contracts, no-look-ahead 100%; Kalshi fee schedule confirmed). Phase 1 INCONCLUSIVE — the free read-only host exposes only a recent, MVE-heavy universe, so available N sits **25–140× below the binary-MDE detection floor**; per the decision matrix this routes to forward accumulation. The Phase-1 core was adversarially audited 7/7 integrity-clean.

- **Phase 2 forward record is live.** A read-only paper-trade harness places against the Kalshi `/events` feed (the `/markets` feed is 100% sub-minute MVE), with a 45-day time-to-close cap so the record accrues on a useful timescale. launchd runs `place` 3×/day, `reconcile` + a weekly digest. Target: 200 resolved events (~weeks–2 months).

#### The Canonical Gauntlet (afgauntlet) + DSR Audit

The per-substrate statistics (Sharpe, DSR, bootstrap CI, SPA / Reality Check, purged-embargoed CV) were consolidated into one version-pinned, golden-tested package, with a binary/calibration module (Brier, log-loss, reliability curve, calibration-edge bootstrap, binary MDE) for prediction markets. A reconciliation audit found the project had been running **four different DSR implementations**; measured divergence is at most 0.026 in DSR units and produces **0 verdict flips across 96 grid points** — so no historical verdict was an artifact of its estimator.

#### MDE Power Calibration — Real Null vs Blunt Instrument

A power study injects synthetic alpha of known strength onto real return noise and measures how often the gauntlet detects it. Overall power tracks the DSR-gate pass rate exactly — **DSR deflation is the sole binding constraint.** Minimum detectable true annualized Sharpe (80% power): **~0.93** generous (1 trial, 10-year window), **~2.40** VIX-like (28 trials, 5-year), **> 3.5** PEAD-like (short OOS). Reading: the strongest observed signal (VIX OOS +0.55) sits below even the generous floor — a *real null* — but a 2.4-Sharpe bar is economically strict versus the ~0.5–1.0 a leveraged desk trades, so the hurdle, not only the data, is part of the story.

#### Cost-Model Reconciliation + Microstructure Recollection

- **Costs.** Realized paper-trade slippage was ~2.6–3× the assumed rate (on 12 live fills), but higher costs flip **zero** verdicts; only crypto carry was plausibly cost-bound. The binding constraint was deflation, not execution.
- **Microstructure (#4) Phase 0 break.** The live collector ran pre-fix code for 29 days (82% gap fraction, ~33% hour coverage). Code on disk was already correct; the process was stale. Fixed the readiness tooling, added a recent-gap-rate alarm, filed a recovery runbook. Earliest honest Phase 1 ~2026-07-16.

The full cross-substrate synthesis lives in `RESEARCH_META_SYNTHESIS.md`.

## 21. Forward Path — The Strategy-Class Decision Window

**The honest question is no longer "what substrate?" — it is "what strategy class?"** Cross-sectional rank-based signals with linear combinations and parametric retail costs do not survive in either equity (substrates 1–2, 5), crypto perpetuals (substrate 3), Indian large-caps (substrate 6), vol-surface premium harvest (substrates 7–9), or — at free-data scale — prediction-market calibration (substrate 10). Six of the eight failures share the row-2 / Mode A pattern with variants; India shows sharper Mode C sign inversion; the VIX cluster discovered Mode D and then refuted it; and the iron condor exhibited Mode E (binary filter works, continuous predictor absent). The MDE calibration (§20) reframes this: the binding constraint is the DSR deflation floor, and the open question is whether to lower that bar deliberately or change a structural input.

#### What could change the verdict (substrate #9+)

- **Larger pre-commit window.** 10-year OOS instead of 5-year lowers DSR variance correction. Requires waiting OR using paid pre-2004 data.
- **Fewer pre-committed trials.** 10-trial DSR denominator instead of 28. Requires dropping search-space from the start; cannot subset post-hoc.
- **Different strategy class.** Spin-off arbitrage (Greenblatt 1997, retail-scale documented), microcap value + quality, vol-surface dispersion, crypto on-chain analytics, market-making at fast latencies. None of these were tested by substrates 1–8.
- **Paid data.** CRSP, VIX futures, Kenneth French published factors, FRED — closes both the 25% PIT data gap and the §7 residualisation gap.
- **Abandon systematic alpha at retail constraints.** Move to market-making, non-systematic discretionary, or accept the research stack as a methodology contribution rather than a capital-deployment vehicle.

#### Live execution status

`alphaforge-execution/.halt` is engaged. `run_daily.sh` exits with `HALTED` on every cron fire. The 10 Alpaca paper positions across momentum and MARL accounts were flattened on 2026-04-26 via `scripts/tier1_close_positions.py`. Re-launch requires the four conditions in `docs/TIER1_PAUSE.md` (Tier 1 gate passed, signal is the survivor, universe expanded, ≥6 months paper trade). With Tier 1 + Tier 2 closed, those conditions cannot be met from the current state; the .halt stays on indefinitely. The kill-switch infrastructure remains tested and wired so a future re-arm can proceed under the existing risk framework.

#### What the project demonstrates today

An end-to-end research-grade systematic-trading stack built and run on free public data, applied honestly to a known-hard problem across six asset classes and two strategy classes, with methodology bugs found and fixed in the same session they surfaced and every diagnostic shift documented openly. **The negative results published here are the artefact; surviving signals are not.** The current frontier is two-fold: substrate #10's live forward paper-trade record (the first deliberate pursuit of a small-capacity edge) and substrate #4's microstructure Phase 1 once its book-data recollection completes (~2026-07-16). The methodology now reports not just a verdict but, via the MDE calibration, whether a verdict was even detectable in the first place.

---

**Repository:** *Quant Alpha* (AlphaForge). **Source:** this file; `make overview` renders the PDF via pandoc. **Companion artefacts:** `PHASE6_WRITEUP.md`, `TIER2_VERDICT.md`, `alphaforge-crypto/research/CARRY_STUDY_VERDICT.md`, `alphaforge-pead/research/PHASE1_VERDICT.md`, `alphaforge-india/research/GAUNTLET_VERDICT.md`, `alphaforge-vix/research/GAUNTLET_VERDICT.md`, `alphaforge-vix/research/SUBSTRATE8_VERDICT.md`, `alphaforge-microstructure/research/PHASE1_DESIGN.md`. Reproducible: `make all` rebuilds every JSON cited.
