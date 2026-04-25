"""Validator and quarantine manager for the local parquet market-data store."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
import json
from pathlib import Path
import shutil
from typing import Dict, Iterable, List, Sequence

import numpy as np
import pandas as pd

from .paths import (
    MarketDataPaths,
    default_paths,
    ticker_year_path,
    validation_report_path,
)
from .universe import load_universe_manifest


@dataclass
class ValidationIssue:
    ticker: str
    code: str
    message: str
    affected_dates: List[str] = field(default_factory=list)
    affected_years: List[int] = field(default_factory=list)


@dataclass
class TickerValidationSummary:
    ticker: str
    clean: bool
    clean_trading_days: int
    usable_start: str | None
    usable_end: str | None
    issues: List[ValidationIssue] = field(default_factory=list)


@dataclass
class ValidationReport:
    generated_at: str
    tickers: List[TickerValidationSummary]

    def to_dict(self) -> Dict[str, object]:
        return {
            "generated_at": self.generated_at,
            "tickers": [
                {
                    "ticker": item.ticker,
                    "clean": item.clean,
                    "clean_trading_days": item.clean_trading_days,
                    "usable_start": item.usable_start,
                    "usable_end": item.usable_end,
                    "issues": [asdict(issue) for issue in item.issues],
                }
                for item in self.tickers
            ],
        }


def _business_gap_runs(index: pd.DatetimeIndex) -> List[pd.DatetimeIndex]:
    if len(index) == 0:
        return []
    expected = pd.date_range(index.min(), index.max(), freq="B")
    missing = expected.difference(index)
    if len(missing) == 0:
        return []

    runs: List[List[pd.Timestamp]] = []
    current = [missing[0]]
    for stamp in missing[1:]:
        if (stamp - current[-1]).days == 1:
            current.append(stamp)
        else:
            runs.append(current)
            current = [stamp]
    runs.append(current)
    return [pd.DatetimeIndex(run) for run in runs]


def _affected_years(dates: Sequence[pd.Timestamp]) -> List[int]:
    return sorted({int(pd.Timestamp(item).year) for item in dates})


class MarketDataValidator:
    """Validates parquet files and quarantines years with hard data issues."""

    def __init__(self, base_dir: str | Path | None = None):
        self.paths: MarketDataPaths = default_paths(base_dir)
        self._manifest_path = self.paths.universe_root / "real_ticker_manifest.json"

    def _active_year_paths(self, ticker: str) -> List[Path]:
        ticker_root = self.paths.market_root / ticker.upper()
        if not ticker_root.exists():
            return []
        return sorted(ticker_root.glob("*.parquet"))

    def _load_ticker(self, ticker: str) -> pd.DataFrame:
        frames = [pd.read_parquet(path) for path in self._active_year_paths(ticker)]
        if not frames:
            return pd.DataFrame()
        df = pd.concat(frames, axis=0)
        df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
        df = df[~df.index.duplicated(keep="last")].sort_index()
        spec = load_universe_manifest(self._manifest_path).get(ticker.upper())
        if spec is not None:
            start = pd.Timestamp(spec.usable_start).tz_localize(None).normalize()
            df = df.loc[start:]
            if spec.usable_end is not None:
                end = pd.Timestamp(spec.usable_end).tz_localize(None).normalize()
                df = df.loc[:end]
        return df

    def _check_ticker(self, ticker: str, df: pd.DataFrame) -> List[ValidationIssue]:
        issues: List[ValidationIssue] = []
        if df.empty:
            issues.append(
                ValidationIssue(
                    ticker=ticker,
                    code="missing_data",
                    message="No parquet files available for ticker.",
                )
            )
            return issues

        numeric_cols = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]
        if df[numeric_cols].isna().any().any():
            bad_rows = df.index[df[numeric_cols].isna().any(axis=1)]
            issues.append(
                ValidationIssue(
                    ticker=ticker,
                    code="nan_values",
                    message="Found NaN values in required OHLCV columns.",
                    affected_dates=[item.date().isoformat() for item in bad_rows[:10]],
                    affected_years=_affected_years(bad_rows),
                )
            )

        bad_price_mask = (
            (df["Open"] <= 0)
            | (df["High"] <= 0)
            | (df["Low"] <= 0)
            | (df["Close"] <= 0)
            | (df["Adj Close"] <= 0)
            | (df["High"] < df["Low"])
        )
        if bad_price_mask.any():
            bad_rows = df.index[bad_price_mask]
            issues.append(
                ValidationIssue(
                    ticker=ticker,
                    code="bad_prices",
                    message="Detected non-positive prices or invalid high/low ranges.",
                    affected_dates=[item.date().isoformat() for item in bad_rows[:10]],
                    affected_years=_affected_years(bad_rows),
                )
            )

        zero_volume_mask = df["Volume"] <= 0
        if zero_volume_mask.any():
            bad_rows = df.index[zero_volume_mask]
            issues.append(
                ValidationIssue(
                    ticker=ticker,
                    code="zero_volume",
                    message="Detected zero-volume rows in the active dataset.",
                    affected_dates=[item.date().isoformat() for item in bad_rows[:10]],
                    affected_years=_affected_years(bad_rows),
                )
            )

        for run in _business_gap_runs(df.index):
            if len(run) > 3:
                issues.append(
                    ValidationIssue(
                        ticker=ticker,
                        code="missing_days",
                        message=f"Found {len(run)} consecutive missing business days.",
                        affected_dates=[item.date().isoformat() for item in run],
                        affected_years=_affected_years(run),
                    )
                )

        returns = df["Close"].pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)
        extreme_mask = returns.abs() > 0.50
        if extreme_mask.any():
            bad_rows = df.index[extreme_mask]
            issues.append(
                ValidationIssue(
                    ticker=ticker,
                    code="extreme_return",
                    message="Detected a daily close-to-close move above +/-50%.",
                    affected_dates=[item.date().isoformat() for item in bad_rows[:10]],
                    affected_years=_affected_years(bad_rows),
                )
            )

        denom = df["Close"].replace(0.0, np.nan)
        adj_factor = (df["Adj Close"] / denom).replace([np.inf, -np.inf], np.nan).fillna(1.0)
        factor_jump = adj_factor.pct_change().abs().fillna(0.0)
        no_corporate_action = (
            df.get("Dividends", pd.Series(0.0, index=df.index)).fillna(0.0).abs() < 1e-12
        ) & (
            df.get("Stock Splits", pd.Series(0.0, index=df.index)).fillna(0.0).abs() < 1e-12
        )
        divergence_mask = (factor_jump > 0.05) & no_corporate_action
        if divergence_mask.any():
            bad_rows = df.index[divergence_mask]
            issues.append(
                ValidationIssue(
                    ticker=ticker,
                    code="adj_close_divergence",
                    message="Adjustment factor changed by more than 5% without a dividend or split.",
                    affected_dates=[item.date().isoformat() for item in bad_rows[:10]],
                    affected_years=_affected_years(bad_rows),
                )
            )

        return issues

    def _quarantine_years(self, ticker: str, years: Iterable[int]) -> None:
        for year in sorted(set(int(item) for item in years)):
            src = ticker_year_path(ticker, year, self.paths.market_root)
            if not src.exists():
                continue
            dst = ticker_year_path(ticker, year, self.paths.market_root, quarantined=True)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))

    def validate_ticker(self, ticker: str, *, quarantine: bool = True) -> TickerValidationSummary:
        df = self._load_ticker(ticker)
        issues = self._check_ticker(ticker, df)
        affected_years = sorted({year for issue in issues for year in issue.affected_years})
        if quarantine and affected_years:
            self._quarantine_years(ticker, affected_years)
            df = self._load_ticker(ticker)

        usable_start = df.index[0].date().isoformat() if not df.empty else None
        usable_end = df.index[-1].date().isoformat() if not df.empty else None
        return TickerValidationSummary(
            ticker=ticker,
            clean=len(issues) == 0,
            clean_trading_days=int(len(df)),
            usable_start=usable_start,
            usable_end=usable_end,
            issues=issues,
        )

    def validate_all(self, tickers: Iterable[str] | None = None, *, quarantine: bool = True) -> ValidationReport:
        if tickers is None:
            tickers = sorted(
                path.name for path in self.paths.market_root.iterdir() if path.is_dir()
            )
        summaries = [
            self.validate_ticker(ticker, quarantine=quarantine)
            for ticker in sorted({ticker.upper() for ticker in tickers})
        ]
        report = ValidationReport(
            generated_at=pd.Timestamp.utcnow().isoformat(),
            tickers=summaries,
        )
        out_path = validation_report_path(self.paths.market_root)
        out_path.write_text(json.dumps(report.to_dict(), indent=2) + "\n")
        return report
