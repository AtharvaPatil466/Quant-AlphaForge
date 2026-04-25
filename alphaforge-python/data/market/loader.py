"""Loader for clean aligned market data from the local parquet store."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, Mapping

import pandas as pd

from .paths import MarketDataPaths, default_paths
from .universe import load_universe_manifest


@lru_cache(maxsize=512)
def _read_parquet_cached(path_str: str, mtime_ns: int) -> pd.DataFrame:
    path = Path(path_str)
    return pd.read_parquet(path)


def _coerce_timestamp(value: str | pd.Timestamp | None) -> pd.Timestamp | None:
    if value is None:
        return None
    return pd.Timestamp(value).tz_localize(None).normalize()


class MarketDataError(RuntimeError):
    """Base class for local market-data access failures."""


class MarketDataRangeError(MarketDataError):
    """Requested range violates the documented usable window."""


class TickerQuarantinedError(MarketDataError):
    """Ticker has only quarantined parquet files and cannot be served."""


class MarketDataLoader:
    """Reads validated parquet files without making any network calls."""

    def __init__(self, base_dir: str | Path | None = None):
        self.paths: MarketDataPaths = default_paths(base_dir)
        self._manifest_path = self.paths.universe_root / "real_ticker_manifest.json"

    def _manifest_spec(self, ticker: str):
        return load_universe_manifest(self._manifest_path).get(ticker.upper())

    def _quarantine_year_paths(self, ticker: str) -> list[Path]:
        root = self.paths.quarantine_root / ticker.upper()
        if not root.exists():
            return []
        return sorted(root.glob("*.parquet"))

    def _active_year_paths(
        self,
        ticker: str,
        start_date: pd.Timestamp | None = None,
        end_date: pd.Timestamp | None = None,
    ) -> list[Path]:
        root = self.paths.market_root / ticker.upper()
        if not root.exists():
            return []
        paths = sorted(root.glob("*.parquet"))
        if start_date is None and end_date is None:
            return paths

        start_year = start_date.year if start_date is not None else None
        end_year = end_date.year if end_date is not None else None
        filtered = []
        for path in paths:
            try:
                year = int(path.stem)
            except ValueError:
                filtered.append(path)
                continue
            if start_year is not None and year < start_year:
                continue
            if end_year is not None and year > end_year:
                continue
            filtered.append(path)
        return filtered

    def _manifest_window(
        self,
        ticker: str,
    ) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
        spec = self._manifest_spec(ticker)
        if spec is None:
            return None, None
        start = _coerce_timestamp(spec.usable_start)
        end = _coerce_timestamp(spec.usable_end)
        return start, end

    def _validate_request(
        self,
        ticker: str,
        start_date: pd.Timestamp | None,
        end_date: pd.Timestamp | None,
    ) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
        if start_date is not None and end_date is not None and start_date > end_date:
            raise MarketDataRangeError(
                f"{ticker.upper()} requested start_date {start_date.date().isoformat()} "
                f"is after end_date {end_date.date().isoformat()}."
            )

        active_paths = self._active_year_paths(ticker)
        if not active_paths and self._quarantine_year_paths(ticker):
            raise TickerQuarantinedError(
                f"{ticker.upper()} has no active parquet files; only quarantined data is available."
            )

        manifest_start, manifest_end = self._manifest_window(ticker)
        if (
            start_date is not None
            and manifest_start is not None
            and start_date < manifest_start
        ):
            raise MarketDataRangeError(
                f"{ticker.upper()} usable_start is {manifest_start.date().isoformat()}; "
                f"requested {start_date.date().isoformat()}."
            )
        if (
            end_date is not None
            and manifest_end is not None
            and end_date > manifest_end
        ):
            raise MarketDataRangeError(
                f"{ticker.upper()} usable_end is {manifest_end.date().isoformat()}; "
                f"requested {end_date.date().isoformat()}."
            )
        return manifest_start, manifest_end

    def available_tickers(self) -> list[str]:
        return sorted(path.name for path in self.paths.market_root.iterdir() if path.is_dir())

    def available_range(self, ticker: str) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
        df = self.load_ticker(ticker)
        if df.empty:
            return None, None
        return pd.Timestamp(df.index[0]), pd.Timestamp(df.index[-1])

    def load_ticker(
        self,
        ticker: str,
        start_date: str | pd.Timestamp | None = None,
        end_date: str | pd.Timestamp | None = None,
    ) -> pd.DataFrame:
        ticker = ticker.upper()
        requested_start = _coerce_timestamp(start_date)
        requested_end = _coerce_timestamp(end_date)
        manifest_start, manifest_end = self._validate_request(
            ticker,
            requested_start,
            requested_end,
        )

        read_start = requested_start
        read_end = requested_end
        if manifest_start is not None and (read_start is None or manifest_start > read_start):
            read_start = manifest_start
        if manifest_end is not None and (read_end is None or manifest_end < read_end):
            read_end = manifest_end

        frames = []
        for path in self._active_year_paths(ticker, start_date=read_start, end_date=read_end):
            stat = path.stat()
            df = _read_parquet_cached(str(path), stat.st_mtime_ns)
            frames.append(df)

        if not frames:
            return pd.DataFrame()

        out = pd.concat(frames, axis=0)
        out.index = pd.to_datetime(out.index).tz_localize(None).normalize()
        out = out[~out.index.duplicated(keep="last")].sort_index()

        if manifest_start is not None:
            out = out.loc[manifest_start:]
        if manifest_end is not None:
            out = out.loc[:manifest_end]
        if requested_start is not None:
            out = out.loc[requested_start:]
        if requested_end is not None:
            out = out.loc[:requested_end]
        return out

    def load_history(
        self,
        tickers: Iterable[str],
        start_date: str | pd.Timestamp | None = None,
        end_date: str | pd.Timestamp | None = None,
        *,
        align: str = "inner",
        min_rows: int = 1,
    ) -> Dict[str, pd.DataFrame]:
        history: Dict[str, pd.DataFrame] = {}
        for ticker in tickers:
            df = self.load_ticker(ticker, start_date=start_date, end_date=end_date)
            if len(df) >= min_rows:
                history[ticker.upper()] = df

        if not history or align == "none":
            return history

        common_index = None
        if align == "inner":
            for df in history.values():
                common_index = df.index if common_index is None else common_index.intersection(df.index)
        elif align == "outer":
            for df in history.values():
                common_index = df.index if common_index is None else common_index.union(df.index)
        else:
            raise ValueError(f"Unknown align mode '{align}'")

        if common_index is None or len(common_index) == 0:
            return {}
        return {ticker: df.loc[common_index].copy() for ticker, df in history.items()}

    def load_latest(
        self,
        tickers: Iterable[str],
        end_date: str | pd.Timestamp | None = None,
    ) -> Dict[str, pd.Series]:
        history = self.load_history(tickers, end_date=end_date, align="none")
        latest: Dict[str, pd.Series] = {}
        for ticker, df in history.items():
            if not df.empty:
                latest[ticker] = df.iloc[-1]
        return latest
