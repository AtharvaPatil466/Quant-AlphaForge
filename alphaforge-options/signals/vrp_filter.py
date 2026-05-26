"""VRP signal and entry filter for Substrate #9.

Per SUBSTRATE9_DESIGN.md §1.2 and §4.
VRP_t = VIX_t - realized_vol_t(21d)
Both in annualized percent (VIX units). Entry when VRP > threshold.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ANNUALIZATION = 252.0
REALIZED_VOL_WINDOW = 21       # trading days — matches VIX 30-day window
VIX_DATA_ROOT = Path(__file__).parents[2] / "alphaforge-vix" / "data"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_vix(vix_csv: Path | None = None) -> pd.Series:
    """Load VIX spot close from CBOE CSV. Returns daily Series in percent."""
    if vix_csv is None:
        vix_csv = VIX_DATA_ROOT / "vix_indices" / "VIX.csv"

    df = pd.read_csv(vix_csv, parse_dates=["DATE"])
    df = df.rename(columns={"DATE": "date", "CLOSE": "vix"})
    df["date"] = pd.to_datetime(df["date"], format="%m/%d/%Y")
    df = df.set_index("date").sort_index()
    return df["vix"].rename("vix")


def load_spy(spy_parquet: Path | None = None) -> pd.DataFrame:
    """Load SPY OHLCV from Substrate #7 parquet. Returns adj_close + close."""
    if spy_parquet is None:
        spy_parquet = VIX_DATA_ROOT / "etps" / "spy.parquet"

    df = pd.read_parquet(spy_parquet)
    df.index = pd.to_datetime(df.index)
    df.index.name = "date"
    return df[["close", "adj_close"]]


# ---------------------------------------------------------------------------
# VRP computation
# ---------------------------------------------------------------------------

def compute_log_returns(close: pd.Series) -> pd.Series:
    return np.log(close / close.shift(1))


def compute_realized_vol(
    log_returns: pd.Series,
    window: int = REALIZED_VOL_WINDOW,
) -> pd.Series:
    """Rolling realized vol in annualized percent (VIX units)."""
    daily_std = log_returns.rolling(window, min_periods=window).std()
    return (daily_std * np.sqrt(ANNUALIZATION) * 100.0).rename("realized_vol")


def compute_vrp(vix: pd.Series, realized_vol: pd.Series) -> pd.Series:
    """VRP_t = VIX_t - realized_vol_t. Both in annualized percent.

    Positive when options are 'rich' — the premium-harvest signal.
    """
    aligned = pd.concat([vix, realized_vol], axis=1, sort=True).dropna()
    return (aligned["vix"] - aligned["realized_vol"]).rename("vrp")


def build_vrp_panel(
    vix_csv: Path | None = None,
    spy_parquet: Path | None = None,
) -> pd.DataFrame:
    """Merge VIX, realized vol, and VRP into a single daily panel."""
    vix = load_vix(vix_csv)
    spy = load_spy(spy_parquet)
    log_ret = compute_log_returns(spy["adj_close"])
    rv = compute_realized_vol(log_ret)
    vrp = compute_vrp(vix, rv)

    panel = pd.concat([vix, rv, vrp, spy["adj_close"].rename("spy_close")], axis=1, sort=True)
    panel = panel.dropna(subset=["vrp"])
    return panel


# ---------------------------------------------------------------------------
# Entry filter
# ---------------------------------------------------------------------------

def entry_signal(vrp: pd.Series, threshold: float) -> pd.Series:
    """Boolean Series: True when VRP > threshold (enter the condor)."""
    return (vrp > threshold).rename("entry")


# ---------------------------------------------------------------------------
# Monthly cycle dates helper
# ---------------------------------------------------------------------------

def monthly_cycle_dates(
    panel: pd.DataFrame,
    start: str,
    end: str,
    dte_calendar: int = 30,
    roll_calendar_days_remaining: int = 9,
) -> list[dict]:
    """Generate monthly iron condor cycle entry/exit dates.

    Entry: first trading day of each calendar month in [start, end].
    Expiry: entry_date + dte_calendar calendar days.
    Roll:   last trading day on or before expiry - roll_calendar_days_remaining.

    Returns list of dicts with keys: entry_date, expiry_date, roll_date,
    T_entry (years), T_roll (years).
    """
    idx = panel.loc[start:end].index
    if idx.empty:
        return []

    # First trading day of each month
    monthly_starts = (
        idx.to_series()
        .groupby([idx.year, idx.month])
        .first()
        .values
    )

    cycles = []
    for entry_dt in monthly_starts:
        entry_dt = pd.Timestamp(entry_dt)
        expiry_dt = entry_dt + pd.Timedelta(days=dte_calendar)
        roll_target = expiry_dt - pd.Timedelta(days=roll_calendar_days_remaining)

        # Find last trading day on or before roll_target that is in idx
        roll_candidates = idx[(idx >= entry_dt) & (idx <= roll_target)]
        if roll_candidates.empty:
            continue
        roll_dt = roll_candidates[-1]

        T_entry = dte_calendar / 365.0
        T_roll = max((expiry_dt - roll_dt).days, 1) / 365.0

        # Ensure both entry and roll dates are in the panel
        if entry_dt not in panel.index or roll_dt not in panel.index:
            continue

        cycles.append(
            {
                "entry_date": entry_dt,
                "expiry_date": expiry_dt,
                "roll_date": roll_dt,
                "T_entry": T_entry,
                "T_roll": T_roll,
            }
        )

    return cycles
