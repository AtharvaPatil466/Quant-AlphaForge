"""
Cross-sectional signal scanner — computes composite scores for a universe.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

import numpy as np

from data.real_dataset import load_real_dataset
from data.synthetic import generate_dataset, safe_div, sanitize_number, PriceSeries
from backtest.engine import _compute_factor_scores_js
from factors.registry import load_factor, JS_FACTOR_NAMES
from data.synthetic import mean, stddev


@dataclass
class SignalRow:
    ticker: str
    name: str
    composite: float
    signal: str
    ret5d: float
    volume: float
    price: float
    factor_scores: Dict[str, float]


@dataclass
class TickerScore:
    ticker: str
    name: str
    raw_score: float
    score: float
    signal: str


def scan_universe(
    sector: str = "All",
    lookback: int = 252,
    base_seed: int = 42,
    min_score: float | None = None,
    signal_filter: str | None = None,
    data_source: str = "synthetic",
    end_date: str | None = None,
    market_dir: str | None = None,
) -> List[SignalRow]:
    """Full universe scan — all factors, all tickers, sorted by composite desc.

    Optional filters:
        min_score: only include rows with |composite| >= this value
        signal_filter: only include 'LONG', 'SHORT', or 'NEUTRAL'
    """
    if data_source == "real":
        dataset = load_real_dataset(
            sector=sector,
            lookback=lookback,
            end_date=end_date,
            market_dir=market_dir,
        )
    else:
        dataset = generate_dataset(sector, lookback, base_seed)
    scores = _compute_factor_scores_js(dataset, lookback)

    results = []
    for ticker, d in dataset.items():
        s = scores.get(ticker, {})
        n = len(d.prices)
        ret5d = safe_div(
            d.prices[n - 1] - d.prices[max(0, n - 6)],
            d.prices[max(0, n - 6)],
            0.0,
        )
        row = SignalRow(
            ticker=ticker,
            name=d.name,
            composite=s.get("_composite", 0.0),
            signal=s.get("_signal", "NEUTRAL"),
            ret5d=ret5d,
            volume=float(d.volumes[n - 1]),
            price=float(d.prices[n - 1]),
            factor_scores={f: s.get(f, 0.0) for f in JS_FACTOR_NAMES},
        )

        if min_score is not None and abs(row.composite) < min_score:
            continue
        if signal_filter is not None and row.signal != signal_filter:
            continue

        results.append(row)

    results.sort(key=lambda r: r.composite, reverse=True)
    return results


def compute_factor_scores(
    sector: str,
    lookback: int,
    factor_name: str,
    base_seed: int = 42,
    data_source: str = "synthetic",
    end_date: str | None = None,
    market_dir: str | None = None,
) -> List[TickerScore]:
    """Compute z-scored factor scores for a single factor across a sector."""
    if data_source == "real":
        dataset = load_real_dataset(
            sector=sector,
            lookback=lookback,
            end_date=end_date,
            market_dir=market_dir,
        )
    else:
        dataset = generate_dataset(sector, lookback, base_seed)
    tickers = list(dataset.keys())
    if not tickers:
        return []

    factor = load_factor(factor_name)

    raw_vals = []
    for ticker in tickers:
        d = dataset[ticker]
        raw = factor.compute_js(d.prices, d.volumes, d.returns, lookback)
        raw_vals.append(raw)

    raw_arr = np.array(raw_vals)
    mu = mean(raw_arr)
    sigma = max(1e-8, stddev(raw_arr))

    results = []
    for i, ticker in enumerate(tickers):
        d = dataset[ticker]
        z = safe_div(raw_vals[i] - mu, sigma, 0.0)
        z = sanitize_number(z, 0.0)
        score = z * 50
        if z > 0.8:
            signal = "LONG"
        elif z < -0.8:
            signal = "SHORT"
        else:
            signal = "NEUTRAL"
        results.append(TickerScore(
            ticker=ticker,
            name=d.name,
            raw_score=raw_vals[i],
            score=score,
            signal=signal,
        ))
    return results
