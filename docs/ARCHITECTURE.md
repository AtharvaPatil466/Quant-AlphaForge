# AlphaForge — System Architecture

*A technical overview for engineers, quant researchers, and technical evaluators.*

---

## 1. Design Philosophy

AlphaForge is built around three non-negotiable architectural principles:

1. **No look-ahead.** Every component that touches time-series data enforces point-in-time semantics. The backtest engine raises exceptions on future data access. The PIT universe module reconstructs index membership as it was on any given date, not as it is today. Factor panels are built with rolling windows that never peek forward.

2. **Defensive numerics everywhere.** Four functions — `safe_div()`, `sanitize_number()`, `clamp()`, `validate_series()` — are used in every computational module across all four sub-projects (JS frontend, Python backend, MARL environment, execution system). NaN and Infinity cannot propagate silently through any pipeline.

3. **Separate contracts, separate engines.** The project deliberately maintains two backtest engines that will never merge: one for JS-parity (bit-for-bit reproducibility with the browser frontend), one for architecturally correct research. This is not technical debt — it's a design decision driven by the fact that correctness and parity are fundamentally incompatible constraints.

---

## 2. System Overview

```
┌────────────────────────────────────────────────────────────────────────┐
│                        JS Frontend (index.html)                        │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │
│  │  Signal   │ │  Corr    │ │   AI     │ │  MARL    │ │   Live   │   │
│  │  Scanner  │ │   Lab    │ │  Engine  │ │ Training │ │ Trading  │   │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘   │
│       │             │            │             │            │          │
│       └─────────────┴────────────┴─────────────┴────────────┘          │
│                              │  API calls                              │
│                    ┌─────────┴─────────┐                               │
│                    │   backend.js      │  (routes to Python or local)   │
│                    │   data.js         │  (Mulberry32 PRNG fallback)    │
│                    └─────────┬─────────┘                               │
└──────────────────────────────┼──────────────────────────────────────────┘
                               │
          ┌────────────────────┼────────────────────┐
          │                    │                    │
          ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│ alphaforge-python│  │ alphaforge-marl │  │alphaforge-exec  │
│    :8000         │  │    :8001        │  │    :8002         │
│                  │  │                 │  │                  │
│ FastAPI + CORS   │  │ FastAPI + CORS  │  │ FastAPI + CORS   │
│                  │  │                 │  │                  │
│ ┌──────────────┐ │  │ ┌─────────────┐│  │ ┌──────────────┐ │
│ │    data/     │ │  │ │    env/     ││  │ │  execution/  │ │
│ │  (PRNG,      │ │  │ │ TradingEnv  ││  │ │  daily_loop  │ │
│ │   market,    │ │  │ │ (Gymnasium) ││  │ │  broker ABC  │ │
│ │   PIT)       │ │  │ └──────┬──────┘│  │ └──────┬───────┘ │
│ ├──────────────┤ │  │        │imports │  │        │         │
│ │   factors/   │◄├──┤────────┘       │  │ ┌──────┴───────┐ │
│ │  (11 factors,│ │  │ ┌─────────────┐│  │ │    risk/     │ │
│ │   registry)  │ │  │ │   agents/   ││  │ │  limits      │ │
│ ├──────────────┤ │  │ │ PPO, MAML   ││  │ │  kill_switch │ │
│ │  backtest/   │ │  │ │ ActorCritic ││  │ │  circuit brk │ │
│ │  synthetic   │ │  │ ├─────────────┤│  │ ├──────────────┤ │
│ │  event_driven│ │  │ │ evolution/  ││  │ │  strategy/   │ │
│ ├──────────────┤ │  │ │ NSGA-II     ││  │ │  momentum    │ │
│ │  optimizer/  │ │  │ │ speciation  ││  │ │  MARL bridge │ │
│ │  Markowitz   │ │  │ ├─────────────┤│  │ ├──────────────┤ │
│ ├──────────────┤ │  │ │  bandit/    ││  │ │  storage/    │ │
│ │  research/   │ │  │ │  HMM regime ││  │ │  SQLite      │ │
│ │  factor_study│ │  │ │  Thompson   ││  │ └──────────────┘ │
│ │  capacity    │ │  │ └─────────────┘│  │                  │
│ │  cost_model  │ │  │                │  │                  │
│ │  stats_hygn  │ │  │                │  │                  │
│ └──────────────┘ │  │                │  │                  │
└────────┬─────────┘  └────────────────┘  └─────────┬────────┘
         │                                          │
         └────────────────┬─────────────────────────┘
                          │
                          ▼
              ┌───────────────────────┐
              │  data/quarantine/     │
              │  market/<TICKER>/     │
              │  <YEAR>.parquet       │
              │                       │
              │  (655 / 881 tickers   │
              │   on disk)            │
              └───────────────────────┘
```

