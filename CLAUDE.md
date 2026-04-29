# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AlphaForge is a quantitative alpha research platform with four components:
1. **Frontend** — Vanilla JS single-page app (`index.html`), no build system. Open directly in a browser.
2. **`alphaforge-python/`** — Python port of the JS data/simulation layer with REST API and mean-variance optimizer.
3. **`alphaforge-marl/`** — Neuroevolution + PPO multi-agent RL framework for evolving trading strategies.
4. **`alphaforge-execution/`** — Live paper trading system with yfinance data, Alpaca broker, and SQLite persistence.

Each Python sub-project has its own `CLAUDE.md` with detailed architecture. This file covers the cross-cutting concerns and the JS frontend.

## Project Status (active as of 2026-04-29)

The project is now framed as the foundational stack for a future hedge fund (see `~/.claude/projects/-Users-atharva-Quant-Projects-Quant-Alpha/memory/user_career.md`). It is executing **Tier 1 — Methodology Validation** per `~/.claude/projects/-Users-atharva-Quant-Projects-Quant-Alpha/memory/project_tier1_plan.md`. Read that plan before starting any new AlphaForge work — it has an explicit "not-doing" list to prevent scope drift.

**Live execution loop is paused.** `alphaforge-execution/.halt` is engaged; `run_daily.sh` exits with `HALTED` on every cron fire. The 10 Alpaca paper positions across the momentum and MARL accounts were flattened on 2026-04-26 via `alphaforge-execution/scripts/tier1_close_positions.py`. Re-launch requires the four conditions in `alphaforge-execution/docs/TIER1_PAUSE.md` (Tier 1 gate passed, signal is the survivor, universe expanded, ≥6 months paper trade).

**Phase 1 (point-in-time S&P 500 universe) is DONE.** New stack at `alphaforge-python/data/market/pit/` produces a 837-event chronological membership log 2010-2026 with 12/12 spot-check fixtures passing and 99% monthly return correlation against `^SP500EW`. Design contract + 5 sessions of lessons in `alphaforge-python/data/market/PIT_UNIVERSE_DESIGN.md`.

**Phase 2 (engine consolidation) is DONE.** `real_engine.py` was removed, `synthetic_demo.py` remains the JS-parity path, and `backtest/event_driven/` is the canonical real-data engine.

**Phase 3 (FF5 + momentum residualization) is the active deliverable.** The local inputs are now staged and the validation pipeline runs end-to-end. Current staged artifacts are `alphaforge-python/research/out/phase3_reference_staged.csv`, `alphaforge-python/research/out/phase3_characteristics_staged.csv`, and `alphaforge-python/research/out/phase3_ff5_validation.json`. The remaining blocker is methodology quality, not plumbing: latest overlap correlations are `MKT 0.9132`, `SMB 0.6456`, `HML 0.8676`, `RMW 0.2321`, `CMA 0.6325`, `UMD 0.8236`. The current best-measured replica variant uses annual June sorts plus OP/Inv-specific exclusions for `Financials`, `Real Estate`, and `Utilities`, but Phase 3 is still blocked on `SMB` / `RMW` / `CMA`.

**Phase-1 universe substrate vs the legacy 50-name universe.** The 50 today-surviving large-caps in `data/market/universe.py` are the LEGACY substrate kept for the headline factor study and JS-parity smoke tests. The PIT 877-ever-member universe is the NEW substrate that all Phase 4-5 work will consume via `validator.membership_on_date(events, baseline, date) -> set[ticker]`. Don't conflate them.

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

## Defensive Numerics

All three Python backends and the JS frontend use the same pattern: `safe_div()`, `sanitize_number()`, `clamp()`, and `validate_series()` to prevent NaN/Infinity propagation. Always use these when writing new numeric code.
