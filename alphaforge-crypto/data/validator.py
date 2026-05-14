"""Parquet integrity checks for the Binance store.

Mirrors the equity-stack validator's discipline: run as a separate pass after
the downloader, emit a structured report, and surface issues without silently
deleting data. Quarantining is left to the caller — the validator only reports.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd
import pyarrow.parquet as pq

from .downloader import INTERVAL_MS
from .paths import BinancePaths, default_paths


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    detail: str


@dataclass
class SymbolReport:
    symbol: str
    stream: str
    rows: int
    first_ts_ms: int | None
    last_ts_ms: int | None
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "stream": self.stream,
            "rows": self.rows,
            "first_ts_ms": self.first_ts_ms,
            "last_ts_ms": self.last_ts_ms,
            "issues": [asdict(i) for i in self.issues],
            "clean": self.clean,
        }


@dataclass
class ValidationReport:
    generated_at: str
    items: list[SymbolReport] = field(default_factory=list)

    @property
    def clean_count(self) -> int:
        return sum(1 for it in self.items if it.clean)

    @property
    def flagged_count(self) -> int:
        return sum(1 for it in self.items if not it.clean)

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "clean_count": self.clean_count,
            "flagged_count": self.flagged_count,
            "items": [it.to_dict() for it in self.items],
        }


class BinanceDataValidator:
    def __init__(
        self,
        *,
        base_dir: str | Path | None = None,
        kline_interval: str = "1h",
    ):
        self.paths: BinancePaths = default_paths(base_dir)
        if kline_interval not in INTERVAL_MS:
            raise ValueError(f"unsupported kline interval {kline_interval!r}")
        self.kline_interval = kline_interval
        self.interval_ms = INTERVAL_MS[kline_interval]

    def validate_all(
        self,
        symbols: Iterable[str],
        *,
        include_spot: bool = True,
        include_perp: bool = True,
        include_funding: bool = True,
        include_open_interest: bool = False,
    ) -> ValidationReport:
        report = ValidationReport(generated_at=datetime.now(timezone.utc).isoformat())
        for symbol in symbols:
            symbol = symbol.upper()
            if include_spot:
                report.items.append(self._validate_klines(symbol, "spot"))
            if include_perp:
                report.items.append(self._validate_klines(symbol, "perp"))
            if include_funding:
                report.items.append(self._validate_funding(symbol))
            if include_open_interest:
                report.items.append(self._validate_open_interest(symbol))
        return report

    def _validate_klines(self, symbol: str, market: str) -> SymbolReport:
        symbol_dir = (
            self.paths.spot_klines_root if market == "spot" else self.paths.perp_klines_root
        ) / symbol
        stream = f"klines_{self.kline_interval}_{market}"
        frame = _load_concat(symbol_dir, sort_key="open_time")
        if frame is None:
            return SymbolReport(symbol, stream, 0, None, None, [ValidationIssue("no_data", "no parquet shards found")])

        issues: list[ValidationIssue] = []
        if not frame["open_time"].is_monotonic_increasing:
            issues.append(ValidationIssue("non_monotonic_timestamps", "open_time is not strictly increasing after dedup"))
        if frame["open_time"].duplicated().any():
            issues.append(ValidationIssue("duplicate_timestamps", f"{int(frame['open_time'].duplicated().sum())} duplicates"))
        diffs = frame["open_time"].diff().dropna().astype("int64")
        unexpected = diffs[diffs != self.interval_ms]
        if not unexpected.empty:
            issues.append(
                ValidationIssue(
                    "irregular_bar_spacing",
                    f"{len(unexpected)} bar gaps != {self.interval_ms}ms (likely listing-date or exchange downtime)",
                )
            )
        if (frame["volume"] < 0).any():
            issues.append(ValidationIssue("negative_volume", "negative volume values present"))
        for col in ["open", "high", "low", "close"]:
            if (frame[col] <= 0).any():
                issues.append(ValidationIssue(f"non_positive_{col}", f"{col} has non-positive values"))
        if frame[["open", "high", "low", "close"]].isna().any().any():
            issues.append(ValidationIssue("nan_prices", "NaN values in OHLC columns"))

        return SymbolReport(
            symbol=symbol,
            stream=stream,
            rows=len(frame),
            first_ts_ms=int(frame["open_time"].iloc[0]),
            last_ts_ms=int(frame["open_time"].iloc[-1]),
            issues=issues,
        )

    def _validate_funding(self, symbol: str) -> SymbolReport:
        from .paths import funding_path

        path = funding_path(symbol, base_dir=self.paths.binance_root)
        if not path.exists():
            return SymbolReport(symbol, "funding", 0, None, None, [ValidationIssue("no_data", "no funding parquet file")])
        frame = pq.read_table(path).to_pandas().sort_values("funding_time").reset_index(drop=True)
        if frame.empty:
            return SymbolReport(symbol, "funding", 0, None, None, [ValidationIssue("no_data", "funding parquet is empty")])

        issues: list[ValidationIssue] = []
        if frame["funding_time"].duplicated().any():
            issues.append(ValidationIssue("duplicate_funding_times", f"{int(frame['funding_time'].duplicated().sum())} duplicates"))
        if frame["funding_rate"].isna().any():
            issues.append(ValidationIssue("nan_funding_rate", "NaN funding rates present"))
        if (frame["funding_rate"].abs() > 0.05).any():
            issues.append(
                ValidationIssue(
                    "extreme_funding_rate",
                    f"{int((frame['funding_rate'].abs() > 0.05).sum())} rows with |funding_rate| > 5% — verify scale",
                )
            )

        return SymbolReport(
            symbol=symbol,
            stream="funding",
            rows=len(frame),
            first_ts_ms=int(frame["funding_time"].iloc[0]),
            last_ts_ms=int(frame["funding_time"].iloc[-1]),
            issues=issues,
        )

    def _validate_open_interest(self, symbol: str) -> SymbolReport:
        symbol_dir = self.paths.open_interest_root / symbol
        frame = _load_concat(symbol_dir, sort_key="timestamp")
        if frame is None:
            return SymbolReport(symbol, "open_interest", 0, None, None, [ValidationIssue("no_data", "no OI parquet shards")])
        issues: list[ValidationIssue] = []
        if frame["timestamp"].duplicated().any():
            issues.append(ValidationIssue("duplicate_oi_timestamps", f"{int(frame['timestamp'].duplicated().sum())} duplicates"))
        if (frame["sum_open_interest"] < 0).any():
            issues.append(ValidationIssue("negative_oi", "negative open interest values"))
        return SymbolReport(
            symbol=symbol,
            stream="open_interest",
            rows=len(frame),
            first_ts_ms=int(frame["timestamp"].iloc[0]),
            last_ts_ms=int(frame["timestamp"].iloc[-1]),
            issues=issues,
        )


def _load_concat(symbol_dir: Path, *, sort_key: str) -> pd.DataFrame | None:
    if not symbol_dir.exists():
        return None
    parts = sorted(symbol_dir.glob("*.parquet"))
    if not parts:
        return None
    frames = [pq.read_table(p).to_pandas() for p in parts]
    if not frames:
        return None
    combined = pd.concat(frames, ignore_index=True)
    return combined.drop_duplicates(subset=[sort_key]).sort_values(sort_key).reset_index(drop=True)
