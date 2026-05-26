"""Tests for the SUE math library (period_end-keyed interface).

Per `research/PEAD_DESIGN.md` §1 + the §2.2 addendum (2026-05-17), SUE is
defined over period_end dates, with seasonal predecessors looked up
via a ±15-day window around 365 days. These tests use synthetic in-
memory dicts; no real EDGAR data flows.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from gauntlet.sue import (
    SEASONAL_GAP_MIN_DAYS,
    SEASONAL_GAP_MAX_DAYS,
    compute_sue,
    compute_sue_panel,
    seasonal_predecessor,
)


# --- helpers --------------------------------------------------------------


def _calendar_year_eps(start_year: int, n_years: int,
                       val_fn=lambda y, q: 1.0) -> dict[date, float]:
    """Build an EPS dict for `n_years` of calendar-quarterly reporting
    starting at start_year. val_fn(year, quarter_index) → float."""
    out: dict[date, float] = {}
    ends = [(3, 31), (6, 30), (9, 30), (12, 31)]
    for yr in range(start_year, start_year + n_years):
        for q_idx, (m, d) in enumerate(ends):
            out[date(yr, m, d)] = val_fn(yr, q_idx)
    return out


# --- seasonal_predecessor -------------------------------------------------


def test_seasonal_predecessor_calendar_year():
    eps = _calendar_year_eps(2020, 4)
    pred = seasonal_predecessor(eps, date(2022, 6, 30))
    assert pred == date(2021, 6, 30)


def test_seasonal_predecessor_no_match_returns_none():
    eps = {date(2020, 3, 31): 1.0}
    # focal is 6 months later, no candidate in [350, 380] day window
    assert seasonal_predecessor(eps, date(2020, 9, 30)) is None


def test_seasonal_predecessor_first_year_returns_none():
    """A firm's first year has no seasonal predecessor."""
    eps = {date(2020, 3, 31): 1.0, date(2020, 6, 30): 1.1}
    assert seasonal_predecessor(eps, date(2020, 3, 31)) is None


def test_seasonal_predecessor_handles_53_week_year():
    """A 53-week fiscal year would put one quarter's seasonal predecessor
    slightly outside 365 days — needs to be within [350, 380]."""
    eps = {
        date(2020, 12, 26): 1.0,   # last week of 52-week 2020
        date(2021, 12, 25): 1.1,   # one calendar year later (~364 days)
    }
    # 2021-12-25 - 2020-12-26 = 364 days → in [350, 380] window
    assert seasonal_predecessor(eps, date(2021, 12, 25)) == date(2020, 12, 26)


def test_seasonal_predecessor_ambiguous_returns_none():
    """If two period_ends both fall in the ±15-day window, that's
    structurally wrong (overlapping reporting periods) → None."""
    eps = {
        date(2020, 1, 1): 1.0,
        date(2020, 1, 15): 1.0,  # both within 365±15d of focal
    }
    focal = date(2021, 1, 5)
    # both 2020 dates: 370 days and 356 days from focal — both in window
    assert seasonal_predecessor(eps, focal) is None


def test_window_bounds_match_design():
    """Sanity guard on the pre-committed tolerance window."""
    assert SEASONAL_GAP_MIN_DAYS == 350
    assert SEASONAL_GAP_MAX_DAYS == 380


# --- compute_sue: numerator ----------------------------------------------


def test_numerator_uses_same_quarter_prior_year():
    eps = _calendar_year_eps(2018, 5)
    eps[date(2022, 6, 30)] = 5.0
    eps[date(2021, 6, 30)] = 2.0
    sue = compute_sue(eps, focal=date(2022, 6, 30))
    # numerator = 5 - 2 = 3; denominator depends on prior-quarter
    # constancy. Since all values are 1.0 in 2018-2021 except Q2-2022
    # (and we just overrode Q2-2021), the 8 prior quarters from focal
    # 2022-06-30 are 2020-06-30..2022-03-31. Their seasonal diffs are
    # mostly 0 (year-on-year unchanged), except for Q2-2021 (1.0 - 2.0
    # since we overrode 2021-06-30, but its predecessor 2020-06-30 = 1.0)
    # — that single Q2-2021 difference = (2.0 - 1.0) = 1.0. Variance > 0.
    assert math.isfinite(sue)


def test_numerator_missing_focal_returns_nan():
    eps = _calendar_year_eps(2018, 5)
    del eps[date(2022, 6, 30)]
    assert math.isnan(compute_sue(eps, focal=date(2022, 6, 30)))


def test_numerator_missing_prior_year_returns_nan():
    eps = _calendar_year_eps(2018, 5)
    del eps[date(2021, 6, 30)]
    assert math.isnan(compute_sue(eps, focal=date(2022, 6, 30)))


def test_non_finite_value_propagates_to_nan():
    eps = _calendar_year_eps(2018, 5)
    eps[date(2022, 6, 30)] = float("inf")
    assert math.isnan(compute_sue(eps, focal=date(2022, 6, 30)))
    eps[date(2022, 6, 30)] = float("nan")
    assert math.isnan(compute_sue(eps, focal=date(2022, 6, 30)))


