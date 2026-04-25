"""Factor portfolio turnover — simulated using seeded PRNG (matches JS)."""

from __future__ import annotations

from typing import Dict, List

from data.prng import Mulberry32, hash_string
from data.synthetic import PriceSeries, sanitize_number
from factors.registry import JS_FACTOR_NAMES


def compute_turnover(
    dataset: Dict[str, PriceSeries],
    lookback_days: int,
    seed: int = 42,
) -> List[float]:
    """Port of JS computeFactorTurnover — simulated turnover per factor.

    JS uses seeded random to produce a stable turnover metric (15%-70%).
    """
    turnovers = []
    for factor in JS_FACTOR_NAMES:
        rng = Mulberry32(hash_string(factor) + seed)
        val = sanitize_number(0.15 + rng() * 0.55, 0.3)
        turnovers.append(val)
    return turnovers
