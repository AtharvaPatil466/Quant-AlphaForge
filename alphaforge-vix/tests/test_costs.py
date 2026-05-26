"""Unit tests for gauntlet/costs.py."""
from __future__ import annotations

import math

import pandas as pd
import pytest

from gauntlet import costs


# ---------------------------------------------------------------------------
# Frozen constants
# ---------------------------------------------------------------------------

def test_frozen_constants_match_design():
    assert costs.ETP_BASELINE_ROUND_TRIP_BPS == 10.0
    assert costs.ETP_GATE4_ROUND_TRIP_BPS == 20.0
    assert costs.STRESS_PERIOD_COST_MULTIPLIER == 3.0


def test_stress_periods_cover_4_pre_committed_windows():
    names = {name for name, _, _ in costs.STRESS_PERIODS}
    assert names == {
        "2008_financial_crisis", "2011_debt_ceiling",
        "2018_volmageddon", "2020_covid_crash",
    }


# ---------------------------------------------------------------------------
# in_stress_period
# ---------------------------------------------------------------------------

def test_in_stress_period_returns_name_inside_window():
    assert costs.in_stress_period(pd.Timestamp("2020-03-16")) == "2020_covid_crash"
    assert costs.in_stress_period(pd.Timestamp("2018-02-05")) == "2018_volmageddon"


def test_in_stress_period_returns_none_outside():
    assert costs.in_stress_period(pd.Timestamp("2015-06-15")) is None
    assert costs.in_stress_period(pd.Timestamp("2026-05-21")) is None


def test_stress_periods_inclusive_on_endpoints():
    # 2018-02-01 is the first day of the Volmageddon window.
    assert costs.in_stress_period(pd.Timestamp("2018-02-01")) == "2018_volmageddon"
    assert costs.in_stress_period(pd.Timestamp("2018-03-31")) == "2018_volmageddon"


# ---------------------------------------------------------------------------
# CostModel
# ---------------------------------------------------------------------------

def test_baseline_cost_model_round_trip_matches_design():
    m = costs.baseline_costs()
    # 10 bp round-trip → 5 bp per fill.
    assert math.isclose(m.total_bps_per_fill, 5.0)


def test_gate4_cost_model_is_doubled():
    m = costs.gate4_stress_costs()
    # 20 bp round-trip → 10 bp per fill.
    assert math.isclose(m.total_bps_per_fill, 10.0)


def test_invalid_regime_rejected():
    with pytest.raises(ValueError):
        costs.CostModel(regime="bogus")


def test_cost_model_charges_calm_period_baseline():
    m = costs.baseline_costs()
    fill = m.apply(100_000.0, pd.Timestamp("2015-06-15"))
    # 5 bp of 100k = 50 dollars.
    assert math.isclose(fill.total_dollars, 50.0)
    assert not fill.in_stress
    assert fill.stress_name is None


def test_cost_model_triples_during_stress_period():
    m = costs.baseline_costs()
    fill = m.apply(100_000.0, pd.Timestamp("2020-03-16"))
    # 5 bp × 3 = 15 bp of 100k = 150 dollars.
    assert math.isclose(fill.total_dollars, 150.0)
    assert fill.in_stress
    assert fill.stress_name == "2020_covid_crash"


def test_gate4_in_stress_compounds_correctly():
    m = costs.gate4_stress_costs()
    fill = m.apply(100_000.0, pd.Timestamp("2018-02-05"))
    # gate4 fill = 10 bp; × 3 (stress) = 30 bp of 100k = 300 dollars.
    assert math.isclose(fill.total_dollars, 300.0)


def test_apply_handles_negative_fill_notional_as_absolute():
    m = costs.baseline_costs()
    fill = m.apply(-100_000.0, pd.Timestamp("2015-06-15"))
    assert math.isclose(fill.total_dollars, 50.0)


# ---------------------------------------------------------------------------
# CarryTable — fallback path
# ---------------------------------------------------------------------------

def test_carry_table_fallback_lookup_zirp_era():
    ct = costs.CarryTable()
    # 2010 is in the ZIRP fallback tier (30 bp annualized).
    assert ct.lookup(pd.Timestamp("2010-06-15")) == 30.0


def test_carry_table_fallback_lookup_recent_hike_cycle():
    ct = costs.CarryTable()
    assert ct.lookup(pd.Timestamp("2024-06-15")) == 450.0


def test_carry_table_with_fred_series_overrides_fallback():
    # FRED-style series (percent annualized).
    s = pd.Series(
        [4.5, 4.5, 4.5],
        index=pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]),
    )
    ct = costs.CarryTable(fred_series=s)
    # 4.5% → 450 bp.
    assert ct.lookup(pd.Timestamp("2024-01-03")) == 450.0


def test_carry_table_forward_fills_past_last_observation():
    s = pd.Series([2.0], index=pd.to_datetime(["2024-01-02"]))
    ct = costs.CarryTable(fred_series=s)
    # No observation on 2024-06-15 → forward-fill from 2024-01-02.
    assert ct.lookup(pd.Timestamp("2024-06-15")) == 200.0


def test_carry_table_falls_back_before_first_observation():
    s = pd.Series([2.0], index=pd.to_datetime(["2024-01-02"]))
    ct = costs.CarryTable(fred_series=s)
    # 2010 is before the series start → fallback tier (ZIRP = 30 bp).
    assert ct.lookup(pd.Timestamp("2010-06-15")) == 30.0


def test_daily_carry_dollars_sign_convention():
    ct = costs.CarryTable()
    # Long cash 1M in 2010 (30 bp annualized) for 1 day.
    d = ct.daily_carry_dollars(1_000_000, pd.Timestamp("2010-06-15"), days=1)
    expected = 1_000_000 * 0.0030 / 365.0
    assert math.isclose(d, expected, rel_tol=1e-9)


def test_daily_carry_dollars_negative_capital_is_debit():
    ct = costs.CarryTable()
    d = ct.daily_carry_dollars(-500_000, pd.Timestamp("2024-06-15"), days=1)
    expected = -500_000 * 0.0450 / 365.0
    assert math.isclose(d, expected, rel_tol=1e-9)
