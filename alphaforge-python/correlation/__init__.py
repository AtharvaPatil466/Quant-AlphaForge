"""AlphaForge correlation lab — pairwise correlation, IC, turnover."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from .matrix import compute_correlation_matrix
from .ic import compute_ic, compute_ic_js
from .turnover import compute_turnover

from data.real_dataset import load_real_dataset
from data.synthetic import generate_dataset
from factors.registry import JS_FACTOR_NAMES


@dataclass
class CorrelationResult:
    matrix: List[List[float]]
    ic: List[float]
    turnover: List[float]
    factors: List[str]


def compute_correlation_result(
    sector: str = "Technology",
    lookback: int = 252,
    base_seed: int = 42,
    data_source: str = "synthetic",
    end_date: str | None = None,
    market_dir: str | None = None,
) -> CorrelationResult:
    """Full correlation analysis for the API."""
    if data_source == "real":
        dataset = load_real_dataset(
            sector=sector,
            lookback=lookback,
            end_date=end_date,
            market_dir=market_dir,
        )
    else:
        dataset = generate_dataset(sector, lookback, base_seed)
    return CorrelationResult(
        matrix=compute_correlation_matrix(dataset, lookback),
        ic=compute_ic_js(dataset, lookback),
        turnover=compute_turnover(dataset, lookback, base_seed),
        factors=list(JS_FACTOR_NAMES),
    )
