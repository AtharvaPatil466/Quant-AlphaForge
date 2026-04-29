"""AlphaForge backtest module.

Two distinct engines live here, with different jobs:

    backtest.synthetic_demo  — JS-parity demo on Mulberry32 PRNG data.
                               DO NOT use for research. See module
                               docstring and ENGINE_CONSOLIDATION_DESIGN.md.
    backtest.event_driven    — the canonical real-data backtest engine
                               (no look-ahead, next-bar fills, per-fill
                               costs). Use this for everything new.

The legacy `backtest.real_engine` (`run_real_backtest`) was retired per
ENGINE_CONSOLIDATION_DESIGN.md — its same-bar fills, daily ±20%
clamp, and per-rebalance flat costs are bugs from synthetic-engine
inheritance, not deliberate research choices.

Top-level re-exports below preserve the historical
`from backtest import BacktestConfig, ...` import surface so callers
don't break, but each caller should be migrating to the explicit
`backtest.synthetic_demo` or `backtest.event_driven` path.
"""

from .synthetic_demo import run_synthetic_backtest, BacktestConfig, BacktestResult
from .metrics import (
    sharpe_ratio,
    max_drawdown,
    calmar_ratio,
    win_rate,
    annualized_return,
    annualized_vol,
    information_ratio,
    sortino_ratio,
    monthly_returns,
)
