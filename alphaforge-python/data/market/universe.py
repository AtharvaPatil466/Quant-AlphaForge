"""Real-data universe manifest used by the parquet market-data store."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, List

from .paths import universe_manifest_path


@dataclass(frozen=True)
class TickerSpec:
    ticker: str
    sector: str
    usable_start: str
    usable_end: str | None
    requires_clean_years: int
    notes: str


REAL_TICKER_SPECS: List[TickerSpec] = [
    TickerSpec("AAPL", "Technology", "2010-01-04", None, 5, "Core mega-cap technology name with full modern history."),
    TickerSpec("MSFT", "Technology", "2010-01-04", None, 5, "Core mega-cap technology name with full modern history."),
    TickerSpec("NVDA", "Technology", "2010-01-04", None, 5, "Core semiconductor name with full modern history."),
    TickerSpec("GOOGL", "Technology", "2010-01-04", None, 5, "Core mega-cap technology name with full modern history."),
    TickerSpec("META", "Technology", "2012-05-18", None, 5, "Exclude pre-IPO history; training eligibility starts only after 5 clean post-IPO years."),
    TickerSpec("AVGO", "Technology", "2010-01-04", None, 5, "Use listed Broadcom history only; no predecessor backfill."),
    TickerSpec("INTC", "Technology", "2010-01-04", None, 5, "Added as a mature underperforming semiconductor counterweight."),
    TickerSpec("IBM", "Technology", "2010-01-04", None, 5, "Added as a mature low-growth technology name."),
    TickerSpec("CSCO", "Technology", "2010-01-04", None, 5, "Added as a mature networking incumbent."),
    TickerSpec("ORCL", "Technology", "2010-01-04", None, 5, "Added to widen enterprise software outcomes."),
    TickerSpec("JNJ", "Healthcare", "2010-01-04", None, 5, "Core defensive healthcare benchmark."),
    TickerSpec("UNH", "Healthcare", "2010-01-04", None, 5, "Core managed-care benchmark."),
    TickerSpec("PFE", "Healthcare", "2010-01-04", None, 5, "Large-cap pharma with mixed regime outcomes."),
    TickerSpec("ABBV", "Healthcare", "2013-01-02", None, 5, "Exclude pre-spin data before AbbVie began standalone trading."),
    TickerSpec("MRK", "Healthcare", "2010-01-04", None, 5, "Core pharma benchmark."),
    TickerSpec("LLY", "Healthcare", "2010-01-04", None, 5, "Core pharma benchmark."),
    TickerSpec("BMY", "Healthcare", "2010-01-04", None, 5, "Added as a slower-growth pharma control."),
    TickerSpec("CVS", "Healthcare", "2010-01-04", None, 5, "Added as a healthcare services name with mixed performance."),
    TickerSpec("GILD", "Healthcare", "2010-01-04", None, 5, "Added as a boom-bust biotech/pharma outcome."),
    TickerSpec("AMGN", "Healthcare", "2010-01-04", None, 5, "Added as a mature biotech benchmark."),
    TickerSpec("JPM", "Finance", "2010-01-04", None, 5, "Core money-center bank benchmark."),
    TickerSpec("BAC", "Finance", "2010-01-04", None, 5, "Post-crisis recovery bank with full training history."),
    TickerSpec("GS", "Finance", "2010-01-04", None, 5, "Investment-bank benchmark."),
    TickerSpec("MS", "Finance", "2010-01-04", None, 5, "Investment-bank benchmark."),
    TickerSpec("BLK", "Finance", "2010-01-04", None, 5, "Asset-management benchmark."),
    TickerSpec("C", "Finance", "2010-01-04", None, 5, "Keep post-crisis history but quarantine split/anomaly years when validator flags them."),
    TickerSpec("WFC", "Finance", "2010-01-04", None, 5, "Added as a bank with weaker long-run outcomes."),
    TickerSpec("AIG", "Finance", "2010-01-04", None, 5, "Keep post-crisis restructured history only."),
    TickerSpec("USB", "Finance", "2010-01-04", None, 5, "Added as a lower-beta regional bank."),
    TickerSpec("PNC", "Finance", "2010-01-04", None, 5, "Added as a diversified regional bank."),
    TickerSpec("AMZN", "Consumer", "2010-01-04", None, 5, "Core consumer/discretionary benchmark."),
    TickerSpec("TSLA", "Consumer", "2010-06-29", None, 5, "Exclude pre-IPO history; training eligibility begins after 5 clean post-IPO years."),
    TickerSpec("WMT", "Consumer", "2010-01-04", None, 5, "Defensive retail benchmark."),
    TickerSpec("HD", "Consumer", "2010-01-04", None, 5, "Home-improvement retail benchmark."),
    TickerSpec("NKE", "Consumer", "2010-01-04", None, 5, "Consumer brand with cyclical drawdowns."),
    TickerSpec("COST", "Consumer", "2010-01-04", None, 5, "Defensive retail benchmark."),
    TickerSpec("DIS", "Consumer", "2010-01-04", None, 5, "Added as a large-cap consumer name with multiple regime shifts."),
    TickerSpec("TGT", "Consumer", "2010-01-04", None, 5, "Added as a retail name with weaker stretches than COST/WMT."),
    TickerSpec("SBUX", "Consumer", "2010-01-04", None, 5, "Added as a global consumer discretionary name."),
    TickerSpec("KHC", "Consumer", "2015-07-06", None, 5, "Exclude pre-merger ticker history; training eligibility starts after 5 clean post-merger years."),
    TickerSpec("XOM", "Energy", "2010-01-04", None, 5, "Core energy benchmark."),
    TickerSpec("CVX", "Energy", "2010-01-04", None, 5, "Core energy benchmark."),
    TickerSpec("COP", "Energy", "2010-01-04", None, 5, "Core E&P benchmark."),
    TickerSpec("SLB", "Energy", "2010-01-04", None, 5, "Oil-services benchmark."),
    TickerSpec("EOG", "Energy", "2010-01-04", None, 5, "E&P benchmark."),
    TickerSpec("PSX", "Energy", "2012-05-01", None, 5, "Exclude pre-spin history before Phillips 66 began standalone trading."),
    TickerSpec("GE", "Energy", "2010-01-04", None, 5, "Added as a major restructuring / underperformance case."),
    TickerSpec("BA", "Energy", "2010-01-04", None, 5, "Added as an industrial stress-case with major drawdown periods."),
    TickerSpec("F", "Energy", "2010-01-04", None, 5, "Added as a mature cyclical underperformer."),
    TickerSpec("GM", "Energy", "2010-11-18", None, 5, "Use post-relisting history only after 2010 IPO."),
]


REAL_UNIVERSE: Dict[str, List[str]] = {}
for spec in REAL_TICKER_SPECS:
    REAL_UNIVERSE.setdefault(spec.sector, []).append(spec.ticker)

REAL_SECTORS = list(REAL_UNIVERSE.keys())
ALL_REAL_TICKERS = [spec.ticker for spec in REAL_TICKER_SPECS]


def manifest_records() -> List[Dict[str, object]]:
    return [asdict(spec) for spec in REAL_TICKER_SPECS]


@lru_cache(maxsize=32)
def _load_manifest_cached(path_str: str, mtime_ns: int) -> tuple[TickerSpec, ...]:
    path = Path(path_str)
    if path.exists():
        payload = json.loads(path.read_text())
        return tuple(
            TickerSpec(**item)
            for item in payload.get("tickers", [])
        )
    return tuple(REAL_TICKER_SPECS)


def load_universe_manifest(path: str | Path | None = None) -> Dict[str, TickerSpec]:
    manifest_path = Path(path) if path else universe_manifest_path()
    mtime_ns = manifest_path.stat().st_mtime_ns if manifest_path.exists() else -1
    return {
        spec.ticker.upper(): spec
        for spec in _load_manifest_cached(str(manifest_path), mtime_ns)
    }


def write_universe_manifest(path: str | Path | None = None) -> Path:
    out_path = Path(path) if path else universe_manifest_path()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "tickers": manifest_records(),
        "summary": {
            "n_tickers": len(REAL_TICKER_SPECS),
            "sectors": REAL_SECTORS,
        },
    }
    out_path.write_text(json.dumps(payload, indent=2) + "\n")
    return out_path
