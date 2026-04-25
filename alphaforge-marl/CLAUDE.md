# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AlphaForge MARL is a Multi-Agent Reinforcement Learning framework for evolving trading strategies. It builds on top of the `alphaforge-python` alpha engine (sibling directory) and uses neuroevolution + regime-conditional Thompson sampling to train a population of trading agents.

## Commands

```bash
# Run full test suite (104 tests)
python3 -m pytest tests/ -v --tb=short

# Run a single test file
python3 -m pytest tests/test_env.py -v

# Run a specific test
python3 -m pytest tests/test_agents.py -k "test_clone" -v

# Start MARL API server
uvicorn api.server:app --reload --port 8001

# Run training programmatically
python3 -c "from training.trainer import Trainer; Trainer().train(n_generations=5)"

# Walk-forward validation (train 2022-2023, validate 2024, test 2025)
python3 run_walk_forward.py                     # Full run (30 gens/fold)
python3 run_walk_forward.py --quick             # Smoke test (5 gens, 5 agents)
python3 run_walk_forward.py --n-gens 50 --output results.json

# Convergence check
python3 validate_convergence.py --quick
```

## Architecture

The system is a multi-layer pipeline: **Environment → Agent Population → Evolutionary Engine (NSGA-II + Speciation + MAML) → Regime Bandit (HMM) → Ensemble**

**`env/`** — Gymnasium-compatible `TradingEnv`. 57-dim float32 observations. Supports discrete (5 actions) and continuous (10-dim weight vector) action spaces. Dense reward shaping: rolling Sharpe delta + drawdown-aware penalty + participation incentive per step, plus Sharpe-based episode-end reward. `set_continuous(True)` enables continuous portfolio weight output. Curriculum learning progressively increases difficulty (tx costs, leverage limits, stop-loss tightness, episode length).

**`agents/`** — `BaseAgent` wraps an `ActorCriticNetwork` (shared trunk with multi-head attention over per-ticker features → actor/critic heads) and optional `DQNHead`. `ContinuousActorCritic` outputs Gaussian per-ticker portfolio weights. `PPOTrainer` runs GAE + clipped surrogate updates. `MAMLTrainer` provides FOMAML meta-learning for fast regime adaptation. `EnsemblePolicy` blends multiple agents' action distributions weighted by regime bandit. `ParetoFront` maintains non-dominated agents across multiple objectives. `AgentPool` manages population with ranked fitness, elite/survivor selection.

**`evolution/`** — `EvolutionaryEngine` runs: evaluate (common random numbers) → PPO fine-tune → MAML meta-update (periodic) → NSGA-II multi-objective selection (Sharpe, drawdown, turnover) → speciated reproduction (per-species offspring allocation) → per-parameter adaptive mutation. `SpeciationManager` groups agents by behavioral distance (Jensen-Shannon divergence of action distributions). `nsga2.py` implements fast non-dominated sort + crowding distance.

**`bandit/`** — `RegimeDetector` uses an HMM (Hidden Markov Model) with K-Means initialization + Baum-Welch EM for temporal regime persistence. `ThompsonSampler` maintains Beta posteriors per (regime, agent) pair, now integrated into training fitness. `CapitalAllocator` combines both for regime-conditional ensemble weighting.

**`training/`** — `Trainer` orchestrates everything: curriculum scheduling, regime detector fitting, regime-weighted fitness blending, Pareto front/ensemble updates, validation-based early stopping, checkpointing, and JSONL logging. `WalkForwardValidator` implements anchored walk-forward analysis with strict temporal splits (train/validate/test) on real market data — no future data leakage. Reports overfitting ratio and val/test correlation. `baselines.compute_performance_metrics` returns `daily_returns` + `nav_series` lists inside every metric dict; `aggregate_metric_dicts` concatenates list-valued keys across windows so cost-grid and fold aggregates carry one combined daily path (scalars are averaged as before). `Trainer._aggregate_validation_metrics` does the same list-vs-scalar split. Downstream: bootstrap CIs on OOS Sharpe and baseline-excess computation can be done at report time with no re-evaluation.

