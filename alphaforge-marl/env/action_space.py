"""Action space definitions for the MARL trading environment.

Supports both discrete (5 actions) and continuous (per-ticker weights) modes.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Dict, List

import numpy as np


class Action(IntEnum):
    HOLD = 0
    LONG_STRONG = 1
    LONG_MILD = 2
    SHORT_STRONG = 3
    SHORT_MILD = 4


# Position size multipliers per action
ACTION_POSITION = {
    Action.HOLD: 0.0,
    Action.LONG_STRONG: 1.0,
    Action.LONG_MILD: 0.5,
    Action.SHORT_STRONG: -1.0,
    Action.SHORT_MILD: -0.5,
}

N_ACTIONS = len(Action)


def continuous_weights_to_positions(
    weights: np.ndarray,
    top_tickers: List[str],
    bottom_tickers: List[str],
    max_position: float = 0.05,
    max_gross_exposure: float = 1.50,
) -> Dict[str, float]:
    """Convert continuous weight vector to position dict.

    Args:
        weights: Array of shape (10,) — first 5 for top tickers, last 5 for bottom.
                 Values should be in [-max_position, +max_position].
        top_tickers: Top 5 ranked tickers (long candidates).
        bottom_tickers: Bottom 5 ranked tickers (short candidates).
        max_position: Maximum absolute weight per ticker.
        max_gross_exposure: Maximum total gross exposure.

    Returns:
        Dict mapping ticker -> weight.
    """
    positions: Dict[str, float] = {}

    # Top 5 tickers get first 5 weights
    for i, t in enumerate(top_tickers[:5]):
        if i < len(weights):
            w = float(np.clip(weights[i], -max_position, max_position))
            if abs(w) > 1e-6:
                positions[t] = w

    # Bottom 5 tickers get last 5 weights
    for i, t in enumerate(bottom_tickers[:5]):
        idx = 5 + i
        if idx < len(weights):
            w = float(np.clip(weights[idx], -max_position, max_position))
            if abs(w) > 1e-6:
                positions[t] = w

    # Enforce gross exposure limit
    gross = sum(abs(v) for v in positions.values())
    if gross > max_gross_exposure:
        scale = max_gross_exposure / gross
        positions = {t: w * scale for t, w in positions.items()}

    return positions
