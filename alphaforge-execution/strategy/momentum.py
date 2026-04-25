"""Momentum ranking strategy — extracted from MARL dynamic ranking.

Ranks tickers by a composite of short-term momentum, medium-term momentum,
and mean reversion. Returns target portfolio weights for the top N tickers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd


@dataclass
class Signal:
    """Output of the momentum ranking for a single ticker."""
    ticker: str
    mom_5d: float
    mom_21d: float
    mean_reversion: float
    composite: float
    rank: int


@dataclass
class TargetPortfolio:
    """Target portfolio weights from the strategy."""
    weights: Dict[str, float]   # ticker -> target weight
    signals: List[Signal]       # full ranking for audit
    date: str                   # date of the signal


def compute_signals(
    history: Dict[str, pd.DataFrame],
    day_index: int = -1,
    mom_5d_weight: float = 0.4,
    mom_21d_weight: float = 0.4,
    mr_weight: float = 0.2,
) -> List[Signal]:
    """Compute momentum signals for all tickers at a given day.

    Args:
        history: dict of ticker -> DataFrame with 'Close' column
        day_index: which day to compute signals for (-1 = latest)
        mom_5d_weight: weight for 5-day momentum in composite
        mom_21d_weight: weight for 21-day momentum in composite
        mr_weight: weight for mean reversion signal in composite
    """
    signals: List[Signal] = []

    for ticker, df in history.items():
        closes = df["Close"].values
        n = len(closes)
        if n < 2:
            continue

        d = n - 1 if day_index == -1 else min(day_index, n - 1)

        # 5-day momentum
        d5 = max(0, d - 5)
        mom5 = (closes[d] - closes[d5]) / max(closes[d5], 1e-10) if d > 0 else 0.0

        # 21-day momentum
        d21 = max(0, d - 21)
        mom21 = (closes[d] - closes[d21]) / max(closes[d21], 1e-10) if d > 0 else 0.0

        # Mean reversion: price vs 21-day MA
        if d >= 21:
            ma21 = float(np.mean(closes[d - 20:d + 1]))
            mr = -(closes[d] / max(ma21, 1e-10) - 1.0)
        else:
            mr = 0.0

        composite = mom_21d_weight * mom21 + mom_5d_weight * mom5 + mr_weight * mr

        signals.append(Signal(
            ticker=ticker,
            mom_5d=float(mom5),
            mom_21d=float(mom21),
            mean_reversion=float(mr),
            composite=float(composite),
            rank=0,
        ))

    # Sort by composite descending and assign ranks
    signals.sort(key=lambda s: s.composite, reverse=True)
    for i, sig in enumerate(signals):
        sig.rank = i + 1

    return signals


def generate_target_weights(
    history: Dict[str, pd.DataFrame],
    top_n: int = 5,
    position_weight: float = 0.05,
    **signal_kwargs: Any,
) -> TargetPortfolio:
    """Generate target portfolio weights from momentum ranking.

    Goes long the top N tickers with equal weight.
    """
    signals = compute_signals(history, **signal_kwargs)
    top = signals[:top_n]

    weights = {sig.ticker: position_weight for sig in top}

    # Determine date from the latest data
    dates = []
    for df in history.values():
        if not df.empty:
            idx = df.index[-1]
            dates.append(str(idx.date()) if hasattr(idx, "date") else str(idx))
            break

    return TargetPortfolio(
        weights=weights,
        signals=signals,
        date=dates[0] if dates else "",
    )
