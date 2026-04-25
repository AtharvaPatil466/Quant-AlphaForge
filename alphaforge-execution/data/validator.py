"""Validate market data before use."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List

import pandas as pd


class DataValidationError(Exception):
    pass


def validate_history(
    history: Dict[str, pd.DataFrame],
    expected_tickers: List[str],
    min_days: int = 30,
    check_staleness: bool = True,
) -> None:
    """Raise DataValidationError if data is incomplete or stale."""
    # Check all tickers present
    missing = [t for t in expected_tickers if t not in history]
    if missing:
        raise DataValidationError(f"Missing tickers: {missing}")

    for ticker, df in history.items():
        if ticker not in expected_tickers:
            continue

        # Check minimum history length
        if len(df) < min_days:
            raise DataValidationError(
                f"{ticker}: only {len(df)} days of data (need {min_days})"
            )

        # Check for NaN in Close prices
        nan_count = df["Close"].isna().sum()
        if nan_count > 0:
            raise DataValidationError(
                f"{ticker}: {nan_count} NaN values in Close prices"
            )

        # Check for zero volumes (suspicious)
        zero_vol = (df["Volume"] == 0).sum()
        if zero_vol > len(df) * 0.1:  # more than 10% zero volume days
            raise DataValidationError(
                f"{ticker}: {zero_vol} zero-volume days ({zero_vol/len(df)*100:.0f}%)"
            )

        # Check data is not stale. Measure staleness in *trading* days since
        # the last known NYSE session (not calendar days) so weekends and
        # holidays don't trip the check. Allow up to 2 trading days of lag
        # (accounts for pre-open runs before today's bar is available).
        if check_staleness:
            last_date = df.index[-1].date() if hasattr(df.index[-1], "date") else df.index[-1]
            staleness_td = _trading_days_between(last_date, date.today())
            if staleness_td > 2:
                raise DataValidationError(
                    f"{ticker}: data is {staleness_td} trading days stale (last: {last_date})"
                )


def _trading_days_between(start: date, end: date) -> int:
    """Approximate NYSE trading days between `start` (exclusive) and `end` (inclusive).

    Uses the execution system's market_calendar helper when available so NYSE
    holidays are honored. Falls back to a weekday count otherwise.
    """
    if end <= start:
        return 0
    try:
        from market_calendar import is_market_day  # type: ignore
    except Exception:
        is_market_day = None

    count = 0
    d = start + timedelta(days=1)
    while d <= end:
        if is_market_day is not None:
            if is_market_day(d):
                count += 1
        elif d.weekday() < 5:
            count += 1
        d += timedelta(days=1)
    return count
