"""Filesystem layout for the local Binance parquet store.

Mirrors the equity stack's data/market/paths.py discipline: every shard lives
under <repo>/data/binance/ unless explicitly overridden, and the helpers ensure
parent directories exist before callers write.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


SPOT_KLINES_DIR = "klines_1h_spot"
PERP_KLINES_DIR = "klines_1h_perp"
FUNDING_DIR = "funding"
OI_DIR = "open_interest"
QUARANTINE_DIR = "_quarantine"
MANIFEST_FILENAME = "_manifest.json"


@dataclass(frozen=True)
class BinancePaths:
    repo_root: Path
    data_root: Path
    binance_root: Path
    spot_klines_root: Path
    perp_klines_root: Path
    funding_root: Path
    open_interest_root: Path
    quarantine_root: Path
    manifest_path: Path


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_paths(base_dir: str | Path | None = None) -> BinancePaths:
    repo_root = default_repo_root()
    data_root = repo_root / "data"
    binance_root = (
        Path(base_dir).expanduser().resolve()
        if base_dir
        else data_root / "binance"
    )
    if base_dir:
        data_root = binance_root.parent

    paths = BinancePaths(
        repo_root=repo_root,
        data_root=data_root,
        binance_root=binance_root,
        spot_klines_root=binance_root / SPOT_KLINES_DIR,
        perp_klines_root=binance_root / PERP_KLINES_DIR,
        funding_root=binance_root / FUNDING_DIR,
        open_interest_root=binance_root / OI_DIR,
        quarantine_root=binance_root / QUARANTINE_DIR,
        manifest_path=binance_root / MANIFEST_FILENAME,
    )
    for path in (
        paths.binance_root,
        paths.spot_klines_root,
        paths.perp_klines_root,
        paths.funding_root,
        paths.open_interest_root,
        paths.quarantine_root,
    ):
        path.mkdir(parents=True, exist_ok=True)
    return paths


def _kline_root(market: str, paths: BinancePaths) -> Path:
    if market == "spot":
        return paths.spot_klines_root
    if market == "perp":
        return paths.perp_klines_root
    raise ValueError(f"unknown market {market!r}; expected 'spot' or 'perp'")


def kline_year_path(
    symbol: str,
    year: int,
    market: str,
    base_dir: str | Path | None = None,
    *,
    quarantined: bool = False,
) -> Path:
    paths = default_paths(base_dir)
    if quarantined:
        return paths.quarantine_root / f"{market}_klines" / symbol.upper() / f"{int(year)}.parquet"
    return _kline_root(market, paths) / symbol.upper() / f"{int(year)}.parquet"


def funding_path(
    symbol: str,
    base_dir: str | Path | None = None,
    *,
    quarantined: bool = False,
) -> Path:
    paths = default_paths(base_dir)
    if quarantined:
        return paths.quarantine_root / "funding" / f"{symbol.upper()}.parquet"
    return paths.funding_root / f"{symbol.upper()}.parquet"


def oi_year_path(
    symbol: str,
    year: int,
    base_dir: str | Path | None = None,
    *,
    quarantined: bool = False,
) -> Path:
    paths = default_paths(base_dir)
    root = paths.quarantine_root / "open_interest" if quarantined else paths.open_interest_root
    return root / symbol.upper() / f"{int(year)}.parquet"
