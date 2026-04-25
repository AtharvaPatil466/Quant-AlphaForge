"""Downloader for the local parquet-backed market-data store."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
import json
import math
from pathlib import Path
from typing import Dict, Iterable, List, Mapping

import pandas as pd

from .paths import MarketDataPaths, default_paths, sync_report_path, ticker_year_path


REQUIRED_COLUMNS = [
    "Open",
    "High",
    "Low",
    "Close",
    "Adj Close",
    "Volume",
    "Dividends",
    "Stock Splits",
]


@dataclass
class SyncResult:
    start_date: str
    end_date: str
    tickers: List[str]
    downloaded_rows: Dict[str, int] = field(default_factory=dict)
    written_files: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=REQUIRED_COLUMNS)

    out = df.copy()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = out.columns.get_level_values(0)
    for column in REQUIRED_COLUMNS:
        if column not in out.columns:
            out[column] = 0.0
    out = out[REQUIRED_COLUMNS]
    out.index = pd.to_datetime(out.index).tz_localize(None).normalize()
    out = out.dropna(subset=["Open", "High", "Low", "Close", "Adj Close", "Volume"])
    if "Dividends" in out.columns:
        out["Dividends"] = out["Dividends"].fillna(0.0)
    if "Stock Splits" in out.columns:
        out["Stock Splits"] = out["Stock Splits"].fillna(0.0)
    out = out[~out.index.duplicated(keep="last")]
    out = out.sort_index()
    return out


def _split_download_frame(downloaded: pd.DataFrame, tickers: Iterable[str]) -> Dict[str, pd.DataFrame]:
    tickers = [ticker.upper() for ticker in tickers]
    if downloaded.empty:
        return {}

    if isinstance(downloaded.columns, pd.MultiIndex):
        result: Dict[str, pd.DataFrame] = {}
        for ticker in tickers:
            if ticker not in downloaded.columns.get_level_values(0):
                continue
            result[ticker] = _normalize_ohlcv(downloaded[ticker])
        return result

    if len(tickers) == 1:
        return {tickers[0]: _normalize_ohlcv(downloaded)}

    # yfinance can occasionally flatten partial responses; guard by returning empties
    result = {}
    for ticker in tickers:
        result[ticker] = pd.DataFrame(columns=REQUIRED_COLUMNS)
    return result


def _merge_year_file(path: Path, new_rows: pd.DataFrame) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=REQUIRED_COLUMNS)
    if existing.empty:
        merged = new_rows.copy()
    else:
        merged = pd.concat([existing, new_rows], axis=0)
    merged = _normalize_ohlcv(merged)
    merged.to_parquet(path)
    return len(merged)


class MarketDataDownloader:
    """Bulk downloader that writes one parquet file per ticker per year."""

    def __init__(self, base_dir: str | Path | None = None, *, chunk_size: int = 10):
        self.paths: MarketDataPaths = default_paths(base_dir)
        self.chunk_size = max(1, int(chunk_size))

    def download(
        self,
        tickers: Iterable[str],
        start_date: date | str,
        end_date: date | str | None = None,
    ) -> Dict[str, pd.DataFrame]:
        try:
            import yfinance as yf
        except ImportError as exc:
            raise RuntimeError("yfinance is required for market-data sync") from exc

        start = date.fromisoformat(start_date) if isinstance(start_date, str) else start_date
        end = date.fromisoformat(end_date) if isinstance(end_date, str) else (end_date or date.today())
        tickers = [ticker.upper() for ticker in tickers]
        result: Dict[str, pd.DataFrame] = {}

        for offset in range(0, len(tickers), self.chunk_size):
            batch = tickers[offset : offset + self.chunk_size]
            downloaded = yf.download(
                batch,
                start=start.isoformat(),
                end=(end + timedelta(days=1)).isoformat(),
                auto_adjust=False,
                actions=True,
                group_by="ticker",
                progress=False,
                threads=True,
            )
            result.update(_split_download_frame(downloaded, batch))
        return result

    def write_frames(self, history: Mapping[str, pd.DataFrame]) -> SyncResult:
        earliest = None
        latest = None
        written_files: List[str] = []
        row_counts: Dict[str, int] = {}

        for ticker, df in history.items():
            normalized = _normalize_ohlcv(df)
            if normalized.empty:
                row_counts[ticker] = 0
                continue

            row_counts[ticker] = len(normalized)
            first_dt = normalized.index[0].date()
            last_dt = normalized.index[-1].date()
            earliest = first_dt if earliest is None else min(earliest, first_dt)
            latest = last_dt if latest is None else max(latest, last_dt)

            for year, year_df in normalized.groupby(normalized.index.year):
                path = ticker_year_path(ticker, int(year), self.paths.market_root)
                _merge_year_file(path, year_df)
                try:
                    written_files.append(str(path.relative_to(self.paths.repo_root)))
                except ValueError:
                    written_files.append(str(path))

        return SyncResult(
            start_date=(earliest or date.today()).isoformat(),
            end_date=(latest or date.today()).isoformat(),
            tickers=sorted(history.keys()),
            downloaded_rows=row_counts,
            written_files=sorted(set(written_files)),
        )

    def sync(
        self,
        tickers: Iterable[str],
        start_date: date | str,
        end_date: date | str | None = None,
    ) -> SyncResult:
        history = self.download(tickers, start_date=start_date, end_date=end_date)
        result = self.write_frames(history)
        report_path = sync_report_path(self.paths.market_root)
        report_path.write_text(json.dumps(result.to_dict(), indent=2) + "\n")
        return result
