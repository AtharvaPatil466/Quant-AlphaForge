# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project Overview

AlphaForge is a quantitative alpha research platform with four components:
1. **Frontend** — Vanilla JS single-page app (`index.html`), no build system. Open directly in a browser.
2. **`alphaforge-python/`** — Python port of the JS data/simulation layer with REST API and mean-variance optimizer.
3. **`alphaforge-marl/`** — Neuroevolution + PPO multi-agent RL framework for evolving trading strategies.
4. **`alphaforge-execution/`** — Live paper trading system with yfinance data, Alpaca broker, and SQLite persistence.

Each Python sub-project has its own `AGENTS.md` with detailed architecture. This file covers the cross-cutting concerns and the JS frontend.

## Commands

```bash
# alphaforge-python (496 tests)
cd alphaforge-python
python3 -m pytest tests/ -v --tb=short
python3 -m pytest tests/test_prng.py -k "test_first_five"  # single test
uvicorn api.server:app --reload                              # API at :8000

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
- **`factors/`** — `BaseFactor` ABC with `compute()` (enhanced) and `compute_js()` (JS parity). Registry pattern via `FACTOR_REGISTRY`. 9 factors total: the 5 JS-parity factors (Momentum 12-1, Mean Reversion 5d, Volume Surge, RSI Divergence, Earnings Drift), plus Python-only Low Volatility, Amihud Illiquidity, Idiosyncratic Volatility, and Residual Reversal (5d). The last two override `compute_universe` to compute an equal-weighted market return once and reuse it per ticker — they produce 0 in the single-ticker fallback.
- **`factors/scoring.py`** — Cross-sectional z-score pipeline (`compute_factor_scores_js`). Imported by the optimizer, correlation matrix, scanner, MARL env, execution strategy, and both backtest engines. Lives outside `backtest/` so non-backtest callers don't pull in the engine module.
- **`backtest/`** — Long-short simulation engine (`engine.py`, public entry `run_synthetic_backtest`) + real-data variant (`real_engine.py`, `run_real_backtest`) that runs the same factor logic against the parquet store. 9 performance metrics, portfolio/position tracking, OLS attribution, Gymnasium TradingEnv.
- **`backtest/event_driven/`** — Event-driven engine that replaces the vectorized panel sweep. Architecturally enforces no-look-ahead (`BarHistory` raises if it holds any row past its `as_of`), no same-bar fills (`ExecutionHandler` requires next-bar timestamp strictly later than the order), and per-fill cash costs (slippage + commission charged on each `FillEvent`, not as a flat post-hoc bps deduction). Components: `events.py`, `data_handler.py` (`DataHandler` + PIT `BarHistory`), `strategy.py` (`Strategy` ABC + reference `MomentumLongShort`), `execution.py` (`ExecutionHandler` + `FlatSlippageModel`), `portfolio.py` (positions/cash/NAV marks that fail loudly on missing prices), `core.py` (`EventDrivenEngine`). Slated to absorb `engine.py` and `real_engine.py` after the reconciliation pass.
- **`optimizer/`** — Markowitz mean-variance optimizer (`optimize_portfolio()`). Supports long-only/long-short/market-neutral modes. Uses scipy SLSQP, Ledoit-Wolf covariance shrinkage, factor-score-blended expected returns.
- **`scanner/`** / **`correlation/`** — Factor screening and correlation/IC/turnover analysis.
- **`research/`** — Headline research artifacts. All scripts read from the parquet store, never the network, and write to `research/out/`:
  - **`factor_study.py`** — Builds 8 vectorized factor panels (5 JS-parity + Amihud Illiquidity + Idiosyncratic Volatility + Residual Reversal; IVOL and Residual Reversal residualize against the equal-weight market in a 60-day rolling regression). Runs the full pipeline twice — raw and sector-neutral (within-sector cross-sectional demean, D2) — and emits IC + IC-decay, quintile-spread backtests with realistic tx costs, stationary-bootstrap Sharpe CIs, Deflated Sharpe across the full factor trial set, regime splits, equal-weight / random long-short baselines, and a final-window train/test split at `OOS_START=2024-01-02` with a 21-day embargo (D4). Also surfaces Hansen SPA + White's Reality Check p-values on the K × T net-return matrix for both variants, and a purged + embargoed CV IC per factor at the 21-day horizon. Writes `factor_study_report.md`, `factor_study_results.json`, `net_navs.csv`.
  - **`cost_model.py`** — Honest transaction cost library: `SquareRootImpactModel` (k·√participation), `corwin_schultz_spread` (High/Low based half-spread estimator), `BorrowCostTable` (annualized bps with HTB override map), and `HonestCostModel` aggregator.
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

**Rigor report:** `research/marl_rigor.py` scans every `training.jsonl` and summary JSON under the MARL tree, enumerates the full trial count, and applies the same statistical hygiene as the single-factor study (Deflated Sharpe, baseline-excess Sharpe distribution, seed-stability summary). Output: `research/out/marl_rigor_report.md` + `marl_rigor_metrics.json`. Re-run after any new stability/ablation/reward-mix batch.

**Ablation ladder:** `research/ablation_ladder.py` complements the rigor report with *paired* stationary-bootstrap Sharpe-difference tests across configurations found in summary artifacts. It looks for directory-name prefixes `baseline_equal_weight`, `single_agent_ppo`, `no_bandit`, `no_evolution`, `marl_full` and reports, for each adjacent rung and for each rung versus equal-weight, the observed ΔSharpe with a 95% paired-bootstrap CI. A rung whose CI brackets zero adds no statistically distinguishable lift and is a prune candidate. Output: `research/out/ablation_ladder_report.md` + `ablation_ladder_results.json`.

**Daily-series logging.** `training.baselines.compute_performance_metrics` returns `daily_returns` + `nav_series` lists alongside scalar metrics, and `aggregate_metric_dicts` concatenates list-valued keys across windows (scalars are still averaged). Any run that goes through `evaluate_checkpoint_cost_grid` or `evaluate_baselines` now persists per-day portfolio paths inside its `oos_metrics` / fold metrics, enabling stationary-bootstrap Sharpe CIs and baseline-excess computation at report time without re-running the environment. The ablation ladder consumes exactly these `daily_returns` lists.

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
yfinance ──(one-off sync only)──▶ alphaforge-python/data/market/ (parquet store, one file per ticker-year)
                                           │
                                           ├─▶ alphaforge-python (real_dataset / real_engine: factor scoring, backtest, optimizer; research/* for factor / capacity / stats studies)
                                           │        ↓ imported via sys.path
                                           ├─▶ alphaforge-marl (env/real_data.py → TradingEnv; walk-forward train/validate/test on real history; research/* for rigor + ablation)
                                           │
                                           └─▶ alphaforge-execution (daily loop pulls live yfinance prices, runs extracted momentum + MARL strategies, Alpaca paper-trade; research/slippage_reconciliation.py closes the loop)
```

- The parquet store is the single source of truth for historical data. Only `sync_market_data.py` (and the execution daily loop) contact yfinance.
- Synthetic PRNG data still exists for JS parity tests and offline smoke tests, but it is no longer the default training/eval substrate.
- The JS frontend calls the `alphaforge-python` API for real-data scans/backtests; its local-only mode uses the synthetic fallback.

## Reproducibility

- **`Makefile`** — Every headline artifact rebuildable with one command. Targets: `factor-study`, `capacity-study`, `marl-rigor`, `ablation-ladder`, `slippage-reconciliation`, `tests`, `clean`.
- **`SEEDS.md`** — Per-component seed manifest. All stochastic studies honor `ALPHAFORGE_GLOBAL_SEED` (default 42), exported by the Makefile.
- **`.github/workflows/research-ci.yml`** — Matrix tests for all three sub-projects plus a headline-metrics drift diff that catches silent numerical regressions from dependency bumps or NumPy changes.

## Defensive Numerics

All three Python backends and the JS frontend use the same pattern: `safe_div()`, `sanitize_number()`, `clamp()`, and `validate_series()` to prevent NaN/Infinity propagation. Always use these when writing new numeric code.
