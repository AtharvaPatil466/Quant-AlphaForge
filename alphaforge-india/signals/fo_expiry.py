"""F&O expiry event-study signal.

Per research/INDIA_DESIGN.md §4.3 and §8.3:

    4 pre-committed trials:
        Pre-expiry window × Post-expiry window = {3, 5} × {3, 5}

    Signal logic:
        1. Identify monthly expiry dates from the F&O expiry calendar.
        2. Around each expiry, compute average return of all Nifty 500
           stocks in the pre-expiry and post-expiry windows.
        3. Event-study IC: is the pre-expiry return predictive of the
           post-expiry return?

    Phase 1C pass criterion (§8.3):
        - Mean pre-expiry OR post-expiry return statistically significant
          at p < 0.05 (t-test on the event-study return distribution).
        - Consistent sign across at least 70% of individual expiry events.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

log = logging.getLogger("india.signals.fo_expiry")


# ---------------------------------------------------------------------------
# Trial enumeration
# ---------------------------------------------------------------------------

PRE_EXPIRY_WINDOWS = (3, 5)
POST_EXPIRY_WINDOWS = (3, 5)


@dataclass
class FOExpiryTrial:
    """One F&O expiry event-study trial."""
    pre_window: int   # trading days before expiry
    post_window: int  # trading days after expiry

    @property
    def trial_name(self) -> str:
        return f"fo_expiry_pre{self.pre_window}_post{self.post_window}"


def enumerate_trials() -> list[FOExpiryTrial]:
    """Return all 4 pre-committed F&O expiry trials."""
    return [
        FOExpiryTrial(pre_window=pre, post_window=post)
        for pre in PRE_EXPIRY_WINDOWS
        for post in POST_EXPIRY_WINDOWS
    ]


# ---------------------------------------------------------------------------
# Event window returns
# ---------------------------------------------------------------------------

def _trading_days_around_date(
    all_dates: pd.DatetimeIndex | np.ndarray,
    anchor: date,
    n_before: int,
    n_after: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Find the n_before trading days before and n_after after `anchor`.

    Returns (pre_dates, post_dates) as arrays of datetime-like values.
    `anchor` itself is NOT included in either window.
    """
    all_d = pd.DatetimeIndex(all_dates).sort_values()
    anchor_ts = pd.Timestamp(anchor)

    # Pre-window: the n_before dates strictly before anchor
    pre_mask = all_d < anchor_ts
    pre_dates = all_d[pre_mask][-n_before:]

    # Post-window: the n_after dates strictly after anchor
    post_mask = all_d > anchor_ts
    post_dates = all_d[post_mask][:n_after]

    return pre_dates.values, post_dates.values


def compute_window_returns(
    close_df: pd.DataFrame,
    expiry_dates: list[date],
    pre_window: int,
    post_window: int,
) -> pd.DataFrame:
    """Compute pre-expiry and post-expiry returns for each expiry event.

    Parameters
    ----------
    close_df : pd.DataFrame
        Columns = symbols, index = dates (DatetimeIndex), values = close
        prices.
    expiry_dates : list[date]
        Monthly expiry dates from the F&O calendar.
    pre_window : int
        Number of trading days before expiry.
    post_window : int
        Number of trading days after expiry.

    Returns
    -------
    pd.DataFrame
        Columns: expiry_date, pre_return, post_return, n_stocks,
                 pre_sign_positive (fraction of stocks with positive
                 pre-window return).
    """
    all_dates = close_df.index
    daily_returns = close_df.pct_change()
    results: list[dict[str, Any]] = []

    for exp_date in expiry_dates:
        pre_dates, post_dates = _trading_days_around_date(
            all_dates, exp_date, pre_window, post_window,
        )
        if len(pre_dates) < pre_window or len(post_dates) < post_window:
            log.debug("Skipping expiry %s: insufficient window dates", exp_date)
            continue

        # Cross-sectional average return over window
        pre_rets = daily_returns.loc[pre_dates].sum(axis=0)  # per-stock cumulative
        post_rets = daily_returns.loc[post_dates].sum(axis=0)

        # Drop NaN stocks
        valid = pre_rets.dropna().index.intersection(post_rets.dropna().index)
        if len(valid) < 10:
            log.debug("Skipping expiry %s: only %d valid stocks", exp_date, len(valid))
            continue

        pre_mean = float(pre_rets[valid].mean())
        post_mean = float(post_rets[valid].mean())
        n_stocks = len(valid)
        pre_sign_frac = float((pre_rets[valid] > 0).mean())
        post_sign_frac = float((post_rets[valid] > 0).mean())

        results.append({
            "expiry_date": exp_date,
            "pre_return": pre_mean,
            "post_return": post_mean,
            "n_stocks": n_stocks,
            "pre_sign_positive_frac": pre_sign_frac,
            "post_sign_positive_frac": post_sign_frac,
        })

    return pd.DataFrame(results)


