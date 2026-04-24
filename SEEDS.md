# AlphaForge — Deterministic Seeds Manifest

Every stochastic component writes to a named seed so that a fresh clone
of the repo reproduces byte-identical research artifacts (within
float-order-of-operations tolerance) on the same Python / numpy versions.

## Global entry point

All scripts respect the environment variable `ALPHAFORGE_GLOBAL_SEED`
(default `42`). The Makefile exports this before every target.

    export ALPHAFORGE_GLOBAL_SEED=42
    make all

## Per-component seeds

| Component | Seed | Notes |
|---|---|---|
| `data.prng.Mulberry32` | JS-parity: `hash_string(ticker) + global` | Synthetic PRNG; same outputs as JS frontend. |
| `research/factor_study.py` — stationary bootstrap | `abs(hash(factor_name)) % 2**31` | Per-factor so two factors never share resamples. |
| `research/factor_study.py` — random LS baselines | `range(N_BASELINE_SEEDS)` = 0..99 | Emits 100 independent Sharpes. |
| `research/capacity_study.py` — per-AUM bootstrap | `abs(hash(aum)) % 2**31` | Ensures each rung is independent. |
| `research/stats_hygiene.py` — Hansen SPA | caller-supplied `seed=` (default `0`) | factor_study passes `seed=7` when wired in. |
| `research/stats_hygiene.py` — Purged CV | deterministic (no RNG) | |
| `alphaforge-marl/research/ablation_ladder.py` — paired bootstrap | `SEED = 42` | Same for every rung so diffs are paired. |
| `alphaforge-marl` — PPO rollouts | `configs/default_config.yaml :: training.seed` | |
| `alphaforge-marl` — NSGA-II mutation | `configs/default_config.yaml :: evolution.seed` | Per-generation seed = base + generation. |
| `alphaforge-marl` — MAML task sampling | per-meta-batch seed derived from evolution seed | |
| `alphaforge-execution` — PaperBroker slippage | deterministic (constant bps, no randomness) | Live fills are non-deterministic by nature. |

## Re-running a single study

    make clean                    # remove all generated reports
    ALPHAFORGE_GLOBAL_SEED=123 make factor-study

## What is NOT reproducible

- **Live paper trading** (Alpaca) depends on real-time quotes and fill
  timing — not reproducible by design.
- **yfinance history fetches** are network-dependent; the parquet store
  is the deterministic substrate. Never run `sync_market_data.py` from
  CI or reproducibility pipelines.