---

## 3. Data Layer

### 3.1 Dual Substrate Design

The project maintains two data substrates for different purposes:

| Substrate | Source | Tickers | Purpose |
|---|---|---|---|
| **Synthetic** | Mulberry32 PRNG + GBM | Deterministic per seed | JS-parity tests, offline smoke tests, frontend demo |
| **Real market** | yfinance → parquet store | 655 of 881 ever-members | All research, MARL training/eval, execution |

Only `sync_market_data.py` touches the network. Everything downstream reads parquet deterministically.

### 3.2 Point-in-Time Universe (Phase 1 Deliverable)

The PIT module at `data/market/pit/` answers the question: *"Which 500 tickers were in the S&P 500 on date D?"*

**Pipeline:**
```
Wikipedia revisions API  →  enumerate_revisions.py  (2,811 revisions)
                         →  hybrid filter            (1,118 candidates)
                         →  fetch_content.py          (batched wikitext)
                         →  parser.py                 (multi-format table parse)
                         →  cik.py                    (EDGAR CIK enrichment)
                         →  differ.py                 (CIK-based diff)
                         →  _event_log.parquet         (837 events)
```

**Canonical accessor:**
```python
from data.market.pit.validator import membership_on_date
members = membership_on_date(events, baseline, "2018-04-15")
# → set of ~500 tickers that were actually in the index on that date
```

### 3.3 Mulberry32 PRNG — The JS Parity Contract

The `Mulberry32` class in `data/prng.py` is an exact port of the JavaScript PRNG, verified to 10 decimal places. This is the most critical module: every downstream synthetic computation depends on it producing identical output to the JS `mulberry32` for the same seed.

The PRNG uses unsigned 32-bit arithmetic with explicit masking, `Math.imul` emulation, and a djb2-variant string hash. Box-Muller transform for normal random generation matches JS call order exactly.

---

## 4. Factor System

### 4.1 Registry Pattern

All 11 factors implement a `BaseFactor` ABC:

```python
class BaseFactor(ABC):
    name: str
    lookback_required: int

    @abstractmethod
    def compute(self, prices, volumes, returns, lookback) -> float:
        """Enhanced formula (Python-only research)."""

    @abstractmethod
    def compute_js(self, prices, volumes, returns, lookback) -> float:
        """JS-parity formula (must match frontend exactly)."""

    def compute_universe(self, dataset, lookback, use_js=True) -> Dict[str, float]:
        """Raw scores across all tickers."""

    def score_universe(self, dataset, lookback, use_js=True) -> Dict[str, float]:
        """Cross-sectional z-scores."""
```

Factors are discovered via `FACTOR_REGISTRY` and loaded by name:
```python
from factors.registry import load_factor
factor = load_factor("Momentum (12-1)")
scores = factor.score_universe(dataset, lookback=252)
```

### 4.2 Two Formula Tracks

Each factor carries two implementations:
- **`compute_js()`** — Matches the JS frontend exactly. Used for parity tests and the synthetic demo.
- **`compute()`** — Enhanced formula for Python-only research (e.g., Idiosyncratic Volatility and Residual Reversal residualize against an equal-weight market return).

This dual-track design means the frontend always shows results consistent with the Python backend on synthetic data, while the research pipeline can use academically correct formulas.

---

## 5. Backtest Engines

### 5.1 Why Two Engines

| | Synthetic Demo | Event-Driven Engine |
|---|---|---|
| **Module** | `backtest/synthetic_demo.py` | `backtest/event_driven/` |
| **Data** | Mulberry32 synthetic | Real parquet OHLCV |
| **Fill timing** | Same-bar close | Next-bar open |
| **Cost model** | Flat bps post-hoc deduction | Per-fill slippage + commission |
| **Look-ahead** | Allowed (by design — matches JS) | Raises on violation |
| **Purpose** | JS-parity demo | All real research |
| **Can they merge?** | **No** — incompatible constraints | — |