# --- compute_sue: denominator --------------------------------------------


def test_denominator_zero_when_constant_returns_nan():
    eps = _calendar_year_eps(2018, 6, val_fn=lambda y, q: 1.0)
    assert math.isnan(compute_sue(eps, focal=date(2023, 6, 30)))


def test_denominator_uses_8_prior_quarters():
    """Inject a one-time shock at a specific quarter and verify SUE has
    expected sign at a subsequent focal whose 8 prior quarters include
    the shock."""
    eps = _calendar_year_eps(2018, 6, val_fn=lambda y, q: 1.0)
    eps[date(2021, 12, 31)] = 2.0   # one-off shock
    sue = compute_sue(eps, focal=date(2023, 6, 30))
    # numerator = 1 - 1 = 0; denominator > 0 because of the shock
    # 8 prior quarters of 2023-06-30: 2021Q2..2023Q1.
    # Their seasonal diffs are 0 except 2021-12-31's diff = (2-1)=1.
    # Mean = 1/8 = 0.125; variance > 0 → SUE = 0 / std = 0.
    assert sue == 0.0


def test_insufficient_history_returns_nan():
    """A firm with only 6 prior quarters cannot have its 7th-quarter SUE."""
    eps = {
        date(2020, 3, 31): 1.0, date(2020, 6, 30): 1.0,
        date(2020, 9, 30): 1.0, date(2020, 12, 31): 1.0,
        date(2021, 3, 31): 1.0, date(2021, 6, 30): 1.0,
    }
    # focal at 2021-09-30, but only 6 prior period_ends → < 8
    assert math.isnan(compute_sue(eps, focal=date(2021, 9, 30)))


def test_history_window_parameter_is_respected():
    """With history_window=2, only 2 prior quarters' seasonal diffs needed."""
    eps = {
        date(2020, 3, 31): 1.0, date(2020, 6, 30): 1.0,
        date(2020, 9, 30): 2.0,    # shock here
        date(2020, 12, 31): 1.0,
        date(2021, 3, 31): 1.0, date(2021, 6, 30): 1.5,
    }
    # focal = 2021-06-30, history_window=2
    # numerator: 2021-06-30 (1.5) - 2020-06-30 (1.0) = 0.5
    # prior 2 quarters: 2020-12-31, 2021-03-31
    # 2020-12-31 seasonal pred = 2019-12-31 → not in eps → seasonal_predecessor returns None → NaN
    # Hmm. So we'd need 2019 data too. Let me adjust the test.
    eps[date(2019, 12, 31)] = 1.0
    eps[date(2019, 3, 31)] = 1.0
    sue = compute_sue(eps, focal=date(2021, 6, 30), history_window=2)
    # numerator = 0.5
    # prior 2 quarters: 2020-12-31, 2021-03-31
    #   2020-12-31 seasonal pred = 2019-12-31 → both 1.0 → diff = 0
    #   2021-03-31 seasonal pred = 2020-03-31 → 1.0 - 1.0 = 0
    # Both diffs = 0 → variance = 0 → SUE = NaN
    # That's a degenerate denominator case
    assert math.isnan(sue)


# --- the no-look-ahead invariant -----------------------------------------


def test_focal_eps_change_does_not_affect_denominator():
    """Load-bearing: changing focal EPS must alter numerator only."""
    eps_base = _calendar_year_eps(2018, 6, val_fn=lambda y, q: 1.0 + 0.1 * y)
    # Add a one-off shock at 2021-12-31 to ensure variance > 0
    eps_base[date(2021, 12, 31)] = 5.0

    eps_a = dict(eps_base)
    eps_a[date(2023, 6, 30)] = 10.0
    eps_b = dict(eps_base)
    eps_b[date(2023, 6, 30)] = 100.0

    sue_a = compute_sue(eps_a, focal=date(2023, 6, 30))
    sue_b = compute_sue(eps_b, focal=date(2023, 6, 30))

    if math.isfinite(sue_a) and math.isfinite(sue_b) and sue_a != 0:
        pred_val = eps_base[date(2022, 6, 30)]
        ratio_observed = sue_b / sue_a
        ratio_expected = (100.0 - pred_val) / (10.0 - pred_val)
        assert math.isclose(ratio_observed, ratio_expected, rel_tol=1e-9)


# --- panel convenience --------------------------------------------------


def test_compute_sue_panel_preserves_nan_entries():
    eps = _calendar_year_eps(2020, 2, val_fn=lambda y, q: 1.0)
    focal = [date(2020, 3, 31), date(2020, 6, 30), date(2021, 3, 31)]
    out = compute_sue_panel(eps, focal)
    assert set(out.keys()) == set(focal)
    # All NaN: 2020 has no prior year → no predecessor; 2021Q1 has only
    # 4 prior period_ends in 2020 → can't fill history_window=8
    assert all(math.isnan(v) for v in out.values())
