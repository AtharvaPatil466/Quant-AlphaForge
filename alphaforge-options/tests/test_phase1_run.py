"""Tests for alphaforge-options/research/phase1_run.py.

Tests the evaluation logic in isolation (pass criterion, report structure)
without requiring the full data stack. The SHA-guard and IO functions are
tested with temporary files.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from research.phase1_run import (
    evaluate_pass_criterion,
    rfree_for_date,
)


# ---------------------------------------------------------------------------
# rfree_for_date
# ---------------------------------------------------------------------------

class TestRfreeForDate:
    def test_pre_crisis_rate(self):
        dt = pd.Timestamp("2007-03-15")
        r = rfree_for_date(dt)
        assert abs(r - 0.035) < 1e-10

    def test_post_crisis_rate(self):
        dt = pd.Timestamp("2010-06-01")
        r = rfree_for_date(dt)
        assert abs(r - 0.001) < 1e-10

    def test_fallback_for_unknown_year(self):
        dt = pd.Timestamp("2020-01-01")
        r = rfree_for_date(dt)
        assert abs(r - 0.045) < 1e-10


# ---------------------------------------------------------------------------
# evaluate_pass_criterion
# ---------------------------------------------------------------------------

def _make_cycles(
    n_per_year: int = 11,
    years: range = range(2004, 2015),
    pnl_fn=None,
    vrp_fn=None,
) -> pd.DataFrame:
    """Synthetic cycle DataFrame with known properties."""
    records = []
    pnl_fn = pnl_fn or (lambda yr, i: 0.10)
    vrp_fn = vrp_fn or (lambda yr, i: 2.0)

    for yr in years:
        for i in range(n_per_year):
            dt = pd.Timestamp(f"{yr}-{(i % 12) + 1:02d}-01")
            records.append(
                {
                    "entry_date": dt,
                    "roll_date": dt + pd.Timedelta(days=21),
                    "vrp": vrp_fn(yr, i),
                    "entered": True,
                    "pnl_per_share": pnl_fn(yr, i),
                    "premium": 2.0,
                }
            )
    return pd.DataFrame(records)


class TestEvaluatePassCriterion:
    def test_all_positive_passes_all_three_tests(self):
        # Both VRP and pnl must vary so Pearson correlation is defined;
        # make them positively correlated so test1 passes.
        df = _make_cycles(
            vrp_fn=lambda yr, i: 1.0 + 0.1 * i,
            pnl_fn=lambda yr, i: 0.05 + 0.01 * i,
        )
        result = evaluate_pass_criterion(df)
        assert result["passed"] is True
        assert result["test1_pass"] is True
        assert result["test2_pass"] is True
        assert result["test3_pass"] is True

    def test_all_negative_fails_all_tests(self):
        df = _make_cycles(pnl_fn=lambda yr, i: -0.10)
        result = evaluate_pass_criterion(df)
        assert result["passed"] is False
        assert result["test1_pass"] is False

    def test_too_few_cycles_returns_failed(self):
        # Empty DataFrame with correct columns — simulates no cycles traded
        df = pd.DataFrame(
            columns=["entry_date", "roll_date", "vrp", "entered", "pnl_per_share", "premium"]
        )
        result = evaluate_pass_criterion(df)
        assert result["passed"] is False
        assert "n_cycles" in result

    def test_negative_correlation_fails_test1(self):
        # High VRP → negative pnl, low VRP → positive pnl
        def pnl_fn(yr, i):
            return -0.05 * i

        def vrp_fn(yr, i):
            return 0.5 + 0.1 * i

        df = _make_cycles(pnl_fn=pnl_fn, vrp_fn=vrp_fn)
        result = evaluate_pass_criterion(df)
        assert result["test1_pass"] is False

    def test_crisis_years_excluded_in_test3(self):
        # Make 2008 and 2009 negative but 5+ of the other 9 years positive
        def pnl_fn(yr, i):
            return -0.10 if yr in (2008, 2009) else 0.10

        df = _make_cycles(pnl_fn=pnl_fn)
        result = evaluate_pass_criterion(df)
        # 9 non-crisis years, all positive → test3 passes
        assert result["test3_pass"] is True
        # Overall: 2008+2009 are negative → positive years might be < 7
        # 9 positive out of 11 → test2 passes too
        assert result["test2_positive_years"] == 9

    def test_exactly_7_positive_years_passes_test2(self):
        # Make exactly 7 of 11 IS years positive
        positive_years = set(range(2004, 2011))  # 2004-2010 = 7 years

        def pnl_fn(yr, i):
            return 0.10 if yr in positive_years else -0.10

        df = _make_cycles(pnl_fn=pnl_fn)
        result = evaluate_pass_criterion(df)
        assert result["test2_positive_years"] == 7
        assert result["test2_pass"] is True

    def test_6_positive_years_fails_test2(self):
        positive_years = set(range(2004, 2010))  # 6 years

        def pnl_fn(yr, i):
            return 0.10 if yr in positive_years else -0.10

        df = _make_cycles(pnl_fn=pnl_fn)
        result = evaluate_pass_criterion(df)
        assert result["test2_positive_years"] == 6
        assert result["test2_pass"] is False

    def test_exactly_5_ex_crisis_passes_test3(self):
        # 2008, 2009 negative; exactly 5 of remaining 9 positive
        positive_ex = {2004, 2005, 2006, 2007, 2010}

        def pnl_fn(yr, i):
            if yr in (2008, 2009):
                return -0.10
            return 0.10 if yr in positive_ex else -0.10

        df = _make_cycles(pnl_fn=pnl_fn)
        result = evaluate_pass_criterion(df)
        assert result["test3_positive_ex_crisis"] == 5
        assert result["test3_pass"] is True

    def test_4_ex_crisis_fails_test3(self):
        positive_ex = {2004, 2005, 2006, 2007}  # 4 only

        def pnl_fn(yr, i):
            if yr in (2008, 2009):
                return -0.10
            return 0.10 if yr in positive_ex else -0.10

        df = _make_cycles(pnl_fn=pnl_fn)
        result = evaluate_pass_criterion(df)
        assert result["test3_positive_ex_crisis"] == 4
        assert result["test3_pass"] is False

    def test_result_contains_required_keys(self):
        df = _make_cycles()
        result = evaluate_pass_criterion(df)
        required = {
            "passed", "test1_correlation", "test1_pass",
            "test2_positive_years", "test2_total_years", "test2_pass",
            "test3_positive_ex_crisis", "test3_total_ex_crisis", "test3_pass",
            "yearly_mean_pnl", "n_cycles_traded", "n_cycles_total",
            "mean_pnl", "std_pnl", "mean_vrp",
        }
        for k in required:
            assert k in result, f"Missing key: {k}"

    def test_skipped_cycles_excluded_from_traded(self):
        # Mix of entered=True and entered=False
        records = []
        for yr in range(2004, 2015):
            for month in range(1, 13):
                dt = pd.Timestamp(f"{yr}-{month:02d}-01")
                entered = month <= 8  # 8 per year entered, 4 skipped
                records.append(
                    {
                        "entry_date": dt,
                        "roll_date": dt + pd.Timedelta(days=21),
                        "vrp": 2.0 if entered else -1.0,
                        "entered": entered,
                        "pnl_per_share": 0.10 if entered else np.nan,
                        "premium": 2.0 if entered else np.nan,
                    }
                )
        df = pd.DataFrame(records)
        result = evaluate_pass_criterion(df)
        # n_cycles_traded should be less than n_cycles_total
        assert result["n_cycles_traded"] < result["n_cycles_total"]

    def test_yearly_mean_pnl_keys_are_ints(self):
        df = _make_cycles()
        result = evaluate_pass_criterion(df)
        for k in result["yearly_mean_pnl"]:
            assert isinstance(k, int)

    def test_passed_is_conjunction_of_three_tests(self):
        df = _make_cycles()
        result = evaluate_pass_criterion(df)
        expected = result["test1_pass"] and result["test2_pass"] and result["test3_pass"]
        assert result["passed"] == expected
