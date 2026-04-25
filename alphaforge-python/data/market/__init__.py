"""Local real-market data package backed by on-disk parquet files."""

from .downloader import MarketDataDownloader, SyncResult
from .loader import (
    MarketDataError,
    MarketDataLoader,
    MarketDataRangeError,
    TickerQuarantinedError,
)
from .paths import MarketDataPaths, default_paths
from .universe import (
    ALL_REAL_TICKERS,
    REAL_SECTORS,
    REAL_TICKER_SPECS,
    REAL_UNIVERSE,
    TickerSpec,
    load_universe_manifest,
    write_universe_manifest,
)
from .validator import (
    MarketDataValidator,
    TickerValidationSummary,
    ValidationIssue,
    ValidationReport,
)

__all__ = [
    "ALL_REAL_TICKERS",
    "MarketDataDownloader",
    "MarketDataError",
    "MarketDataLoader",
    "MarketDataRangeError",
    "MarketDataPaths",
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
