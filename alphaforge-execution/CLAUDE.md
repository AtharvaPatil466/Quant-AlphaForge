# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AlphaForge Execution is a Python quantitative trading backtest and execution system. It fetches real OHLCV data via yfinance, runs a momentum-based ranking strategy on a paper broker, tracks portfolio performance, and persists results to SQLite. A FastAPI server exposes monitoring endpoints.

## Setup & Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run backtest (default: 2024-03-21 to 2025-03-21)
python3 run_backtest.py

# Custom date range and database
python3 run_backtest.py --start 2024-01-01 --end 2024-12-31 --db backtest.db

# Start monitoring API (requires populated backtest.db)
uvicorn api.server:app --host 0.0.0.0 --port 8002 --reload

# Run tests (framework ready, tests not yet written)
python3 -m pytest tests/ -v
```

## Architecture

### Daily Trading Loop (`execution/daily_loop.py`)

`ExecutionEngine.run_day()` orchestrates each trading day in sequence:

1. **Update prices** — latest close from history → `broker.update_prices()`
2. **Generate targets** — `strategy/momentum.py` ranks tickers by composite score → target weights
3. **Risk checks** — `risk/limits.py` validates position size, exposure, turnover
4. **Compute orders** — weight deltas → buy/sell orders (skips < $50 or < 0.5% delta)
5. **Submit orders** — `paper_broker.py` fills at price ± slippage
6. **Record snapshot** — `portfolio/tracker.py` logs NAV, returns, drawdown
7. **Circuit breakers** — halts trading if daily loss > 2% or drawdown > 10%

The `backtest()` function fetches full history once via yfinance, then replays day-by-day through `run_day()`.

### Strategy (`strategy/momentum.py`)

Three signals combined into a composite score:
- **5-day momentum** (40%): short-term price change
- **21-day momentum** (40%): medium-term trend
- **Mean reversion** (20%): negative deviation from 21-day MA

Top N tickers (default 5) get equal weight (default 5% each = 25% gross long). This formula originates from the MARL environment's `_rank_tickers()` in the parent project.

### Broker Abstraction

`execution/broker.py` defines an abstract `Broker` with `submit_order()`, `get_account()`, `update_prices()`. `PaperBroker` implements local simulation with slippage. The abstraction exists for future live broker integration (Alpaca credentials in `.env.template`).

### Persistence

SQLite database with three tables: `orders` (trade audit log), `snapshots` (daily NAV/exposure with JSON weights), `signals` (per-ticker factor scores). Schema auto-created by `storage/database.py`.

### Configuration

All parameters in `configs/execution_config.yaml`: universe tickers, strategy weights, position sizing, slippage, risk limits. Loaded by `config.py` which falls back to the default path if no `--config` arg is given.

## Key Dataclasses

- `Order` (`execution/broker.py`) — ticker, side, quantity, fill_price, status
- `Position` (`execution/broker.py`) — ticker, quantity, avg_cost, current_price, market_value
- `DailySnapshot` (`portfolio/tracker.py`) — date, nav, daily_return, drawdown, sharpe_to_date, exposures
- `Signal` / `TargetPortfolio` (`strategy/momentum.py`) — per-ticker scores and resulting weight allocation

## Testing

```bash
python3 -m pytest tests/ -v --tb=short   # run full test suite (106 tests)
```

Test files cover: broker dataclasses & PaperBroker (`test_broker.py`), momentum strategy (`test_strategy.py`), risk checks & circuit breakers (`test_risk.py`), portfolio tracker (`test_tracker.py`), data validator (`test_validator.py`), market calendar (`test_calendar.py`), SQLite storage (`test_storage.py`), execution engine & daily loop (`test_daily_loop.py`).

## Known Issues

- yfinance MultiIndex columns: `fetch_history()` flattens with `get_level_values(0)` but yfinance column format can vary across versions
- Floating-point quantity matching: `paper_broker.py` clamps sell order quantity to position size within 0.01 shares to avoid rounding rejections

## Relationship to Parent Project

This repo sits under `Quant Alpha/` alongside `alphaforge-python/` (JS-parity simulation engine) and `alphaforge-marl/` (neuroevolution + PPO RL agents). The momentum ranking formula was extracted from the MARL environment's hardcoded `_rank_tickers()` after discovering the neural network wasn't learning state-conditional behavior beyond this formula.