**`research/`** — `research/marl_rigor.py` is the deflation-aware assessment script. It scans every `training.jsonl` and summary JSON under the MARL tree, enumerates the full generation-level trial count, computes the Bailey & López de Prado Deflated Sharpe Ratio against that trial count, summarizes the baseline-excess Sharpe distribution from the reward-mix logs, and reports seed-stability spread. Writes `research/out/marl_rigor_report.md` + `marl_rigor_metrics.json`. Re-run after any new stability / ablation / reward-mix batch for an honest assessment of whether the checkpoints clear the DSR > 0.95 bar and beat equal-weight.

**`api/`** — FastAPI server with endpoints: `POST /train/start`, `POST /train/stop`, `GET /train/status`, `GET /train/history`, `POST /walk-forward/start`, `GET /walk-forward/status`, `WebSocket /ws` for real-time generation broadcasts. `GET /dashboard` serves a self-contained HTML monitoring page with fitness charts, regime detection, ensemble weights, and portfolio positions. Training runs in a background thread.

## Critical Dependencies

The environment (`env/trading_env.py`) imports from `alphaforge-python` by dynamically adding it to `sys.path`. The expected directory layout is:

```
Quant Alpha/
├── alphaforge-python/   # Alpha engine (data, factors, backtest)
└── alphaforge-marl/     # This repo
```

Specifically imported: `data.synthetic.generate_dataset`, `backtest.engine._compute_factor_scores_js`, `factors.registry.JS_FACTOR_NAMES`, plus `safe_div` and `clamp` helpers.

## Configuration

All hyperparameters live in `configs/default_config.yaml`. The `Config` dataclass provides dotted attribute access (e.g., `config.population.get("n_agents")`). Use `config.section.get(key, default)` — direct attribute access raises `AttributeError` on missing keys.

## Key Patterns

- **Param vectors**: All networks expose `param_vector()` / `load_param_vector()` for flat 1D tensor serialization — used by evolution (mutation, crossover) and checkpointing.
- **Agent cloning**: `BaseAgent.clone()` preserves `hidden_sizes` and `activation` so the child network has matching architecture. Forgetting to propagate these causes shape mismatches.
- **NaN safety**: `state_builder.py` runs `np.nan_to_num()` on all observations. `reward.py` checks `math.isfinite()` on output. All state helper functions return 0.0 or 0.5 on degenerate inputs.
- **Checkpoints**: `torch.save()` format storing agent param lists + metadata. Load with `load_checkpoint(path, pool)` which overwrites the pool's agents in-place.
- **Ticker attention**: `ActorCriticNetwork` splits obs into portfolio+regime (15d), ticker features (40d → attention), and time (2d). The `TickerAttention` module applies multi-head self-attention over 10 ticker slots to learn cross-ticker relationships.
- **Common random numbers**: `evaluate_population()` generates one set of seeds per generation, shared across all agents, for fair relative comparison.
- **Per-parameter mutation**: `mutate()` scales noise by `sigma * (1 + |w|)` so perturbation is proportional to weight magnitude.
- **Speciation**: `SpeciationManager` computes behavioral distance via Jensen-Shannon divergence of action distributions on fixed probe states. Species compete internally; offspring slots allocated proportional to adjusted fitness.
- **Curriculum**: `CurriculumScheduler` manages 4 stages (beginner→expert) with increasing tx costs, tighter leverage/stops, and longer episodes. Promotion based on fitness threshold + minimum generations at stage.
- **MAML**: `MAMLTrainer` uses FOMAML (first-order) to find weight initializations that adapt in K inner SGD steps to new regimes. Applied periodically to elite agents.
- **NSGA-II**: `nsga2_select()` uses fast non-dominated sort + crowding distance across Sharpe, drawdown, and turnover objectives. Replaces single-scalar fitness ranking for survivor selection.
- **Ensemble**: `EnsemblePolicy` blends action distributions from `ParetoFront` agents, weighted by `CapitalAllocator` regime scores.
- **Walk-forward**: `WalkForwardValidator` trains on historical windows, validates on the next period, tests out-of-sample. Reports overfitting ratio (test/val Sharpe) and val-test correlation. Default split: train 2022-2023, validate 2024, test 2025.
- **Dashboard**: `GET /dashboard` serves a self-contained HTML page with Chart.js — auto-refreshes every 3s and receives WebSocket generation events. Shows fitness trajectory, regime state, ensemble weights, portfolio positions, and sigma evolution.
