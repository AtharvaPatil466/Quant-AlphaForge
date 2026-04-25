"""
Ticker universe definitions — must match JS UNIVERSE object exactly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True, slots=True)
class TickerInfo:
    ticker: str
    name: str


UNIVERSE: Dict[str, List[TickerInfo]] = {
    "Technology": [
        TickerInfo("AAPL", "Apple Inc."),
        TickerInfo("MSFT", "Microsoft Corp."),
        TickerInfo("NVDA", "NVIDIA Corp."),
        TickerInfo("GOOGL", "Alphabet Inc."),
        TickerInfo("META", "Meta Platforms"),
        TickerInfo("AVGO", "Broadcom Inc."),
    ],
    "Finance": [
        TickerInfo("JPM", "JPMorgan Chase"),
        TickerInfo("BAC", "Bank of America"),
        TickerInfo("GS", "Goldman Sachs"),
        TickerInfo("MS", "Morgan Stanley"),
        TickerInfo("C", "Citigroup Inc."),
        TickerInfo("WFC", "Wells Fargo"),
    ],
    "Healthcare": [
        TickerInfo("JNJ", "Johnson & Johnson"),
        TickerInfo("UNH", "UnitedHealth"),
        TickerInfo("PFE", "Pfizer Inc."),
        TickerInfo("ABBV", "AbbVie Inc."),
        TickerInfo("MRK", "Merck & Co."),
        TickerInfo("LLY", "Eli Lilly"),
    ],
    "Energy": [
        TickerInfo("XOM", "Exxon Mobil"),
        TickerInfo("CVX", "Chevron Corp."),
        TickerInfo("COP", "ConocoPhillips"),
        TickerInfo("SLB", "Schlumberger"),
        TickerInfo("EOG", "EOG Resources"),
        TickerInfo("MPC", "Marathon Petroleum"),
    ],
    "Consumer": [
        TickerInfo("AMZN", "Amazon.com"),
        TickerInfo("TSLA", "Tesla Inc."),
        TickerInfo("WMT", "Walmart Inc."),
        TickerInfo("HD", "Home Depot"),
        TickerInfo("NKE", "Nike Inc."),
        TickerInfo("SBUX", "Starbucks Corp."),
    ],
}

SECTORS = list(UNIVERSE.keys())


def get_tickers(sector: str) -> List[TickerInfo]:
    """Return tickers for a sector. 'All' returns all sectors flattened."""
    if sector == "All":
        return [t for tickers in UNIVERSE.values() for t in tickers]
    return list(UNIVERSE.get(sector, []))
