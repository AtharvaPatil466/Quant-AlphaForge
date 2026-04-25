"""Filesystem layout for the local parquet-backed market data store."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MarketDataPaths:
    repo_root: Path
    data_root: Path
    market_root: Path
    quarantine_root: Path
    reports_root: Path
    universe_root: Path


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def default_paths(base_dir: str | Path | None = None) -> MarketDataPaths:
    repo_root = default_repo_root()
    data_root = repo_root / "data"
    market_root = Path(base_dir).expanduser().resolve() if base_dir else data_root / "market"
    if base_dir:
        data_root = market_root.parent

    paths = MarketDataPaths(
        repo_root=repo_root,
        data_root=data_root,
        market_root=market_root,
        quarantine_root=data_root / "quarantine" / "market",
        reports_root=data_root / "reports",
        universe_root=data_root / "universe",
    )
    for path in (
        paths.data_root,
        paths.market_root,
        paths.quarantine_root,
        paths.reports_root,
        paths.universe_root,
    ):
        path.mkdir(parents=True, exist_ok=True)
    return paths


def ticker_dir(ticker: str, base_dir: str | Path | None = None) -> Path:
    paths = default_paths(base_dir)
    return paths.market_root / ticker.upper()


def ticker_year_path(
    ticker: str,
    year: int,
    base_dir: str | Path | None = None,
    *,
    quarantined: bool = False,
) -> Path:
    paths = default_paths(base_dir)
    root = paths.quarantine_root if quarantined else paths.market_root
    return root / ticker.upper() / f"{int(year)}.parquet"


def validation_report_path(base_dir: str | Path | None = None) -> Path:
    paths = default_paths(base_dir)
    return paths.reports_root / "market_validation_report.json"


def sync_report_path(base_dir: str | Path | None = None) -> Path:
    paths = default_paths(base_dir)
    return paths.reports_root / "market_sync_report.json"


def universe_manifest_path(base_dir: str | Path | None = None) -> Path:
    paths = default_paths(base_dir)
    return paths.universe_root / "real_ticker_manifest.json"
