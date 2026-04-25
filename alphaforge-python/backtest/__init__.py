"""AlphaForge backtest engine — simulation, portfolio, metrics, attribution."""

from .engine import run_backtest, BacktestConfig, BacktestResult
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