# ---------------------------------------------------------------------------
# Event-study statistical tests
# ---------------------------------------------------------------------------

@dataclass
class EventStudyResult:
    """Results for one F&O expiry event-study trial."""
    trial_name: str
    n_events: int
    pre_return_mean: float
    pre_return_t_stat: float
    pre_return_p_value: float
    pre_sign_consistency: float  # fraction of events with same sign as mean
    post_return_mean: float
    post_return_t_stat: float
    post_return_p_value: float
    post_sign_consistency: float
    passed_phase1: bool

    def summary(self) -> str:
        pre_pass = self.pre_return_p_value < 0.05 and self.pre_sign_consistency >= 0.70
        post_pass = self.post_return_p_value < 0.05 and self.post_sign_consistency >= 0.70
        return (
            f"{self.trial_name}: n={self.n_events}, "
            f"pre_mean={self.pre_return_mean:.4f} t={self.pre_return_t_stat:.2f} "
            f"p={self.pre_return_p_value:.4f} sign={self.pre_sign_consistency:.1%}"
            f"{'✓' if pre_pass else '✗'} | "
            f"post_mean={self.post_return_mean:.4f} t={self.post_return_t_stat:.2f} "
            f"p={self.post_return_p_value:.4f} sign={self.post_sign_consistency:.1%}"
            f"{'✓' if post_pass else '✗'}"
            f" → {'PASS' if self.passed_phase1 else 'FAIL'}"
        )


def run_event_study(
    window_returns: pd.DataFrame,
    trial: FOExpiryTrial,
) -> EventStudyResult:
    """Run the Phase 1C event-study statistical test on window returns.

    Pass criterion (§8.3):
        - Mean pre-expiry OR post-expiry return significant at p < 0.05
        - Consistent sign across ≥ 70% of individual expiry events
    """
    from scipy import stats

    n = len(window_returns)
    if n < 3:
        return EventStudyResult(
            trial_name=trial.trial_name,
            n_events=n,
            pre_return_mean=0.0, pre_return_t_stat=0.0,
            pre_return_p_value=1.0, pre_sign_consistency=0.0,
            post_return_mean=0.0, post_return_t_stat=0.0,
            post_return_p_value=1.0, post_sign_consistency=0.0,
            passed_phase1=False,
        )

    pre_rets = window_returns["pre_return"].values
    post_rets = window_returns["post_return"].values

    # t-test (two-sided, testing if mean != 0)
    pre_t, pre_p = stats.ttest_1samp(pre_rets, 0.0)
    post_t, post_p = stats.ttest_1samp(post_rets, 0.0)

    # Sign consistency: fraction of events with same sign as mean
    pre_mean = float(pre_rets.mean())
    post_mean = float(post_rets.mean())

    if pre_mean >= 0:
        pre_sign_consist = float((pre_rets >= 0).mean())
    else:
        pre_sign_consist = float((pre_rets < 0).mean())

    if post_mean >= 0:
        post_sign_consist = float((post_rets >= 0).mean())
    else:
        post_sign_consist = float((post_rets < 0).mean())

    # Pass if EITHER pre or post passes both sub-criteria
    pre_passes = (pre_p < 0.05) and (pre_sign_consist >= 0.70)
    post_passes = (post_p < 0.05) and (post_sign_consist >= 0.70)
    passed = pre_passes or post_passes

    return EventStudyResult(
        trial_name=trial.trial_name,
        n_events=n,
        pre_return_mean=pre_mean,
        pre_return_t_stat=float(pre_t),
        pre_return_p_value=float(pre_p),
        pre_sign_consistency=pre_sign_consist,
        post_return_mean=post_mean,
        post_return_t_stat=float(post_t),
        post_return_p_value=float(post_p),
        post_sign_consistency=post_sign_consist,
        passed_phase1=passed,
    )


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

def run_all_trials(
    close_df: pd.DataFrame,
    expiry_dates: list[date],
) -> list[EventStudyResult]:
    """Run all 4 F&O expiry trials and return results."""
    results: list[EventStudyResult] = []
    for trial in enumerate_trials():
        window_rets = compute_window_returns(
            close_df, expiry_dates,
            pre_window=trial.pre_window,
            post_window=trial.post_window,
        )
        result = run_event_study(window_rets, trial)
        results.append(result)
        log.info(result.summary())
    return results
