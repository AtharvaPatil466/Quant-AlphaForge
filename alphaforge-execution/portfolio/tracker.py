"""Portfolio tracker — NAV, daily returns, exposure."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class DailySnapshot:
    date: str
    nav: float
    daily_return: float
    cumulative_return: float
    drawdown: float
    long_exposure: float
    short_exposure: float
    cash: float
    n_positions: int
    sharpe_to_date: float
    weights: Dict[str, float] = field(default_factory=dict)


class PortfolioTracker:
    """Tracks portfolio state across days."""

    def __init__(self, starting_nav: float = 100_000.0):
        self.starting_nav = starting_nav
        self.nav_history: List[float] = [starting_nav]
        self.daily_returns: List[float] = []
        self.snapshots: List[DailySnapshot] = []
        self.peak_nav = starting_nav

    def record_day(
        self,
        date: str,
        nav: float,
        cash: float,
        positions: Dict[str, float],  # ticker -> market_value
    ) -> DailySnapshot:
        prev_nav = self.nav_history[-1]
        daily_ret = (nav - prev_nav) / prev_nav if prev_nav > 0 else 0.0

        self.nav_history.append(nav)
        self.daily_returns.append(daily_ret)
        self.peak_nav = max(self.peak_nav, nav)

        cum_ret = (nav - self.starting_nav) / self.starting_nav
        dd = (self.peak_nav - nav) / self.peak_nav if self.peak_nav > 0 else 0.0

        long_exp = sum(v for v in positions.values() if v > 0)
        short_exp = sum(abs(v) for v in positions.values() if v < 0)

        weights = {t: v / nav for t, v in positions.items()} if nav > 0 else {}

        snap = DailySnapshot(
            date=date,
            nav=nav,
            daily_return=daily_ret,
            cumulative_return=cum_ret,
            drawdown=dd,
            long_exposure=long_exp / nav if nav > 0 else 0.0,
            short_exposure=short_exp / nav if nav > 0 else 0.0,
            cash=cash,
            n_positions=len(positions),
            sharpe_to_date=self.sharpe(),
            weights=weights,
        )
        self.snapshots.append(snap)
        return snap

    def sharpe(self, annualize: bool = True) -> float:
        if len(self.daily_returns) < 5:
            return 0.0
        import numpy as np
        rets = np.array(self.daily_returns)
        mu = float(np.mean(rets))
        sigma = float(np.std(rets, ddof=1))
        if sigma < 1e-12:
            return 0.0
        s = mu / sigma
        if annualize:
            s *= math.sqrt(252)
        return s if math.isfinite(s) else 0.0

    def max_drawdown(self) -> float:
        if not self.snapshots:
            return 0.0
        return max(s.drawdown for s in self.snapshots)

    def win_rate(self) -> float:
        if not self.daily_returns:
            return 0.0
        wins = sum(1 for r in self.daily_returns if r > 0)
        return wins / len(self.daily_returns)

    def total_return(self) -> float:
        if len(self.nav_history) < 2:
            return 0.0
        return (self.nav_history[-1] - self.starting_nav) / self.starting_nav
