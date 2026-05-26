"""Realized-vol panels from SPY close prices.

Per `VIX_DESIGN.md` §2.3. Computes daily log returns and 10/21/63-day
rolling realized volatility (annualized). The 21-day series is the
primary VRP input; the 10-day and 63-day series are alternate-lookback
variants in the trial set (§4.1).

Includes a validator that checks the 5 known volatility-event spikes
listed in §2.3 are present in the computed series. Phase 0 cert
treats a failed validation as a Gate-3 FAIL.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger("vix.ingest.realized_vol")

ANNUALIZATION = 252.0


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_log_returns(close: pd.Series) -> pd.Series:
    """Daily log returns from a close-price series. First value is NaN."""
    close = close.astype(float)
    return np.log(close / close.shift(1))


def compute_realized_vol(
    log_returns: pd.Series,
    window: int,
    annualize: float = ANNUALIZATION,
    min_periods: int | None = None,
) -> pd.Series:
    """Rolling realized volatility, annualized, **in percent** (VIX units).

    Output is on the same scale as the VIX index — e.g., 20.0 means 20%
    annualized vol — so `VRP = VIX − realized_vol` per §1.2 evaluates with
    consistent units. Industry convention; mirrors how CBOE quotes VIX.
    """
    if min_periods is None:
        min_periods = window
    daily_std = log_returns.rolling(window, min_periods=min_periods).std()
    return daily_std * np.sqrt(annualize) * 100.0


def build_spy_panel(spy_close: pd.Series) -> pd.DataFrame:
    """SPY → wide panel of (log_return, realized_vol_10, _21, _63).

    Index: date. Pre-window rows are NaN for the rolling cols.
    """
    log_ret = compute_log_returns(spy_close)
    return pd.DataFrame({
        "log_return": log_ret,
        "realized_vol_10": compute_realized_vol(log_ret, 10),
        "realized_vol_21": compute_realized_vol(log_ret, 21),
        "realized_vol_63": compute_realized_vol(log_ret, 63),
    })


# ---------------------------------------------------------------------------
# Validation — 5 known spike events from VIX_DESIGN.md §2.3
# ---------------------------------------------------------------------------

@dataclass
class SpikeCheck:
    name: str
    date_window: tuple[date, date]  # inclusive
    metric: str                       # column in spy_panel
    op: str                           # ">", "<", "abs>", "max>", etc.
    threshold: float


# Per §2.3 — the SPY series must reproduce these. Window is permissive
# (a few days around the event) because the exact peak can fall on the
# event date or the next session.
KNOWN_SPIKES: tuple[SpikeCheck, ...] = (
    SpikeCheck(
        name="2008_lehman",
        date_window=(date(2008, 9, 15), date(2008, 11, 30)),
        metric="realized_vol_21", op="max>", threshold=60.0,
    ),
    SpikeCheck(
        name="2010_flash_crash",
        # SPY May 6 2010 closed at -3.3% (intraday -9% but recovered). Daily
        # close threshold is what we can observe in OHLC data.
        date_window=(date(2010, 5, 5), date(2010, 5, 7)),
        metric="log_return", op="min<", threshold=-0.030,
    ),
    SpikeCheck(
        name="2015_china_devaluation",
        date_window=(date(2015, 8, 17), date(2015, 9, 30)),
        metric="realized_vol_21", op="max>", threshold=20.0,
    ),
    SpikeCheck(
        name="2018_volmageddon",
        date_window=(date(2018, 2, 1), date(2018, 3, 15)),
        metric="realized_vol_21", op="max>", threshold=20.0,
    ),
    SpikeCheck(
        name="2020_covid_monday",
        date_window=(date(2020, 3, 9), date(2020, 3, 20)),
        metric="log_return", op="min<", threshold=-0.10,
    ),
)


@dataclass
class SpikeValidationResult:
    name: str
    passed: bool
    observed: float | None
    summary: str


@dataclass
class ValidationReport:
    all_passed: bool
    n_passed: int
    n_total: int
    results: list[SpikeValidationResult] = field(default_factory=list)


def _evaluate_check(
    panel: pd.DataFrame, check: SpikeCheck,
) -> SpikeValidationResult:
    sliced = panel[
        (panel.index >= pd.Timestamp(check.date_window[0]))
        & (panel.index <= pd.Timestamp(check.date_window[1]))
    ]
    if sliced.empty or check.metric not in sliced.columns:
        return SpikeValidationResult(
            name=check.name, passed=False, observed=None,
            summary=f"no data in window [{check.date_window[0]} .. "
                    f"{check.date_window[1]}] for {check.metric}",
        )
    s = sliced[check.metric].dropna()
    if s.empty:
        return SpikeValidationResult(
            name=check.name, passed=False, observed=None,
            summary="all-NaN in window",
        )
    if check.op == "max>":
        observed = float(s.max())
        passed = observed > check.threshold
    elif check.op == "min<":
        observed = float(s.min())
        passed = observed < check.threshold
    elif check.op == ">":
        observed = float(s.iloc[-1])
        passed = observed > check.threshold
    elif check.op == "<":
        observed = float(s.iloc[-1])
        passed = observed < check.threshold
    elif check.op == "abs>":
        observed = float(s.abs().max())
        passed = observed > check.threshold
    else:
        return SpikeValidationResult(
            name=check.name, passed=False, observed=None,
            summary=f"unknown op {check.op!r}",
        )
    return SpikeValidationResult(
        name=check.name, passed=passed, observed=observed,
        summary=(f"{check.metric} {check.op} {check.threshold} "
                 f"→ observed {observed:.4f} "
                 f"({'PASS' if passed else 'FAIL'})"),
    )


def validate_spike_events(
    panel: pd.DataFrame, checks: tuple[SpikeCheck, ...] = KNOWN_SPIKES,
) -> ValidationReport:
    results = [_evaluate_check(panel, c) for c in checks]
    n_pass = sum(1 for r in results if r.passed)
    return ValidationReport(
        all_passed=(n_pass == len(checks)),
        n_passed=n_pass, n_total=len(checks),
        results=results,
    )
