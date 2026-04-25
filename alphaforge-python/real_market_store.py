"""Unambiguous import surface for the shared local market-data store."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


_PACKAGE_ROOT = Path(__file__).resolve().parent / "data" / "market"
_SPEC = importlib.util.spec_from_file_location(
    "_shared_market_data",
    _PACKAGE_ROOT / "__init__.py",
    submodule_search_locations=[str(_PACKAGE_ROOT)],
)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("Could not load shared market-data package")

_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules.setdefault(_SPEC.name, _MODULE)
_SPEC.loader.exec_module(_MODULE)

ALL_REAL_TICKERS = _MODULE.ALL_REAL_TICKERS
MarketDataDownloader = _MODULE.MarketDataDownloader
MarketDataError = _MODULE.MarketDataError
MarketDataLoader = _MODULE.MarketDataLoader
MarketDataRangeError = _MODULE.MarketDataRangeError
MarketDataValidator = _MODULE.MarketDataValidator
REAL_SECTORS = _MODULE.REAL_SECTORS
REAL_TICKER_SPECS = _MODULE.REAL_TICKER_SPECS
REAL_UNIVERSE = _MODULE.REAL_UNIVERSE
SyncResult = _MODULE.SyncResult
TickerSpec = _MODULE.TickerSpec
TickerQuarantinedError = _MODULE.TickerQuarantinedError
TickerValidationSummary = _MODULE.TickerValidationSummary
ValidationIssue = _MODULE.ValidationIssue
ValidationReport = _MODULE.ValidationReport
default_paths = _MODULE.default_paths
load_universe_manifest = _MODULE.load_universe_manifest
write_universe_manifest = _MODULE.write_universe_manifest

__all__ = [
    "ALL_REAL_TICKERS",
    "MarketDataDownloader",
    "MarketDataError",
    "MarketDataLoader",
    "MarketDataRangeError",
    "MarketDataValidator",
    "REAL_SECTORS",
    "REAL_TICKER_SPECS",
    "REAL_UNIVERSE",
    "SyncResult",
    "TickerSpec",
    "TickerQuarantinedError",
    "TickerValidationSummary",
    "ValidationIssue",
    "ValidationReport",
    "default_paths",
    "load_universe_manifest",
    "write_universe_manifest",
]
