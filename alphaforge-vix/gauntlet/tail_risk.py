"""Gate 5 (max-drawdown per stress period) + Gate 6 (CF-Sharpe).

Per VIX_DESIGN.md §5.5 + §5.6 + PHASE2_STRATEGY_SPEC.md §6 (covered-stress-
period rule). Pure-function module — caller passes daily-NAV series, gets
gate decisions back.

Gate 5 — Max-drawdown ≤ 30% in each *covered* stress period (Phase 2 §6
modification of the design's strict 4-of-4: uncovered periods report
NO_DATA, not FAIL).

Gate 6 — Cornish-Fisher Sharpe > 0.5 in both OOS-A and OOS-B independently.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd

from . import stats as stats_mod
from .costs import STRESS_PERIODS


# ---------------------------------------------------------------------------
# Frozen gate thresholds (per VIX_DESIGN.md §5.5 + §5.6)
# ---------------------------------------------------------------------------

MAX_DRAWDOWN_THRESHOLD: float = 0.30   # §5.5 — 30% of entry-period equity
CF_SHARPE_THRESHOLD: float = 0.50      # §5.6 — Cornish-Fisher Sharpe > 0.5


# ---------------------------------------------------------------------------
# Per-stress-period drawdown
# ---------------------------------------------------------------------------

class CoverageStatus(str, Enum):
    COVERED = "covered"
    NO_DATA = "no_data"
    PARTIAL = "partial"  # window starts mid-period (e.g. SVXY launches mid-2011)


@dataclass(frozen=True)
class StressPeriodResult:
    name: str
    window_start: pd.Timestamp
    window_end: pd.Timestamp
    effective_start: pd.Timestamp | None
    effective_end: pd.Timestamp | None
    n_days: int
    coverage: CoverageStatus
    entry_nav: float | None
    trough_nav: float | None
    max_drawdown: float | None     # positive number, e.g. 0.30 = 30%
    drawdown_passes_gate: bool | None  # None if not covered

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "window_start": str(self.window_start.date()),
            "window_end": str(self.window_end.date()),
            "effective_start": (str(self.effective_start.date())
                                 if self.effective_start else None),
            "effective_end": (str(self.effective_end.date())
                               if self.effective_end else None),
            "n_days": self.n_days,
            "coverage": self.coverage.value,
            "entry_nav": self.entry_nav,
            "trough_nav": self.trough_nav,
            "max_drawdown": self.max_drawdown,
            "drawdown_passes_gate": self.drawdown_passes_gate,
        }


def evaluate_stress_period(
    nav_series: pd.Series,
    period_name: str,
    period_start: pd.Timestamp,
    period_end: pd.Timestamp,
    threshold: float = MAX_DRAWDOWN_THRESHOLD,
) -> StressPeriodResult:
    """Compute peak-to-trough drawdown within a single stress window.

    Per PHASE2_STRATEGY_SPEC.md §6:
      • If `nav_series` has NO observations in the window → NO_DATA.
      • If first observation is later than `period_start` → PARTIAL.
      • Otherwise → COVERED.

    The drawdown is measured as `1 − trough_nav / entry_nav` where
    `entry_nav` is the NAV at the start of the effective window.
    """
    sliced = nav_series[(nav_series.index >= period_start)
                        & (nav_series.index <= period_end)].dropna()
    if sliced.empty:
        return StressPeriodResult(
            name=period_name,
            window_start=period_start, window_end=period_end,
            effective_start=None, effective_end=None,
            n_days=0, coverage=CoverageStatus.NO_DATA,
            entry_nav=None, trough_nav=None,
            max_drawdown=None, drawdown_passes_gate=None,
        )
    effective_start = sliced.index.min()
    effective_end = sliced.index.max()
    coverage = (CoverageStatus.COVERED if effective_start == period_start
                else CoverageStatus.PARTIAL)
    # Permissive: any data-day within 5 trading days of period_start counts
    # as full coverage (since stress periods are calendar windows but NAV
    # is on business days).
    if effective_start <= period_start + pd.Timedelta(days=5):
        coverage = CoverageStatus.COVERED
    entry_nav = float(sliced.iloc[0])
    # Trough within the window, measured from entry.
    rolling_max = sliced.cummax()
    drawdown_path = 1.0 - sliced / rolling_max
    # We measure FROM entry, not from rolling peak — the gate's intent is
    # "loss vs equity entering the period."
    losses_from_entry = 1.0 - sliced / entry_nav
    max_dd = float(losses_from_entry.max())
    trough_nav = float(sliced[losses_from_entry.idxmax()])
    passes = max_dd <= threshold
    return StressPeriodResult(
        name=period_name,
        window_start=period_start, window_end=period_end,
        effective_start=effective_start, effective_end=effective_end,
        n_days=int(len(sliced)), coverage=coverage,
        entry_nav=entry_nav, trough_nav=trough_nav,
        max_drawdown=max_dd, drawdown_passes_gate=passes,
    )


# ---------------------------------------------------------------------------
# Gate 5 — overall verdict (per Phase 2 spec §6 modification)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Gate5Result:
    per_period: tuple[StressPeriodResult, ...]
    n_covered: int
    n_covered_passing: int
    passes: bool
    rationale: str

    def to_dict(self) -> dict:
        return {
            "per_period": [p.to_dict() for p in self.per_period],
            "n_covered": self.n_covered,
            "n_covered_passing": self.n_covered_passing,
            "passes": self.passes,
            "rationale": self.rationale,
        }


def evaluate_gate5(
    nav_series: pd.Series,
    threshold: float = MAX_DRAWDOWN_THRESHOLD,
) -> Gate5Result:
    """Evaluate Gate 5 across all 4 pre-committed stress periods.

    Pass criterion (Phase 2 §6 modification of §5.5):
        ALL covered periods must pass max-DD ≤ threshold. Uncovered periods
        are excluded from the denominator (NOT counted as either pass or
        fail). A strategy with zero covered periods cannot pass Gate 5 —
        no stress evidence to evaluate against.
    """
    results: list[StressPeriodResult] = []
    for name, start, end in STRESS_PERIODS:
        results.append(evaluate_stress_period(nav_series, name, start, end,
                                              threshold=threshold))
    covered = [r for r in results
               if r.coverage in (CoverageStatus.COVERED, CoverageStatus.PARTIAL)]
    passing = [r for r in covered if r.drawdown_passes_gate]
    if not covered:
        return Gate5Result(
            per_period=tuple(results),
            n_covered=0, n_covered_passing=0,
            passes=False,
            rationale=("Zero covered stress periods — no max-drawdown evidence. "
                       "Gate 5 cannot pass under the §6 covered-only rule."),
        )
    n_cov = len(covered)
    n_pass = len(passing)
    passes = n_pass == n_cov
    rationale = (f"Covered stress periods: {n_pass}/{n_cov} pass "
                 f"({', '.join(r.name for r in passing)} pass; "
                 f"{', '.join(r.name for r in covered if r not in passing) or 'none'} fail)."
                 if n_cov > 0 else "No stress evidence.")
    return Gate5Result(
        per_period=tuple(results),
        n_covered=n_cov, n_covered_passing=n_pass,
        passes=passes,
        rationale=rationale,
    )


# ---------------------------------------------------------------------------
# Gate 6 — Cornish-Fisher Sharpe (in both OOS-A and OOS-B)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Gate6Result:
    cf_sharpe_oos_a: float
    cf_sharpe_oos_b: float
    passes_oos_a: bool
    passes_oos_b: bool
    passes: bool

    def to_dict(self) -> dict:
        return {
            "cf_sharpe_oos_a": self.cf_sharpe_oos_a,
            "cf_sharpe_oos_b": self.cf_sharpe_oos_b,
            "passes_oos_a": self.passes_oos_a,
            "passes_oos_b": self.passes_oos_b,
            "passes": self.passes,
        }


def evaluate_gate6(
    returns_oos_a: pd.Series,
    returns_oos_b: pd.Series,
    threshold: float = CF_SHARPE_THRESHOLD,
) -> Gate6Result:
    """Evaluate Gate 6: CF-Sharpe > threshold INDEPENDENTLY in OOS-A + OOS-B."""
    cf_a = stats_mod.cornish_fisher_sharpe(returns_oos_a)
    cf_b = stats_mod.cornish_fisher_sharpe(returns_oos_b)
    p_a = np.isfinite(cf_a) and cf_a > threshold
    p_b = np.isfinite(cf_b) and cf_b > threshold
    return Gate6Result(
        cf_sharpe_oos_a=float(cf_a),
        cf_sharpe_oos_b=float(cf_b),
        passes_oos_a=bool(p_a),
        passes_oos_b=bool(p_b),
        passes=bool(p_a and p_b),
    )