A third engine (`real_engine.py`) was deleted in Phase 2 after a design review found it had architecturally wrong same-bar fills, daily ±20% clamps, and flat per-rebalance cost deduction. The [design memo](alphaforge-python/backtest/ENGINE_CONSOLIDATION_DESIGN.md) documents the decision and a regression test gates the deletion.

### 5.2 Event-Driven Engine — Loop Semantics

```
for each timestamp t in [start, end]:
    1. Mark portfolio to t's close prices (OLD weights earn this bar's return)
    2. If rebalance bar:
       a. Hand strategy a PIT view ending at t
       b. Size orders against current NAV and t's close prices
       c. Execute at next bar's open price
       d. Apply slippage + commission per fill
```

Key architectural enforcements:
- **`BarHistory`** raises `LookAheadError` if it holds any row past its `as_of` date
- **`ExecutionHandler`** requires fill timestamp strictly later than order timestamp
- **`Portfolio`** fails loudly on missing prices rather than carrying forward stale quotes

---

## 6. MARL Framework

### 6.1 Multi-Layer Pipeline

```
TradingEnv (Gymnasium)
    │
    ▼
AgentPool (N agents, each with ActorCriticNetwork)
    │
    ▼
EvolutionaryEngine (per generation):
    ├── Evaluate all agents (common random numbers for fair comparison)
    ├── PPO fine-tune each agent
    ├── Periodic MAML meta-learning
    ├── NSGA-II select on (Sharpe, drawdown, turnover)
    ├── Speciated reproduction (Jensen-Shannon distance)
    └── Per-parameter adaptive mutation
    │
    ▼
RegimeBandit:
    ├── HMM regime detection (K-Means init + Baum-Welch)
    ├── Thompson sampling per (regime, agent) pair
    └── Capital allocation → EnsemblePolicy
```

### 6.2 Trading Environment

- **Observation space:** 57-dim float32 — portfolio state (NAV, positions, cash, drawdown, days since rebalance), market features (index returns, volumes, prices over multiple windows), and cross-sectional factor z-scores.
- **Action space:** 5 discrete actions (HOLD, LONG_SMALL, LONG_BIG, SHORT_SMALL, SHORT_BIG) or 10-dim continuous weight vector.
- **Reward:** Dense per-step shaping (rolling 21d Sharpe delta + drawdown penalty + participation/inactivity) plus Sharpe-based terminal reward. The dense signal is critical — sparse episode-end-only rewards make evolution too noisy.
- **Data modes:** `synthetic`, `real`, `real_strict`, `hybrid` (randomly mixes synthetic and real episodes for robustness).

### 6.3 Cross-Project Import

The MARL environment dynamically adds `alphaforge-python/` to `sys.path` to import factor scoring and data generation. Both directories must be siblings.

---

## 7. Execution System

### 7.1 Daily Loop

```python
# Simplified ExecutionEngine.run_day():
prices = fetch_latest_closes(history)
broker.update_prices(prices)

if kill_switch.blocks_new_entries():
    # Active unwind: scale positions down per the ladder
    execute_unwind_orders()
    return

target_weights = strategy.generate_weights(history)  # momentum or MARL
risk_result = check_pre_trade(target_weights, nav, limits)

if risk_result.passed:
    orders = compute_order_deltas(target_weights, current_weights, nav, prices)
    for order in orders:
        broker.submit_order(order)

snapshot = record_daily_snapshot()
check_circuit_breakers(snapshot)
kill_switch.end_of_day(snapshot)
```

### 7.2 Broker Abstraction

```python
class Broker(ABC):
    def get_account(self) -> Account: ...
    def submit_order(self, order: Order) -> Order: ...
    def update_prices(self, prices: Dict[str, float]): ...

class PaperBroker(Broker):     # Local simulation with constant slippage
class AlpacaBroker(Broker):    # Live Alpaca paper-trading API
```

Separate Alpaca API credentials for momentum and MARL strategies allow running two strategies simultaneously in the same Alpaca paper account.

