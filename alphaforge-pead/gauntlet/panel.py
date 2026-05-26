"""Announcement-event panel builder for PEAD.

Joins the EDGAR EPS shards (`data/edgar_eps/by_cik/CIK*.parquet`) with
the OHLCV store (`data/quarantine/market/{TICKER}/*.parquet`) to produce
one row per firm-announcement.

**2026-05-17 SEMANTIC NOTE (PEAD_DESIGN.md §2.2 addendum):** the canonical
period identifier is `period_end` (date), NOT `(fy, fp)`. EDGAR's `fp`
field reflects the FILING form (e.g., "FY" for any value reported in a
10-K — including the four quarterly values that 10-K restates), so
`(fy, fp)` is not unique per period. Rows are filtered to
`period_kind == "quarterly"` (90-day duration), which excludes the
cumulative-YTD entries the SEC API returns alongside true quarterly
values.

Announcement time = the `filed` timestamp of the ORIGINAL filing (the
earliest-filed row for that period_end). Subsequent restatements feed
SUE via `value_as_of` at later as-of-dates but do not generate new
announcement rows.

Output schema:
    cik, ticker, period_end, fy, fp, announcement_ts, sue,
    fwd_return_5, fwd_return_21, fwd_return_42, fwd_return_63, fwd_return_84

fy and fp are reported for audit ONLY — they reflect the original
filing's tagging and are not used as join keys.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd
import pyarrow.parquet as pq

from extractors.companyfacts import value_as_of, _pad_cik
from .sue import compute_sue


log = logging.getLogger(__name__)


HOLDING_HORIZONS = (5, 21, 42, 63, 84)
QUARTERLY_KIND = "quarterly"  # canonical period_kind for Phase 1


# --- types ----------------------------------------------------------------


@dataclass(slots=True)
class AnnouncementRow:
    cik: int
    ticker: str
    period_end: date         # CANONICAL key (PEAD_DESIGN.md §2.2 addendum 2026-05-17)
    fy: int                  # FROM FILING — audit only
    fp: str                  # FROM FILING — audit only
    announcement_ts: datetime
    sue: float
    fwd_returns: dict[int, float]


# --- internal helpers -----------------------------------------------------


def _load_shard(edgar_root: Path, cik: int) -> Optional[pd.DataFrame]:
    path = edgar_root / "by_cik" / f"CIK{_pad_cik(cik)}.parquet"
    if not path.exists():
        return None
    return pq.read_table(path).to_pandas()


def _filter_quarterly(shard: pd.DataFrame) -> pd.DataFrame:
    """Keep only rows where period_kind=='quarterly' (~90-day duration).

    Excludes YTD-cumulative rows and the annual FY value (which is a
    sum, not a single-quarter EPS). Without this filter, panel rows
    would mix quarterly and cumulative values for SUE — corrupt input.
    """
    if "period_kind" not in shard.columns:
        # Backward compatibility: shards written before the 2026-05-17
        # parser fix lack this column. Fall back to deriving from
        # start_date/end_date in-memory.
        durations = (pd.to_datetime(shard["end_date"]) - pd.to_datetime(shard["start_date"])).dt.days
        return shard[(durations >= 85) & (durations <= 95)]
    return shard[shard["period_kind"] == QUARTERLY_KIND]


def _original_filings_per_period(quarterly: pd.DataFrame) -> pd.DataFrame:
    """For each period_end, return the ORIGINAL filing (earliest filed).

    Restatements (10-Q/A, 10-K/A) share the same period_end and are
    consumed via value_as_of at later as-of-dates; they don't generate
    new announcement events.
    """
    if quarterly.empty:
        return quarterly
    return (
        quarterly.sort_values("filed")
                 .groupby("period_end", as_index=False)
                 .first()
    )


def _load_ohlcv(ohlcv_root: Path, ticker: str) -> Optional[pd.DataFrame]:
    d = ohlcv_root / ticker
    if not d.exists():
        return None
    files = sorted(d.glob("*.parquet"))
    if not files:
        return None
    frames = [pq.read_table(p).to_pandas() for p in files]
    df = pd.concat(frames, ignore_index=False)
    df.columns = df.columns.str.lower()
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"]).dt.date
        df = df.set_index("date")
    elif df.index.name is not None and df.index.name.lower() == "date":
        df.index = pd.to_datetime(df.index).date
    df = df.sort_index()
    if "close" not in df.columns:
        return None
    df = df[~df.index.duplicated(keep="last")]
    return df


def _fwd_returns(close: pd.Series, anchor_date: date, horizons: Iterable[int]) -> dict[int, float]:
    import math as _math
    import numpy as _np

    dates_after = close.index[close.index >= anchor_date]
    if len(dates_after) == 0:
        return {K: float("nan") for K in horizons}
    t_date = dates_after[0]
    t_loc = close.index.get_loc(t_date)
    p_t = close.iloc[t_loc]
    out: dict[int, float] = {}
    for K in horizons:
        tk_loc = t_loc + K
        if tk_loc >= len(close):
            out[K] = float("nan")
            continue
        p_tk = close.iloc[tk_loc]
        if p_t <= 0 or p_tk <= 0 or not (_math.isfinite(p_t) and _math.isfinite(p_tk)):
            out[K] = float("nan")
        else:
            out[K] = float(_np.log(p_tk / p_t))
    return out


# --- public builder -------------------------------------------------------


def build_panel_for_firm(
    edgar_root: Path,
    ohlcv_root: Path,
    cik: int,
    ticker: str,
    horizons: Iterable[int] = HOLDING_HORIZONS,
) -> list[AnnouncementRow]:
    """Build all PEAD announcement rows for one firm.

    Steps:
      1. Load the firm's EPS shard.
      2. Filter to period_kind == "quarterly".
      3. Identify the ORIGINAL filing per period_end.
      4. For each original filing, build the eps-by-period-end dict
         known at announcement time via value_as_of, compute SUE.
      5. Compute fwd_returns over the OHLCV close series.
    """
    shard = _load_shard(edgar_root, cik)
    if shard is None or shard.empty:
        return []
    quarterly = _filter_quarterly(shard)
    if quarterly.empty:
        return []
    ohlcv = _load_ohlcv(ohlcv_root, ticker)
    if ohlcv is None or ohlcv.empty:
        return []
    close = ohlcv["close"]
    shard_path = edgar_root / "by_cik" / f"CIK{_pad_cik(cik)}.parquet"

    originals = _original_filings_per_period(quarterly)
    all_period_ends = sorted(set(quarterly["period_end"]))

    rows: list[AnnouncementRow] = []
    for _, ann in originals.iterrows():
        period_end: date = ann["period_end"]
        announcement_ts: datetime = ann["filed"]
        if announcement_ts.tzinfo is None:
            announcement_ts = announcement_ts.replace(tzinfo=timezone.utc)

        # Build the eps-by-period-end dict known at announcement time.
        eps_by_period_end: dict[date, float] = {}
        for pe in all_period_ends:
            v = value_as_of(shard_path, ticker, pe, announcement_ts)
            if v is not None:
                eps_by_period_end[pe] = v

        sue = compute_sue(eps_by_period_end, focal=period_end)

        anchor = announcement_ts.date()
        fwd = _fwd_returns(close, anchor, horizons)

        rows.append(AnnouncementRow(
            cik=cik,
            ticker=ticker,
            period_end=period_end,
            fy=int(ann["fy"]),
            fp=str(ann["fp"]),
            announcement_ts=announcement_ts,
            sue=sue,
            fwd_returns=fwd,
        ))
    return rows


def panel_to_dataframe(rows: list[AnnouncementRow],
                       horizons: Iterable[int] = HOLDING_HORIZONS) -> pd.DataFrame:
    """Flatten AnnouncementRow list into a DataFrame for the gauntlet."""
    horizons = tuple(horizons)
    records = []
    for r in rows:
        rec = {
            "cik": r.cik,
            "ticker": r.ticker,
            "period_end": r.period_end,
            "fy": r.fy,
            "fp": r.fp,
            "announcement_ts": r.announcement_ts,
            "sue": r.sue,
        }
        for K in horizons:
            rec[f"fwd_return_{K}"] = r.fwd_returns.get(K, float("nan"))
        records.append(rec)
    return pd.DataFrame.from_records(records)
