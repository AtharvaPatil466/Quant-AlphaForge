# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AlphaForge is a quantitative alpha research platform with nine components:
1. **Frontend** — Vanilla JS single-page app (`index.html`), no build system. Open directly in a browser.
2. **`alphaforge-python/`** — Python port of the JS data/simulation layer with REST API and mean-variance optimizer. FROZEN (factor/research modules) post-Tier-2; data layer (PIT universe, OHLCV store, cost model, stats hygiene) is read-only consumed by other sub-projects.
3. **`alphaforge-marl/`** — Neuroevolution + PPO multi-agent RL framework. FROZEN.
4. **`alphaforge-execution/`** — Live paper trading. FROZEN; `.halt` engaged.
5. **`alphaforge-crypto/`** — Crypto carry/basis research stack on Binance public data. Carry study CLOSED FAILED 2026-05-15.
6. **`alphaforge-microstructure/`** — Microstructure research stack on Binance BTC-USDT L2 + tape. Active substrate #4. Phase 0 in progress (book-data accumulation, started 2026-05-17; earliest Phase 1 execution 2026-06-17). Phase 1/2/3 pre-committed.
7. **`alphaforge-pead/`** — Post-Earnings Announcement Drift research stack on EDGAR XBRL + the existing PIT equity substrate. Substrate #5, **CLOSED FAILED 2026-05-17.** 0 of 10 pre-committed trials cleared the gauntlet; "real but weak" diagnosis with positive IC but DSR < 0.95. Full verdict: `research/PHASE1_VERDICT.md`.
8. **`alphaforge-india/`** — NSE event-driven + flow-based research stack on bhavcopy + delivery percentage + F&O expiry. Substrate #6, **CLOSED FAILED 2026-05-20.** Phase 0 CERTIFIED (7.76M rows over 2004-2026, 100% delivery-pct coverage). Phase 1: 22/22 survivors (delivery-pct IC 0.034-0.062). Phase 3: **0/18 evaluated trials cleared all 5 gates; 0 cleared even Gates 1-4.** Universal sign inversion — every trial produced negative Sharpe in BOTH OOS windows; cost-doubling test confirms costs are not the binding constraint. Diagnosis: row-2 with signal-direction reversal. Sixth credible negative verdict in the project. Full machine verdict: `research/GAUNTLET_VERDICT.md`.
9. **`alphaforge-options/`** — SPY iron condor research stack using BS reconstruction on free VIX+OHLCV data. Substrate #9, **CLOSED FAILED 2026-05-26 at Phase 1.** T1 correlation(VRP_entry, cycle_P&L) = -0.0146 (not > 0). Profitable every IS year (11/11 positive, mean +$0.19/share) but VRP level at entry has no predictive power for cycle-level P&L — binary filter effective, continuous relationship absent (Mode E). Full verdict: `research/PHASE1_VERDICT.md`.
10. **`alphaforge-vix/`** — VIX/Variance Risk Premium harvest research stack on CBOE VIX/term-structure indices + SPY realized vol + SVXY/VXX ETPs. Substrate #7, **CLOSED FAILED 2026-05-21 at Phase 3.** First deliberate **constraint shift** of the project (predictive alpha → structural premium harvest). Pre-commit contract in `research/VIX_DESIGN.md` (SHA-256 `54e53be9...`, post §17 + §17.7 + §17.8 ADDENDA). **Phase 1: 10/18 VRP trials pass signed-positive IC (strongest +0.180 at h=21)**. **Phase 3: 0/28 (trial × variant) combos clear all six gates.** Diagnosis (per §17.8 ADDENDUM + §14.17): the literal §9.1 sizing formula `0.10 × pv / VIX` produces ~0.5% NAV exposure at VIX=20; first run accidentally tested cash carry (§6 carry was for posted margin on futures, removed by §17.2), apparently passing 18/28; §17.8 zeroed cash carry → 0/28 pass. OOS Sharpes are -0.77 to +0.55 — too small for DSR/bootstrap/CF after deflation against 28 trials. **Six prior substrates failed Phase 1 (PEAD, equity Tier 2) or Phase 3 (Tier 1, crypto carry, India); VIX is the first to clear Phase 1 then fail Phase 3.** Phase 1 evidence the premium exists remains valid; Phase 3 evidence the pre-committed retail implementation can't extract enough of it is also valid — not contradictory. 237 tests pass + 4 network-skipped. Full verdict: `research/GAUNTLET_VERDICT.md`. Substrate window 2004-03-26 → present.

Each Python sub-project has its own `CLAUDE.md` with detailed architecture. This file covers the cross-cutting concerns and the JS frontend.

## Project Status (as of 2026-05-26, end of day)

