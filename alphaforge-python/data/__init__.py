"""AlphaForge data layer — PRNG, synthetic market data, universe, features."""

from .prng import Mulberry32, hash_string, normal_random
from .universe import UNIVERSE, SECTORS, TickerInfo, get_tickers
from .synthetic import (
    generate_prices,
    generate_dataset,
    compute_returns,
    generate_benchmark_index,
    PriceSeries,
    safe_div,
    sanitize_number,
    clamp,
    validate_series,
    mean,
    stddev,
    correlation,
)
