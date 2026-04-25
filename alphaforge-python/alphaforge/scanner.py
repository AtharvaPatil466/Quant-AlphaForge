"""
Universe scanner — wraps scoring.scan_universe for the API layer.
"""

from __future__ import annotations

from .scoring import scan_universe, ScanResult
from typing import List


def run_scan(
    sector: str = "All",
    lookback: int = 252,
    base_seed: int = 42,
) -> List[ScanResult]:
    """Run a full universe scan and return sorted results (by composite desc)."""
    results = scan_universe(sector, lookback, base_seed)
    results.sort(key=lambda r: r.composite, reverse=True)
    return results
