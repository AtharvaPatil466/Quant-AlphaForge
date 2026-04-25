# AlphaForge Python Alpha Engine

Python backend for the AlphaForge quantitative research workstation. Reproduces the JS frontend's synthetic data generation, alpha factor scoring, and backtesting — with verified numerical parity — and exposes everything as a REST API.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt          # runtime only
pip install -r requirements-dev.txt      # includes pytest, httpx, jupyter
```

## Run the API Server

```bash
uvicorn api.server:app --reload
```

Server starts at `http://localhost:8000`. API docs at `http://localhost:8000/docs`.

All endpoints are prefixed with `/api/v1`:

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Status check |
| POST | `/backtest` | Run long-short backtest simulation |
| GET | `/scanner?sector=All&lookback=252` | Full universe signal scan |
| GET | `/factors` | List available factor names |
| GET | `/factors/{name}?sector=Tech&lookback=252` | Factor scores for a sector |
| GET | `/correlation?sector=Tech&lookback=252` | Correlation matrix, IC, turnover |
| GET | `/universe?sector=Tech` | Tickers in a sector |
| GET | `/sectors` | Available sector names |

### POST /backtest request body

```json
{
  "sector": "Technology",
  "lookback": 252,
  "factor_name": "Momentum (12-1)",
  "holding_period": 10,
  "position_size": 10,
  "stop_loss": 5.0,
  "tx_cost_bps": 5
}
```

## Run Tests

```bash
pytest tests/ -v --tb=short
```

107 tests covering PRNG parity, data generation, factor scoring, backtest mechanics, scanner output, correlation invariants, Gym environment compliance, and API endpoint schemas.

Run a single test file:

```bash
pytest tests/test_prng.py -v
```

## Configuration

Default parameters are in `configs/default.yaml`. The library modules use hardcoded defaults matching the JS frontend; the config file serves as a reference for the standard values.

| Parameter | Default | Range |
|-----------|---------|-------|
| `base_seed` | 42 | any int |
| `lookback` | 252 | 21–504 |
| `holding_period` | 10 | 1–60 |
| `position_size` | 10% | 1–20 |
| `stop_loss` | 5% | 1–15 |
| `tx_cost_bps` | 5 | 0–100 |

## Gym Environment

The `TradingEnv` in `alphaforge/environment.py` implements the Gymnasium interface for MARL agent training.

```python
from alphaforge.environment import TradingEnv, EnvConfig

env = TradingEnv(EnvConfig(
    sector="Technology",
    lookback=252,
    base_seed=42,
    initial_nav=100.0,
    tx_cost_bps=5,
    max_position=1.0,
))

obs, info = env.reset(seed=42)
obs, reward, terminated, truncated, info = env.step(action)
```

### Observation space

47-dimensional `float32` vector:

| Dims | Feature |
|------|---------|
| 0–4 | Price returns (1d, 5d, 21d, 63d, 252d) |
| 5–7 | Volume features (ratio, trend, log volume) |
| 8–10 | Volatility features (realized, long-term, vol-of-vol proxy) |
| 11–15 | Factor z-scores (5 JS factors) |
| 16–17 | Composite score (normalized), signal direction |
| 18–19 | Distance from MA21, MA50 |
| 20–21 | Current position, PnL % |
| 22–46 | Reserved (zeroed) — filled in MARL Phase 0 |

### Action space

`Discrete(5)`: 0=HOLD, 1=BUY, 2=SELL, 3=SCALE_UP, 4=SCALE_DOWN

### Reward

Log return: `log(NAV_t / NAV_{t-1})`

## JS/Python Parity

The PRNG (`mulberry32`), price generation, factor scoring, and backtest engine produce numerically identical results to the JS frontend. Parity is verified to 10+ decimal places for all Technology-sector tickers at lookback=252, seed=42.

## Project Structure

```
alphaforge-python/
├── alphaforge/          # Core library
│   ├── prng.py          # Mulberry32 PRNG (must match JS exactly)
│   ├── data.py          # Synthetic data, universe, stat helpers
│   ├── factors.py       # 6 alpha factors
│   ├── scoring.py       # Z-score normalization, composite scoring
│   ├── backtest.py      # Long-short simulation engine
│   ├── metrics.py       # Sharpe, drawdown, Calmar, etc.
│   ├── scanner.py       # Universe scan
│   ├── correlation.py   # Factor correlation, IC, turnover
│   └── environment.py   # Gymnasium TradingEnv
├── api/                 # FastAPI server
│   ├── server.py        # App entry point
│   ├── schemas.py       # Pydantic models
│   └── routes/          # Endpoint handlers
├── tests/               # Pytest suite (107 tests)
├── configs/             # Default parameter reference
├── notebooks/           # Parity check notebook
├── requirements.txt
└── requirements-dev.txt
```
