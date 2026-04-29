"""Membership-aware PIT history utilities over the quarantine parquet store.

Phase 1 produced the canonical membership event log and baseline.
Phase 3+ needs a way to combine that time-varying membership with the
much larger OHLCV coverage under `data/quarantine/market/`.

This module intentionally does not try to reuse `MarketDataLoader` from
`data.market.loader`: that loader is scoped to the smaller validated
`data/market/` surface, while PIT work consumes the broad quarantine
store and treats missing/delisted names as explicit coverage gaps.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, Sequence

import numpy as np
import pandas as pd

from data.market.paths import default_paths


ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"


@dataclass(frozen=True)
class PitFieldPanel:
    """Single-field panel with PIT membership and availability masks."""

    field: str
    raw_panel: pd.DataFrame
    panel: pd.DataFrame
    membership_mask: pd.DataFrame
    availability_mask: pd.DataFrame


@lru_cache(maxsize=2048)
def _read_parquet_cached(path_str: str, mtime_ns: int) -> pd.DataFrame:
    return pd.read_parquet(Path(path_str))


def _coerce_timestamp(value: str | pd.Timestamp | None) -> pd.Timestamp | None:
    if value is None:
        return None
    return pd.Timestamp(value).tz_localize(None).normalize()


def load_phase1_membership_artifacts(
    event_path: str | Path | None = None,
    baseline_path: str | Path | None = None,
) -> tuple[pd.DataFrame, set[str]]:
    """Load the Phase 1 event log and baseline membership set."""
    event_file = Path(event_path) if event_path else ARTIFACTS_DIR / "_event_log.parquet"
    baseline_file = (
        Path(baseline_path) if baseline_path else ARTIFACTS_DIR / "_baseline_2010-01-10.parquet"
    )
    events = pd.read_parquet(event_file).copy()
    events["effective_date"] = pd.to_datetime(events["effective_date"]).dt.normalize()
    events = events.sort_values(["effective_date", "event_id"]).reset_index(drop=True)
    baseline = set(pd.read_parquet(baseline_file)["ticker"].astype(str))
    return events, baseline


def all_ever_member_tickers(events: pd.DataFrame, baseline: Iterable[str]) -> list[str]:
    """Sorted union of baseline names plus every ticker mentioned in the event log."""
    tickers = set(map(str, baseline))
    tickers.update(events["ticker"].astype(str))
    if "counterparty_ticker" in events.columns:
        cp = events["counterparty_ticker"].dropna().astype(str)
        tickers.update(cp)
    return sorted(tickers)


def _apply_event(members: set[str], row: pd.Series) -> None:
    action = str(row["action"])
    ticker = str(row["ticker"])
    cp = str(row["counterparty_ticker"]) if pd.notna(row.get("counterparty_ticker")) else None
    if action == "ADD":
        members.add(ticker)
    elif action == "REMOVE":
        members.discard(ticker)
    elif action == "RENAME":
        if cp:
            members.discard(cp)
        members.add(ticker)
    elif action in {"MERGE", "SPINOFF"}:
        members.discard(ticker)


def membership_mask_for_dates(
    events: pd.DataFrame,
    baseline: Iterable[str],
    dates: Sequence[str | pd.Timestamp],
    tickers: Sequence[str],
) -> pd.DataFrame:
    """Boolean [date x ticker] membership mask built by replaying events once.

    Dates are normalized to midnight and evaluated inclusive of all events
    with `effective_date <= date`.
    """
    if len(dates) == 0 or len(tickers) == 0:
        return pd.DataFrame(index=pd.Index([], name="date"), columns=list(tickers), dtype=bool)

    norm_dates = pd.DatetimeIndex(pd.to_datetime(pd.Index(dates))).tz_localize(None).normalize()
    unique_dates = pd.DatetimeIndex(sorted(norm_dates.unique()))
    event_rows = events.sort_values("effective_date").reset_index(drop=True)

    members = set(map(str, baseline))
    out = pd.DataFrame(False, index=unique_dates, columns=list(tickers), dtype=bool)
    event_idx = 0
    n_events = len(event_rows)

    for dt in unique_dates:
        while event_idx < n_events and pd.Timestamp(event_rows.at[event_idx, "effective_date"]) <= dt:
            _apply_event(members, event_rows.iloc[event_idx])
            event_idx += 1
        if members:
            active = [tk for tk in tickers if tk in members]
            if active:
                out.loc[dt, active] = True

    return out.reindex(norm_dates)


def quarantine_root(path: str | Path | None = None) -> Path:
    if path is not None:
        return Path(path).expanduser().resolve()
    return default_paths().quarantine_root


def _quarantine_year_paths(
    ticker: str,
    *,
    root: str | Path | None = None,
    start_date: pd.Timestamp | None = None,
    end_date: pd.Timestamp | None = None,
) -> list[Path]:
    base = quarantine_root(root) / ticker.upper()
    if not base.exists():
        return []
    paths = sorted(base.glob("*.parquet"))
    if start_date is None and end_date is None:
        return paths
    start_year = start_date.year if start_date is not None else None
    end_year = end_date.year if end_date is not None else None
    out: list[Path] = []
    for path in paths:
        try:
            year = int(path.stem)
        except ValueError:
            out.append(path)
            continue
        if start_year is not None and year < start_year:
            continue
        if end_year is not None and year > end_year:
            continue
        out.append(path)
    return out


def load_quarantine_ticker(
    ticker: str,
    *,
    root: str | Path | None = None,
    start_date: str | pd.Timestamp | None = None,
    end_date: str | pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Load a ticker directly from `data/quarantine/market/`."""
    start_ts = _coerce_timestamp(start_date)
    end_ts = _coerce_timestamp(end_date)
    frames = []
    for path in _quarantine_year_paths(
        ticker,
        root=root,
        start_date=start_ts,
        end_date=end_ts,
    ):
        stat = path.stat()
        frames.append(_read_parquet_cached(str(path), stat.st_mtime_ns))
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, axis=0)
    out.index = pd.to_datetime(out.index).tz_localize(None).normalize()
    out = out[~out.index.duplicated(keep="last")].sort_index()
    if start_ts is not None:
        out = out.loc[start_ts:]
    if end_ts is not None:
        out = out.loc[:end_ts]
    return out


