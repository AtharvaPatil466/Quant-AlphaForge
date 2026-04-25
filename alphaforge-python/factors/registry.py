"""
Factor registry — loads all factors by name.
"""

from __future__ import annotations

from typing import Dict

from .base_factor import BaseFactor
from .momentum import MomentumFactor
from .mean_reversion import MeanReversionFactor
from .volume_surge import VolumeSurgeFactor
from .rsi_divergence import RSIDivergenceFactor
from .earnings_drift import EarningsDriftFactor
from .low_volatility import LowVolatilityFactor
from .amihud_illiquidity import AmihudIlliquidityFactor
from .idiosyncratic_volatility import IdiosyncraticVolatilityFactor
from .residual_reversal import ResidualReversalFactor
from .risk_managed_momentum import RiskManagedMomentumFactor
from .long_horizon_reversal import LongHorizonReversalFactor


FACTOR_REGISTRY: Dict[str, BaseFactor] = {
    "Momentum (12-1)": MomentumFactor(),
    "Mean Reversion (5d)": MeanReversionFactor(),
    "Volume Surge": VolumeSurgeFactor(),
    "RSI Divergence": RSIDivergenceFactor(),
    "Earnings Drift": EarningsDriftFactor(),
    "Low Volatility": LowVolatilityFactor(),
    "Amihud Illiquidity": AmihudIlliquidityFactor(),
    "Idiosyncratic Volatility": IdiosyncraticVolatilityFactor(),
    "Residual Reversal (5d)": ResidualReversalFactor(),
    "Risk-Managed Momentum": RiskManagedMomentumFactor(),
    "Long-Horizon Reversal": LongHorizonReversalFactor(),
}

# The first 5 match JS FACTOR_NAMES; the 6th is Python-only.
JS_FACTOR_NAMES = [
    "Momentum (12-1)",
    "Mean Reversion (5d)",
    "Volume Surge",
    "RSI Divergence",
    "Earnings Drift",
]

FACTOR_NAMES = list(FACTOR_REGISTRY.keys())


def load_factor(name: str) -> BaseFactor:
    """Load a factor by name. Raises ValueError if not found."""
    if name not in FACTOR_REGISTRY:
        raise ValueError(
            f"Unknown factor '{name}'. Available: {list(FACTOR_REGISTRY.keys())}"
        )
    return FACTOR_REGISTRY[name]