### 7.3 Risk Management Stack

| Layer | When | What |
|---|---|---|
| **Pre-trade** | Before orders | Max position (10%), max gross exposure (150%), max daily turnover (30%) |
| **Circuit breakers** | After snapshot | Max daily loss (2%), max drawdown (10%) |
| **Kill switch** | End of day | 6 independent triggers → 3-stage unwind ladder → human ACK to re-arm |

The kill switch evaluates independently of circuit breakers. A slippage drift trigger can halt the strategy on a green P&L day. The unwind ladder (25% → 50% → 100% flat) avoids compounding impact on the day of a problem.

---

## 8. Research Pipeline

### 8.1 Statistical Hygiene Stack

| Tool | Implementation | Purpose |
|---|---|---|
| **Stationary bootstrap** | `stats_hygiene.py` | Block-bootstrap Sharpe CIs (block length 21, 2000 reps) |
| **Deflated Sharpe Ratio** | `factor_study.py` | Accounts for trial count — DSR > 0.95 required |
| **Hansen SPA** | `stats_hygiene.py` | Data-snooping adjustment with non-positive-candidate recentering |
| **White's Reality Check** | `stats_hygiene.py` | More conservative than SPA (naive recentering) — reported alongside |
| **Purged + embargoed CV** | `stats_hygiene.py` | Prevents label leakage across folds when forward returns overlap |
| **Square-root impact** | `cost_model.py` | k·√(participation) — the capacity-grade cost model |
| **Corwin-Schultz spread** | `cost_model.py` | High/Low based half-spread estimator |

### 8.2 Factor Study Pipeline

The 48KB `factor_study.py` runs the full pipeline:

1. Build factor panels (8 vectorized factors on T dates × N tickers)
2. Compute IC at 5 horizons with decay curves
3. Run quintile-spread long-short backtests with realistic tx costs
4. Stationary-bootstrap Sharpe CIs on each factor's net return series
5. Deflated Sharpe across the full K-factor trial set
6. Hansen SPA + White's RC on the K × T net-return matrix
7. Regime splits (tercile by trailing vol)
8. Equal-weight + 100-seed random long-short baselines
9. Sector-neutral variant (within-sector cross-sectional demean)
10. Train/test split at `OOS_START=2024-01-02` with 21-day embargo
11. Purged + embargoed CV IC at the 21-day horizon

---

## 9. Frontend

No build step. All JS loaded via `<script>` tags. Chart.js vendored locally with CDN fallback.

**Module communication:** All modules register on `window` (`AlphaData`, `AlphaApp`, etc.) and communicate through `AlphaApp.getState() → { sector, lookback, activeTab }`.

**Script load order matters:** `data.js` first (PRNG + data), feature modules in any order, `app.js` last (initializes everything).

**Backend toggle:** The UI has a Python API / Local (JS Demo) switch. The JS demo uses the Mulberry32 synthetic path; the API mode hits the Python backend for real-market data.

---

## 10. Reproducibility

| Mechanism | Detail |
|---|---|
| **Makefile** | `make all` rebuilds every headline artifact |
| **SEEDS.md** | Per-component seed manifest; `ALPHAFORGE_GLOBAL_SEED=42` |
| **CI** | GitHub Actions: matrix tests (3 sub-projects) + headline-metrics drift diff |
| **Parquet store** | Deterministic substrate — no network during research |
| **Regression tests** | 750 tests across 48 test files; JS-parity verified to 10 decimal places |
| **Engine deletion gate** | `test_engine_consolidation.py` asserts `real_engine.py` stays deleted |

---

## 11. Technology Stack

| Layer | Technology |
|---|---|
| **Frontend** | Vanilla JS, HTML, CSS — no build system |
| **Charts** | Chart.js 4.4.7 (vendored) |
| **Python** | 3.12, numpy, pandas, scipy, gymnasium, torch |
| **API** | FastAPI + CORS (ports 8000, 8001, 8002) |
| **Storage** | Parquet (market data), SQLite (execution), JSON (research artifacts) |
| **Broker** | Alpaca paper-trading API |
| **CI** | GitHub Actions |
| **Data source** | yfinance (market), Wikipedia API (universe), SEC EDGAR (CIK) |