The project is framed as the foundational stack for a future hedge fund (see `~/.claude/projects/-Users-atharva-Quant-Projects-Quant-Alpha/memory/user_career.md`). **Seven substrates have closed FAILED: equity Tier 1 (2026-05-02), equity Tier 2 (2026-05-02), crypto carry (2026-05-15), PEAD (2026-05-17), India (2026-05-20), VIX/VRP (2026-05-21), and iron condor options (2026-05-26).** One is in flight (microstructure #4). **Options (#9) is the eighth substrate and failed Phase 1 on Test 1 only: corr(VRP_entry, cycle_P&L) = -0.0146 (required > 0). Notably, the premium harvest itself is real — 11/11 IS years positive, mean $0.19/share — but the VRP level at entry has no predictive power for cycle-level P&L. This is Mode E: binary filter effective (VRP>0 → positive expectation), continuous predictor relationship absent.** As of end-of-day 2026-05-26:

- **Substrate #4 — Microstructure** (`alphaforge-microstructure/`): BTC-USDT L2 + trade tape on Binance. Phase 0 IN PROGRESS; live collector started 2026-05-17 accumulating book data; Phase 1 pre-committed in `alphaforge-microstructure/research/PHASE1_DESIGN.md` (56 base trials + 112 conditional). Phase 2 + Phase 3 design contracts also pre-committed. Earliest Phase 1 execution: 2026-06-17 (+30d).
- **Substrate #5 — PEAD** (`alphaforge-pead/`): Post-Earnings Announcement Drift via EDGAR XBRL on the existing PIT equity substrate. **CLOSED FAILED 2026-05-17.** Phase 1 gauntlet ran cleanly; 0 of 10 trials cleared. Closest near-misses K=63 and K=84 quintile (DSR 0.58-0.75 vs 0.95 hurdle). "Real but weak" — IC uniformly positive in both OOS, sign agreement 8/10, peak horizon aligned with literature — but not strong enough to clear deflation. Same row-2 diagnosis as the three prior verdicts. Full verdict: `alphaforge-pead/research/PHASE1_VERDICT.md`.
- **Substrate #6 — India** (`alphaforge-india/`): NSE event-driven + flow-based stack on bhavcopy + delivery percentage + F&O expiry. Strategy class deliberately chosen to avoid the cross-sectional-rank failure mode common to all five prior verdicts. **CLOSED FAILED 2026-05-20.** Full pipeline executed: Phase 0 CERTIFIED (7.76M EQ rows, 5,527 dates, 100% deliv-pct coverage on Nifty 500 ever-members), CS calibration ran (OOS_A 20.41 bp ⚠ DIVERGENCE FLAGGED — documented per §6), Phase 1 22/22 survivors (IC 0.034-0.062 positive), **Phase 3 0/18 cleared even Gates 1-4**. Universal sign inversion: every trial produced negative Sharpe in BOTH OOS windows (range −0.62 to −4.94). Cost-doubling barely moves Sharpes (−4.80 → −4.88), confirming the signal direction reversed OOS rather than being eaten by costs. The delivery-pct anomaly that produced positive IC in 2004-2014 produces actively negative Sharpe in 2015-2026. Same row-2 mechanism as the prior 5 substrates with a sharper edge. F&O Phase 3 (4 trials) SKIPPED — no per-event high-OI universe data. Full verdict: `alphaforge-india/research/GAUNTLET_VERDICT.md`. 371/371 tests pass.
- **Substrate #7 — VIX/VRP** (`alphaforge-vix/`): CBOE VIX/term-structure indices + SPY realized vol + SVXY/VXX ETPs. First deliberate constraint shift (premium harvest, not predictive). **CLOSED FAILED 2026-05-21 at Phase 3.** Full pipeline executed in one calendar day: Phase 0 CERTIFIED (4 ADDENDA filed: §17 source-discovery, §17.7 VRP proxy, §17.8 cash-carry zeroing, Phase 2 strategy-spec operational pre-commit), Phase 1 EXECUTED (10/18 VRP trials pass signed-positive IC; 0/6 slope; 4 mean-rev deferred), Phase 2 STRATEGY SPEC FROZEN (SHA `18173b6d...` — 28 (trial × variant) combos pre-committed), Phase 3 EXECUTED (**0/28 deploy-ready**). Phase 3 first-run produced 18/28 apparent passes; on inspection this was cash carry on ~99.5% of NAV (§9.1 formula gives 0.5% NAV exposure at VIX=20). §17.8 ADDENDUM zeroed cash carry — direction-of-effect strictly makes Phase 3 harder. Re-run gave 0/28. **Diagnosis:** Phase 1 evidence that the VRP premium has positive IC remains valid; Phase 3 evidence that the pre-committed §9.1-sized retail implementation can't extract enough of it to clear DSR/bootstrap/CF gates after deflation against 28 trials is also valid. NOT contradictory. **First Phase-3-CLOSED-FAILED post-Phase-1-PASS in the project.** 237 tests pass + 4 network-skipped. Full verdict + Discussion: `alphaforge-vix/research/GAUNTLET_VERDICT.md`. **Honest read:** the constraint shift from predictive to premium-harvest was partially correct — the premium exists and Phase 1 caught it — but the pre-committed retail implementation (small-fraction NAV sizing × ETP-only execution × honest deflation) doesn't survive. Any future "what if we sized larger?" exploration is a SEPARATE substrate #8 with its own pre-commit; sizing changes post-Phase-3 are not permitted under §15.

**Eight substrates initiated. Seven closed FAILED, one in flight (microstructure #4).** The discipline is calibrated correctly across both predictive and premium-harvest substrate classes. The honest read across all seven closures: at retail-data-grade with parametric costs, deflation against ≥6-trial pre-commits, and honest carry accounting, neither predictive anomalies (substrates 1-6) NOR premium-harvest implementations (#7 ETP, #9 iron condor) survive. The five predictive failures share the row-2 / Mode A pattern with variants (Mode B horizon-bound, Mode C sign inversion); the VIX ETP failure is **Mode D: signal-too-small-to-detect-at-pre-committed-sizing**; the iron condor failure is **Mode E: binary filter effective, continuous predictor relationship absent** — premium harvest is real (11/11 years positive) but VRP level doesn't predict cycle-level P&L. **Both premium-harvest attempts confirmed the premium exists; both failed the gauntlet's continuous-predictor requirement.**

**Substrate #7 (VIX) is the first deliberate constraint shift of the project.** Substrates 1-6 all shared one structural assumption: alpha comes from prediction. VIX breaks that. It does not predict; it harvests a structural premium that exists because portfolio managers systematically overpay for insurance. Edge is not better forecasting — it is *being the insurance writer*. The premium's existence is documented (Bondarenko 2004, Carr & Wu 2009); the gauntlet asks whether retail-scale implementation survives costs + tail risk + factor residualization + DSR deflation against 28 pre-committed trials. **If VIX fails, the failure mode tells us something specific** (arbitraged away, tail risk too severe, or disguised factor exposure) and informs whether the next move is paid data, market-making, or abandoning systematic alpha. Microstructure (#4) is still in flight on Binance L2 book-data accumulation through ~2026-06-17.

**Live execution loop is paused.** `alphaforge-execution/.halt` is engaged; `run_daily.sh` exits with `HALTED` on every cron fire. The 10 Alpaca paper positions across the momentum and MARL accounts were flattened on 2026-04-26 via `alphaforge-execution/scripts/tier1_close_positions.py`. Re-launch requires the four conditions in `alphaforge-execution/docs/TIER1_PAUSE.md`. With Tier 1 + Tier 2 failed, those conditions cannot be met from the current state; the `.halt` stays on indefinitely.

**Tier 1 outcome (2026-05-02):** the pre-committed binary gate (DSR > 0.95 on residualized PIT S&P 500 returns + bootstrap CI excludes zero + sign agreement, both OOS windows) FAILED. 0 of 9 single factors and 0 of 4 combinations cleared. The closest result was an MV combination at alpha-residual OOS Sharpe +3.06 / +2.43 with DSR 0.92 / 0.70 — failed the deflation hurdle. Full writeup: `alphaforge-python/research/PHASE6_WRITEUP.md`. Phase 6 §4 committed the diagnostic to row 2 of the failure-path matrix ("real signal eaten by costs/multiple-testing → execution problem").

**Tier 2 outcome (2026-05-02):** the row-2 hypothesis was tested on the same PIT S&P 500 substrate with a pre-committed 8-strategy trial set at lower turnover (63d / 126d rebalance) plus volcap and forced-shrinkage variants. **Outcome 3 (clean fail): 0 strategies survive, no near-misses.** MV-21 alpha did not transport to longer rebalance horizons (MV-21: +3.06 alpha → MV-63: +0.79 → MV-126: +0.95). This is the inverse of what row 2 predicted; the MV signal appears to be a short-horizon-specific phenomenon, not a real cross-sectional anomaly eaten by costs. Full verdict: `alphaforge-python/research/TIER2_VERDICT.md`.

**Current state — five failed substrate attempts, one in flight. Founder-track substrate-class decision pending.**

| # | Substrate | Outcome | Date | Diagnosis |
|---|---|---|---|---|
| 1 | Equity Tier 1 (PIT S&P 500 cross-section) | CLOSED FAILED | 2026-05-02 | Row 2: real signal, costs+multiple-testing |
| 2 | Equity Tier 2 (lower-turnover variant) | CLOSED FAILED | 2026-05-02 | Same substrate, different parameters — clean fail |
| 3 | Crypto Carry (Binance USDT-M funding) | CLOSED FAILED | 2026-05-15 | Same row 2 — signal IC=0.5 but costs+DSR penalty win |
| 4 | Microstructure (BTC-USDT L2 + tape) | IN PROGRESS | 2026-05-17 → +30d | — (Phase 0 book-data accumulation) |
| 5 | PEAD (EDGAR XBRL on PIT S&P 500) | CLOSED FAILED | 2026-05-17 | Same row 2 — "real but weak", 0/10 cleared deflation |
| 6 | India (NSE bhavcopy + delivery + F&O) | CLOSED FAILED | 2026-05-20 | Row 2 with sign inversion — 0/18 cleared, all OOS Sharpes negative |
| 7 | VIX / Variance Risk Premium (CBOE + SPY) | CLOSED FAILED | 2026-05-21 | Mode D — first Phase-1-PASS Phase-3-FAIL; signal real (peak IC +0.180) but §9.1 sizing too small for DSR after deflation; 0/28 deploy-ready |
| 8 | Substrate #8 — VIX 20× ETP sizing | CLOSED FAILED | 2026-05-21 | Sharpe invariant to linear scaling — mean and std both scale by k, k cancels; identical failure |
| 9 | Iron Condor Options (SPY BS reconstruction) | CLOSED FAILED | 2026-05-26 | Mode E — premium real (11/11 IS years positive, mean +$0.19/share) but corr(VRP_entry, P&L) = -0.015; binary filter works, continuous predictor absent |

On 2026-05-15 the user explicitly overrode the §7 reset cooldown (originally locked until 2026-06-01) and pivoted to a crypto substrate via Binance public data. The crypto pivot tested whether the equity-factor failure was substrate-specific. **It wasn't.** Both substrates failed via the same row-2 mechanism (real signal eaten by honest costs and multiple-testing deflation).

The equity sub-projects (`alphaforge-python/`, `-marl/`, `-execution/`) remain frozen; `.halt` stays engaged on the execution loop. The crypto sub-project (`alphaforge-crypto/`) has the carry study CLOSED FAILED; the basis study stub is NOT auto-activated. Methodology hygiene (pre-commit gates, DSR, bootstrap CIs, honest costs) is the load-bearing piece across both substrates — it worked exactly as designed, and it kept failing strategies from being deployed.

**The honest question is no longer "what substrate?" It's "what strategy class?"** Cross-sectional rank-based signals with linear combinations and parametric costs do not survive in either equity or crypto on US-data substrates. India (#6) is the first test of whether geographic-market thinness + event-driven/flow-based signal class (NOT cross-sectional rank) breaks the row-2 pattern. Microstructure (#4) is the first test of whether HFT-saturated execution-alpha capture is reachable at retail latency. If both fail, the remaining unexplored options are different *classes*: spin-off arbitrage (Greenblatt 1997, retail-scale documented), microcap value + quality, vol-surface anomalies, crypto on-chain analytics. See `alphaforge-crypto/research/CARRY_STUDY_VERDICT.md` §"What this means for the next substrate decision".

**Reading order for new sessions:**
- For substrate #6 context: `alphaforge-india/research/INDIA_DESIGN.md` → `alphaforge-india/CLAUDE.md`.
- For substrate #5 verdict: `alphaforge-pead/research/PHASE1_VERDICT.md` → `alphaforge-pead/CLAUDE.md`.
- For substrate #4 plan: `alphaforge-microstructure/research/PHASE1_DESIGN.md` → `alphaforge-microstructure/CLAUDE.md`.
- For substrate #3 verdict: `alphaforge-crypto/research/CARRY_STUDY_VERDICT.md` → `alphaforge-crypto/research/CARRY_STUDY_DESIGN.md` → `alphaforge-crypto/CLAUDE.md`.
- For equity-stack history (substrates #1 + #2): `TIER1_STATUS.txt` → `alphaforge-python/research/PHASE6_WRITEUP.md` → `alphaforge-python/research/TIER2_VERDICT.md`.

The equity history matters for *why we pivoted*; the crypto/PEAD history matters for *why each pivot didn't help*; India + microstructure are the open questions. *What to do next* if those also fail is a founder decision, not a methodology decision.

**Phase-1 universe substrate vs the legacy 50-name universe.** The 50 today-surviving large-caps in `data/market/universe.py` are the LEGACY substrate kept for the headline factor study and JS-parity smoke tests. The PIT 877-ever-member universe is the NEW substrate consumed via `validator.membership_on_date(events, baseline, date) -> set[ticker]`. Don't conflate them.

## Commands

```bash
# alphaforge-python (531 tests as of 2026-04-29)
cd alphaforge-python
python3 -m pytest tests/ -v --tb=short
python3 -m pytest tests/test_prng.py -k "test_first_five"  # single test
uvicorn api.server:app --reload                              # API at :8000
python3 research/phase3_stage_inputs.py --help
python3 research/phase3_check_inputs.py --help
python3 research/phase3_validate_ff5.py --help

# alphaforge-marl (122 tests)
cd alphaforge-marl
python3 -m pytest tests/ -v --tb=short
uvicorn api.server:app --reload --port 8001                  # API at :8001
python3 validate_convergence.py --quick                      # convergence check

# alphaforge-execution (122 tests)
cd alphaforge-execution
python3 -m pytest tests/ -v --tb=short
python3 run_backtest.py --start 2024-01-01 --end 2024-12-31
uvicorn api.server:app --host 0.0.0.0 --port 8002 --reload  # API at :8002

# Top-level — rebuild every headline research artifact from the parquet store
make all          # factor-study + capacity-study + marl-rigor + ablation-ladder
make tests        # full test matrix across the three sub-projects
```

Seeding for every stochastic study is documented in `SEEDS.md`. The GitHub
Actions workflow at `.github/workflows/research-ci.yml` runs the full test
matrix and diffs rebuilt headline metrics against the committed JSON to
catch silent numerical drift.

## JS Frontend

**No build step.** All JS loaded via `<script>` tags. Chart.js vendored locally as `chart.min.js`.

All modules communicate through globals on `window`:
- **`data.js`** (`window.AlphaData`) — Seeded PRNG (Mulberry32), synthetic fallback price/volume generation, factor scoring (cross-sectional z-score), backtest engine. All numerics use `safeDiv`, `sanitizeNumber`, `validateSeries`, `clamp`.
- **`app.js`** (`window.AlphaApp`) — Tab switching, workspace controls, dispatches to modules. Loads last, calls each module's `init()`.
- **`scanner.js`** / **`correlation.js`** / **`ai-engine.js`** / **`marl.js`** / **`execution.js`** — Feature modules for each tab. (The earlier `backtester.js` was removed; the canonical research backtester lives in Python.)

**Key patterns:**
- Global state via `AlphaApp.getState()` → `{ sector, lookback, activeTab }`.
- Primary workflow now hits the `alphaforge-python` API, which serves real-market history from the local parquet store. The seeded-PRNG synthetic path remains as an offline fallback.
- Five alpha factors: Momentum (12-1), Mean Reversion (5d), Volume Surge, RSI Divergence, Earnings Drift.
- Script load order matters: `data.js` first, `app.js` last.

## Python Backend (`alphaforge-python/`)

### Architecture

- **`data/`** — Mulberry32 PRNG (`prng.py`), synthetic ticker universe + GBM generator (`universe.py`, `synthetic.py`), feature engineering (`features.py`), plus the real-market layer: `data/market/` (parquet store, downloader, loader, real ticker universe), `real_dataset.py` (loads aligned OHLCV history from the local parquet store into `PriceSeries` objects). `sync_market_data.py` at the project root is the only module that touches yfinance; everything else reads from parquet.
- **`data/market/pit/`** — **Phase 1 point-in-time S&P 500 universe stack.** See `data/market/PIT_UNIVERSE_DESIGN.md` for the contract. Modules: `parser.py` (multi-format constituents-table parser with caption/ref-tag/header-shift defenses), `cik.py` (EDGAR ticker→CIK with `.↔-` share-class normalization), `differ.py` (CIK-based ADD/REMOVE/RENAME differ with action-precedence + suspect-pair guard), `enumerate_revisions.py` (Wikipedia revision-walker with byte-delta + comment-keyword hybrid filter), `fetch_content.py` (batched-50 wikitext fetcher), `changes_parser.py` (parses Wikipedia's curated "Selected changes" table for cross-check), `validator.py` (`membership_on_date(events, baseline, date) -> set[ticker]` is the canonical membership accessor for downstream code; also runs `cross_check_against_changes_table`), `history.py` (Phase 3 substrate: membership-aware panels over `data/quarantine/market/`), and `sector_map.py` (builds a static ever-member ticker→sector map from the cached snapshot corpus so PIT studies can still do sector-neutralization). Orchestrators: `session{1..5}_*.py`. Outputs land in `data/market/pit/artifacts/`: `_event_log.parquet` (837 rows), `_baseline_2010-01-10.parquet` (500 tickers from rev 339455897), `_session{1..5}_audit.json`. Pytest fixture `tests/test_pit_universe_fixture.py` (12 tests, all passing) is the regression gate.
- **`factors/`** — `BaseFactor` ABC with `compute()` (enhanced) and `compute_js()` (JS parity). Registry pattern via `FACTOR_REGISTRY`. 9 factors total: the 5 JS-parity factors (Momentum 12-1, Mean Reversion 5d, Volume Surge, RSI Divergence, Earnings Drift), plus Python-only Low Volatility, Amihud Illiquidity, Idiosyncratic Volatility, and Residual Reversal (5d). The last two override `compute_universe` to compute an equal-weighted market return once and reuse it per ticker — they produce 0 in the single-ticker fallback.
- **`factors/scoring.py`** — Cross-sectional z-score pipeline (`compute_factor_scores_js`). Imported by the optimizer, correlation matrix, scanner, MARL env, execution strategy, and the surviving backtest paths. Lives outside `backtest/` so non-backtest callers don't pull in the engine module.
- **`backtest/`** — Two deliberately separate surfaces now live here: `synthetic_demo.py` (`run_synthetic_backtest`) is the JS-parity demo on Mulberry32 synthetic data and must remain bit-for-bit aligned with the frontend; `event_driven_adapter.py` is the compatibility layer that maps the legacy backtest API schema onto the canonical event-driven engine for real-data requests. `real_engine.py` was retired in Phase 2 because its same-bar fills, daily clamp, and flat rebalance-cost deduction were architecturally wrong.
- **`backtest/event_driven/`** — Canonical real-data backtest engine. Architecturally enforces no-look-ahead (`BarHistory` raises if it holds any row past its `as_of`), no same-bar fills (`ExecutionHandler` requires next-bar timestamp strictly later than the order), and per-fill cash costs (slippage + commission charged on each `FillEvent`, not as a flat post-hoc bps deduction). Components: `events.py`, `data_handler.py` (`DataHandler` + PIT `BarHistory`), `strategy.py` (`Strategy` ABC + reference `MomentumLongShort` / `PanelStrategy`), `execution.py` (`ExecutionHandler`, `FlatSlippageModel`, `SameBarCloseExecutionHandler`), `portfolio.py` (positions/cash/NAV marks that fail loudly on missing prices), `core.py` (`EventDrivenEngine`).
- **`optimizer/`** — Markowitz mean-variance optimizer (`optimize_portfolio()`). Supports long-only/long-short/market-neutral modes. Uses scipy SLSQP, Ledoit-Wolf covariance shrinkage, factor-score-blended expected returns.
- **`scanner/`** / **`correlation/`** — Factor screening and correlation/IC/turnover analysis.
- **`research/`** — Headline research artifacts. All scripts read from the parquet store, never the network, and write to `research/out/`:
  - **`risk_model.py`** — Phase 3 helper module for factor-model OLS, no-look-ahead rolling residualization, replica-vs-reference factor correlation checks, and the explicit local reference-factor contract (`load_reference_factor_table`) for FF5+UMD validation.
  - **`ff5_replication.py`** — Strict local characteristics contract plus the PIT-based FF5+UMD replica builder. It intentionally refuses to infer FF5 inputs from OHLCV alone; you must stage a local monthly characteristics table with `market_cap`, `book_to_market`, `profitability`, and `investment`.
  - **`PHASE3_DATA_CONTRACT.md`** — Canonical doc for the two required local Phase 3 inputs, their exact schema, and the staging/check/validation command flow.
  - **`phase3_stage_inputs.py`** — Normalizes raw local reference-factor and characteristics files into the canonical Phase 3 schema and fails fast on duplicate keys.
  - **`phase3_check_inputs.py`** — Sanity-checks staged Phase 3 inputs for coverage, missingness, duplicate keys, and obvious unit mistakes before the overlap gate.
  - **`phase3_validate_ff5.py`** — CLI gate for Phase 3. Loads a PIT close panel, local characteristics table, and local daily reference factor file; builds the replica; computes overlap correlations; writes `research/out/phase3_ff5_validation.json`; exits nonzero if any factor lands below 0.85 correlation.
  - **`factor_study.py`** — Builds 8 vectorized factor panels (5 JS-parity + Amihud Illiquidity + Idiosyncratic Volatility + Residual Reversal; IVOL and Residual Reversal residualize against the equal-weight market in a 60-day rolling regression). It now defaults to the PIT/quarantine substrate (`ALPHAFORGE_FACTOR_STUDY_UNIVERSE_MODE=pit`) and uses the PIT sector-map cache for the D2 within-sector demean step. The study runs the full pipeline twice — raw and sector-neutral — and emits IC + IC-decay, quintile-spread backtests with realistic tx costs, stationary-bootstrap Sharpe CIs, Deflated Sharpe across the full factor trial set, regime splits, equal-weight / random long-short baselines, and a final-window train/test split at `OOS_START=2024-01-02` with a 21-day embargo (D4). Also surfaces Hansen SPA + White's Reality Check p-values on the K × T net-return matrix for both variants, and a purged + embargoed CV IC per factor at the 21-day horizon. When `ALPHAFORGE_FACTOR_STUDY_RESIDUALIZE=1`, the IC/backtest/baseline path runs on no-look-ahead rolling FF5+UMD residual returns loaded from `ALPHAFORGE_REFERENCE_FACTORS`. Writes `factor_study_report.md`, `factor_study_results.json`, `net_navs.csv`.
  - **`cost_model.py`** — Honest transaction cost library: `SquareRootImpactModel` (k·√participation), `corwin_schultz_spread` (High/Low based half-spread estimator), `BorrowCostTable` (annualized bps with HTB override map), and `HonestCostModel` aggregator. Used by capacity_study and available for future backtest refactors.
  - **`capacity_study.py`** — AUM-grid sweep under the square-root impact model (capacity curve), tercile regime-conditional Sharpe with bootstrap CIs, OHLCV-only crowding proxies (rolling Sharpe decay + own-return autocorrelation). Writes `capacity_report.md`, `capacity_results.json`, `capacity_curve.csv`.
  - **`stats_hygiene.py`** — `hansen_spa_test` (Hansen 2005 SPA with stationary bootstrap), `white_reality_check` (White 2000, naive bootstrap — strictly more conservative than SPA, reported alongside), and `PurgedEmbargoedKFold` (López de Prado 2018). Importable from any study that needs strict multiple-testing and label-leakage controls.
- **`api/`** — FastAPI with CORS. Routes: health, backtest, optimize, scanner, factors, correlation. Prefix: `/api/v1`.

### JS/Python Parity

PRNG, price generation, factor scoring, and backtest produce numerically identical results to JS. Verified to 10 decimal places. Each factor has `compute_js()` for exact parity and `compute()` with enhanced formulas. Parity tests use `tests/fixtures/js_reference_output.json`.

### Legacy

The flat `alphaforge/` package is superseded. Import from `data`, `factors`, `backtest`, `scanner`, `correlation`, `optimizer`.

## MARL Framework (`alphaforge-marl/`)

Multi-layer pipeline: **TradingEnv → AgentPool → EvolutionaryEngine (NSGA-II + speciation + MAML) → RegimeBandit (HMM) → Ensemble**

- **`env/`** — Gymnasium `TradingEnv`. 57-dim obs, 5 discrete actions (or 10-dim continuous weights). Dense reward shaping (rolling Sharpe delta + drawdown penalty + participation) plus Sharpe-based terminal reward. Curriculum scheduler ramps tx costs, leverage, stops, episode length. `env/real_data.py` sources aligned OHLCV from the shared parquet store — training/validation never touch the network.
- **`agents/`** — `BaseAgent` wraps an `ActorCriticNetwork` with multi-head attention over per-ticker features. `ContinuousActorCritic`, `DQNHead`, `PPOTrainer` (GAE + clipped surrogate), `MAMLTrainer` (FOMAML), `EnsemblePolicy`, `ParetoFront`, `AgentPool`.
- **`evolution/`** — Per-generation: evaluate (common random numbers) → PPO fine-tune → periodic MAML → NSGA-II select on (Sharpe, drawdown, turnover) → speciated reproduction (Jensen-Shannon distance) → per-parameter adaptive mutation.
- **`bandit/`** — HMM regime detector (K-Means init + Baum-Welch), Thompson sampling per (regime, agent), capital allocator feeding the ensemble policy.
- **`training/`** — `Trainer` orchestrator and `WalkForwardValidator` (anchored splits, strict temporal isolation, reports overfitting ratio and val/test correlation). Real-data walk-forward is the headline evaluation path; synthetic windows remain available for smoke tests.

**Headline evaluation scripts:** `run_walk_forward.py` (anchored train/validate/test on real data), `evaluate_real_market.py`, `run_real_baselines.py`, `run_ablation_batch.py`, `run_benchmark_report.py`, `run_retrain_stability.py`, `run_reward_mix_sweep.py`.

**Rigor report:** `research/marl_rigor.py` scans every `training.jsonl` and summary JSON under the MARL tree, enumerates the full trial count, and applies the same statistical hygiene as the single-factor study (Deflated Sharpe, baseline-excess Sharpe distribution, seed-stability summary). Output: `research/out/marl_rigor_report.md` + `marl_rigor_metrics.json`. Re-run after any new stability/ablation/reward-mix batch to get a deflation-aware assessment of whether the checkpoints have credible alpha over equal-weight.

**Ablation ladder:** `research/ablation_ladder.py` complements the rigor report with *paired* stationary-bootstrap Sharpe-difference tests across configurations found in summary artifacts. It looks for directory-name prefixes `baseline_equal_weight`, `single_agent_ppo`, `no_bandit`, `no_evolution`, `marl_full` and reports, for each adjacent rung and for each rung versus equal-weight, the observed ΔSharpe with a 95% paired-bootstrap CI. A rung whose CI brackets zero adds no statistically distinguishable lift and is a prune candidate. Output: `research/out/ablation_ladder_report.md` + `ablation_ladder_results.json`.

**Daily-series logging.** `training.baselines.compute_performance_metrics` returns `daily_returns` + `nav_series` lists alongside scalar metrics, and `aggregate_metric_dicts` concatenates list-valued keys across windows (scalars are still averaged). Any run that goes through `evaluate_checkpoint_cost_grid` or `evaluate_baselines` — stability, ablations, walk-forward, benchmark — now persists per-day portfolio paths inside its `oos_metrics` / fold metrics, enabling stationary-bootstrap Sharpe CIs and baseline-excess computation at report time without re-running the environment. The same list-vs-scalar split is mirrored in `Trainer._aggregate_validation_metrics` so the training loop doesn't crash on the new fields.

**Critical:** `env/trading_env.py` dynamically adds `alphaforge-python/` to `sys.path`. Both directories must be siblings under `Quant Alpha/`.

**Config:** `configs/default_config.yaml`. Access via `config.section.get(key, default)` — direct attribute access raises `AttributeError` on missing keys.

**Convergence validation:** `python3 validate_convergence.py --quick` runs training and produces a structured report with fitness trajectory, validation Sharpe, PPO diagnostics, and best-agent evaluation.

## Execution System (`alphaforge-execution/`)

Daily trading loop: fetch prices → momentum ranking → risk checks → order execution → snapshot recording → circuit breakers.

- **`execution/`** — Abstract `Broker` ABC, `PaperBroker` (local sim with slippage), `AlpacaBroker` (paper trading API).
- **`strategy/momentum.py`** — Composite of 5d momentum (40%), 21d momentum (40%), mean reversion (20%). Top N equal-weight.
- **`risk/limits.py`** — Pre-trade checks (position size, exposure, turnover) + circuit breakers (daily loss, max drawdown).
- **`risk/kill_switch.py`** — Enforces the `kill_switch:` YAML config (C6). `KillSwitch.end_of_day()` is called by `ExecutionEngine.run_day` after every snapshot; it evaluates all 6 triggers (max drawdown, single-day loss, consecutive losing days, realized slippage median, realized cumulative fill-error drag, minimum liquid tickers) and — when halted — takes over `run_day` on subsequent sessions to walk the unwind ladder (scales current weights down to the ladder's cumulative target fraction) and block new entries. Re-arm requires a line starting with `ACK:` in the pager file. Legacy `engine.halted = True` callers still get the pre-existing early-return behavior; the kill-switch path only engages when its own trigger set fires.
- **`portfolio/tracker.py`** — NAV tracking, Sharpe, drawdown, win rate.
- **`storage/`** — SQLite with `orders`, `snapshots`, `signals` tables. Auto-created schema.
- **`research/slippage_reconciliation.py`** — Reads the `orders` table and compares realized slippage to the backtest's assumed `broker.slippage_bps`. Emits a distribution summary, self-contained two-sample KS test (no scipy), and cumulative NAV drag from fill error. Run nightly against the live SQLite database to detect when realized execution quality diverges from backtest assumptions. Output: `research/out/slippage_reconciliation.md` + `.json`.

**Config:** `configs/execution_config.yaml`. Momentum formula extracted from MARL environment's `_rank_tickers()`. The `kill_switch:` section defines halt triggers (max drawdown, single-day loss, consecutive losing days, realized slippage median, cumulative fill-error drag, minimum liquid ticker count) and a three-stage unwind ladder (25% at halt, 50% at +4h, 100% by next close). Trigger re-arming requires a human `ACK:` line in the pager file. Full playbook in `docs/kill_switch_playbook.md`.

## Cross-Project Data Flow

```
                            Wikipedia revisions API + EDGAR
                                       │
                                       ▼
                    alphaforge-python/data/market/pit/
                         (PIT membership event log,
                          baseline, validator)
                                       │
                                       │  validator.membership_on_date(date)
                                       ▼
                    Phase 4-5 factor study / backtests
                    (consumes time-varying membership)
                                       │
yfinance ───(bulk pull)──▶  data/quarantine/market/<TICKER>/<YEAR>.parquet
                            (655 / 881 ever-members on disk; 226 delisted/no data)
                                       │
                                       ├─▶ alphaforge-python  (factor scoring, backtest, optimizer)
                                       │       ↓ imported via sys.path
                                       ├─▶ alphaforge-marl    (env/real_data.py → TradingEnv)
                                       │
                                       └─▶ alphaforge-execution  [PAUSED — .halt engaged]
                                           (daily loop, Alpaca paper-trade — re-launch
                                            requires Tier 1 gate; see TIER1_PAUSE.md)
```

- **PIT layer is the new source of truth for "who was in the index on date X".** All Phase 4-5 work must consume membership via `validator.membership_on_date()` rather than the legacy 50-name list in `data/market/universe.py`.
- The OHLCV parquet store at `data/quarantine/market/` is shared by all sub-projects. Only `sync_market_data.py` and the new `pit/fetch_content.py` (Wikipedia) touch the network.
- 226 of 881 ever-member tickers have no yfinance data (delisted/restructured). Phase 4-5 must treat these as known data gaps in any reported metric.
- Synthetic PRNG data still exists for JS parity tests and offline smoke tests, but it is no longer the default training/eval substrate.
- The JS frontend calls the `alphaforge-python` API for real-data scans/backtests; its local-only mode uses the synthetic fallback.
- **`alphaforge-microstructure/` and `alphaforge-india/` have INDEPENDENT data flows** that do not touch the equity stack: microstructure pulls BTC-USDT L2 + tape live from Binance; India pulls NSE bhavcopy + MTO + FII/DII from `archives.nseindia.com`. Neither sub-project reads from `data/quarantine/market/` or unfreezes any equity module.

## Defensive Numerics

All three Python backends and the JS frontend use the same pattern: `safe_div()`, `sanitize_number()`, `clamp()`, and `validate_series()` to prevent NaN/Infinity propagation. Always use these when writing new numeric code.

<!-- code-review-graph MCP tools -->
## MCP Tools: code-review-graph

**IMPORTANT: This project has a knowledge graph. ALWAYS use the
code-review-graph MCP tools BEFORE using Grep/Glob/Read to explore
the codebase.** The graph is faster, cheaper (fewer tokens), and gives
you structural context (callers, dependents, test coverage) that file
scanning cannot.

### When to use graph tools FIRST

- **Exploring code**: `semantic_search_nodes` or `query_graph` instead of Grep
- **Understanding impact**: `get_impact_radius` instead of manually tracing imports
- **Code review**: `detect_changes` + `get_review_context` instead of reading entire files
- **Finding relationships**: `query_graph` with callers_of/callees_of/imports_of/tests_for
- **Architecture questions**: `get_architecture_overview` + `list_communities`

Fall back to Grep/Glob/Read **only** when the graph doesn't cover what you need.

### Key Tools

| Tool | Use when |
|------|----------|
| `detect_changes` | Reviewing code changes — gives risk-scored analysis |
| `get_review_context` | Need source snippets for review — token-efficient |
| `get_impact_radius` | Understanding blast radius of a change |
| `get_affected_flows` | Finding which execution paths are impacted |
| `query_graph` | Tracing callers, callees, imports, tests, dependencies |
| `semantic_search_nodes` | Finding functions/classes by name or keyword |
| `get_architecture_overview` | Understanding high-level codebase structure |
| `refactor_tool` | Planning renames, finding dead code |

### Workflow

1. The graph auto-updates on file changes (via hooks).
2. Use `detect_changes` for code review.
3. Use `get_affected_flows` to understand impact.
4. Use `query_graph` pattern="tests_for" to check coverage.