def load_quarantine_history(
    tickers: Iterable[str],
    *,
    root: str | Path | None = None,
    start_date: str | pd.Timestamp | None = None,
    end_date: str | pd.Timestamp | None = None,
    min_rows: int = 1,
) -> Dict[str, pd.DataFrame]:
    history: Dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        df = load_quarantine_ticker(
            ticker,
            root=root,
            start_date=start_date,
            end_date=end_date,
        )
        if len(df) >= min_rows:
            history[str(ticker).upper()] = df
    return history


def build_field_panel(
    history: Dict[str, pd.DataFrame],
    field: str = "Adj Close",
) -> pd.DataFrame:
    """Outer-join one field across the loaded ticker history."""
    if not history:
        return pd.DataFrame()
    series = {
        ticker: df[field].astype(float)
        for ticker, df in history.items()
        if field in df.columns
    }
    if not series:
        return pd.DataFrame()
    return pd.DataFrame(series).sort_index()


def mask_panel_by_membership(panel: pd.DataFrame, membership_mask: pd.DataFrame) -> pd.DataFrame:
    """Set non-member dates/tickers to NaN."""
    if panel.empty:
        return panel.copy()
    aligned_mask = membership_mask.reindex(index=panel.index, columns=panel.columns, fill_value=False)
    return panel.where(aligned_mask, np.nan)


def load_pit_field_panel(
    *,
    field: str = "Adj Close",
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
    root: str | Path | None = None,
    events: pd.DataFrame | None = None,
    baseline: Iterable[str] | None = None,
    tickers: Sequence[str] | None = None,
    min_rows: int = 1,
) -> PitFieldPanel:
    """Load a PIT membership-aware field panel from the quarantine store."""
    if events is None or baseline is None:
        events, baseline = load_phase1_membership_artifacts()
    tickers = list(tickers) if tickers is not None else all_ever_member_tickers(events, baseline)
    history = load_quarantine_history(
        tickers,
        root=root,
        start_date=start_date,
        end_date=end_date,
        min_rows=min_rows,
    )
    raw_panel = build_field_panel(history, field=field)
    if raw_panel.empty:
        empty_mask = pd.DataFrame(index=pd.Index([], name="date"), columns=tickers, dtype=bool)
        return PitFieldPanel(
            field=field,
            raw_panel=raw_panel,
            panel=raw_panel.copy(),
            membership_mask=empty_mask,
            availability_mask=empty_mask,
        )
    membership = membership_mask_for_dates(events, baseline, raw_panel.index, list(raw_panel.columns))
    masked = mask_panel_by_membership(raw_panel, membership)
    availability = raw_panel.notna()
    return PitFieldPanel(
        field=field,
        raw_panel=raw_panel,
        panel=masked,
        membership_mask=membership,
        availability_mask=availability,
    )
