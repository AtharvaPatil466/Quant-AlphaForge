"""Sharpe-based reward function computed at episode end."""

from __future__ import annotations

import math
from typing import List

import numpy as np


def compute_reward(
    daily_returns: List[float],
    nav_history: List[float],
    daily_turnover: List[float],
    benchmark_returns: List[float] | None = None,
    *,
    drawdown_penalty_coeff: float = 2.0,
    drawdown_threshold: float = 0.10,
    consistency_bonus: float = 0.20,
    consistency_threshold: float = 0.55,
    turnover_penalty_coeff: float = 0.10,
    benchmark_relative_mix: float = 0.5,
) -> float:
    """Episode-end reward with optional benchmark-relative pressure.

    Base reward is the portfolio Sharpe. When benchmark returns are provided,
    a fraction of the reward is replaced by active-return Sharpe so the agent
    is encouraged to beat the equal-weight market proxy rather than simply
    drift upward with it.
    """
    rets = np.array(daily_returns, dtype=np.float64)

    if len(rets) < 2:
        return 0.0

    # Base reward: annualized portfolio Sharpe
    mu = float(np.mean(rets))
    sigma = float(np.std(rets, ddof=1))
    portfolio_sharpe = (mu / sigma) * math.sqrt(252) if sigma > 1e-12 else 0.0

    mix = float(np.clip(benchmark_relative_mix, 0.0, 1.0))
    active_sharpe = 0.0
    if benchmark_returns is not None:
        bench = np.asarray(benchmark_returns, dtype=np.float64)
        n = min(len(rets), len(bench))
        if n >= 2:
            active = rets[:n] - bench[:n]
            active_mu = float(np.mean(active))
            active_sigma = float(np.std(active, ddof=1))
            if active_sigma > 1e-12:
                active_sharpe = (active_mu / active_sigma) * math.sqrt(252)

    base_reward = (1.0 - mix) * portfolio_sharpe + mix * active_sharpe

    # Drawdown penalty
    nav = np.array(nav_history, dtype=np.float64)
    peak = np.maximum.accumulate(nav)
    dd = (peak - nav) / np.where(peak > 0, peak, 1.0)
    max_dd = float(np.max(dd)) if len(dd) > 0 else 0.0
    dd_penalty = max(0.0, max_dd - drawdown_threshold) * drawdown_penalty_coeff

    # Consistency bonus: monthly win rate
    monthly_rets = []
    for i in range(0, len(rets), 21):
        chunk = rets[i : i + 21]
        if len(chunk) > 0:
            monthly_rets.append(float(np.sum(chunk)))
    if monthly_rets:
        win_rate = sum(1 for r in monthly_rets if r > 0) / len(monthly_rets)
        c_bonus = consistency_bonus if win_rate > consistency_threshold else 0.0
    else:
        c_bonus = 0.0

    # Turnover penalty
    turnover = np.array(daily_turnover, dtype=np.float64) if daily_turnover else np.zeros(1)
    t_penalty = float(np.mean(np.abs(turnover))) * turnover_penalty_coeff

    reward = base_reward - dd_penalty + c_bonus - t_penalty

    return reward if math.isfinite(reward) else 0.0
