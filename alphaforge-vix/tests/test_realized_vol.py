"""Tests for ingest.realized_vol."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from ingest import realized_vol as RV


# ---------------------------------------------------------------------------
# compute_log_returns
# ---------------------------------------------------------------------------

def test_compute_log_returns_first_value_is_nan():
    s = pd.Series([100.0, 101.0, 102.0],
                   index=pd.date_range("2024-01-01", periods=3))
    out = RV.compute_log_returns(s)
    assert pd.isna(out.iloc[0])
    assert out.iloc[1] == pytest.approx(np.log(101 / 100))
    assert out.iloc[2] == pytest.approx(np.log(102 / 101))


def test_compute_log_returns_handles_unchanged_prices():
    s = pd.Series([100.0, 100.0, 100.0],
                   index=pd.date_range("2024-01-01", periods=3))
    out = RV.compute_log_returns(s)
    assert out.iloc[1] == 0.0
    assert out.iloc[2] == 0.0


# ---------------------------------------------------------------------------
# compute_realized_vol
# ---------------------------------------------------------------------------

def test_compute_realized_vol_zero_for_constant_returns():
    """If log-returns are constant (no variance), realized vol is 0."""
    ret = pd.Series([0.01] * 30,
                     index=pd.date_range("2024-01-01", periods=30, freq="B"))
    vol = RV.compute_realized_vol(ret, window=10)
    assert vol.iloc[-1] == pytest.approx(0.0)


def test_compute_realized_vol_matches_hand_calc_in_percent():
    """std × √252 × 100 — output in percent units (VIX convention)."""
    rng = np.random.default_rng(42)
    ret = pd.Series(rng.normal(0, 0.01, 100),
                     index=pd.date_range("2024-01-01", periods=100, freq="B"))
    vol = RV.compute_realized_vol(ret, window=21)
    expected = ret.tail(21).std() * np.sqrt(252) * 100.0
    assert vol.iloc[-1] == pytest.approx(expected)


def test_compute_realized_vol_scales_to_vix_units():
    """Output should be on the same scale as VIX (percent annualized)."""
    ret = pd.Series([0.01, -0.01] * 50,
                     index=pd.date_range("2024-01-01", periods=100, freq="B"))
    vol = RV.compute_realized_vol(ret, window=21)
    # Pandas .std() uses ddof=1 (sample). Match it exactly.
    expected = ret.tail(21).std(ddof=1) * np.sqrt(252) * 100.0
    assert vol.iloc[-1] == pytest.approx(expected)
    # Sanity: 1% daily vol → ~15-17% annualized (in VIX units, not 0.15).
    assert 14.0 < vol.iloc[-1] < 18.0


def test_compute_realized_vol_pre_window_is_nan():
    ret = pd.Series(np.random.normal(0, 0.01, 30),
                     index=pd.date_range("2024-01-01", periods=30))
    vol = RV.compute_realized_vol(ret, window=21)
    assert pd.isna(vol.iloc[0])
    assert pd.isna(vol.iloc[19])
    assert not pd.isna(vol.iloc[20])  # 21st observation completes the window


# ---------------------------------------------------------------------------
# build_spy_panel
# ---------------------------------------------------------------------------

def test_build_spy_panel_has_all_four_columns():
    close = pd.Series(
        100 + np.cumsum(np.random.default_rng(1).normal(0, 1, 200)),
        index=pd.date_range("2010-01-04", periods=200, freq="B"),
    )
    panel = RV.build_spy_panel(close)
    assert set(panel.columns) == {
        "log_return", "realized_vol_10", "realized_vol_21", "realized_vol_63",
    }
    assert len(panel) == 200


def test_build_spy_panel_realized_vol_63_starts_later():
    """The 63-day series needs 63 obs; earlier indices stay NaN."""
    close = pd.Series(
        100 + np.cumsum(np.random.default_rng(1).normal(0, 1, 100)),
        index=pd.date_range("2010-01-04", periods=100, freq="B"),
    )
    panel = RV.build_spy_panel(close)
    assert pd.isna(panel["realized_vol_63"].iloc[50])
    assert not pd.isna(panel["realized_vol_63"].iloc[80])


# ---------------------------------------------------------------------------
# validate_spike_events
# ---------------------------------------------------------------------------

def _make_panel_with_spike(spike_date: date, spike_vol: float = 80.0,
                            n_days: int = 252) -> pd.DataFrame:
    """Build a synthetic SPY panel where realized_vol_21 = spike_vol on the
    given date and ~10% (vol units, like VIX) elsewhere."""
    idx = pd.date_range(pd.Timestamp(spike_date) - pd.Timedelta(days=180),
                         pd.Timestamp(spike_date) + pd.Timedelta(days=60),
                         freq="B")
    return pd.DataFrame({
        "log_return": pd.Series(0.0, index=idx),
        "realized_vol_10": pd.Series(10.0, index=idx),
        "realized_vol_21": pd.Series(
            [spike_vol if d == pd.Timestamp(spike_date) else 10.0 for d in idx],
            index=idx,
        ),
        "realized_vol_63": pd.Series(10.0, index=idx),
    })


def test_evaluate_check_max_gt_passes_when_spike_in_window():
    panel = _make_panel_with_spike(date(2008, 10, 1), spike_vol=80.0)
    check = RV.SpikeCheck(
        name="lehman_test", date_window=(date(2008, 9, 15), date(2008, 11, 30)),
        metric="realized_vol_21", op="max>", threshold=60.0,
    )
    r = RV._evaluate_check(panel, check)
    assert r.passed
    assert r.observed == pytest.approx(80.0)


def test_evaluate_check_max_gt_fails_when_spike_too_small():
    panel = _make_panel_with_spike(date(2008, 10, 1), spike_vol=30.0)
    check = RV.SpikeCheck(
        name="lehman_test", date_window=(date(2008, 9, 15), date(2008, 11, 30)),
        metric="realized_vol_21", op="max>", threshold=60.0,
    )
    r = RV._evaluate_check(panel, check)
    assert not r.passed


def test_evaluate_check_min_lt_for_crash_day():
    idx = pd.date_range("2020-03-01", "2020-04-01", freq="B")
    log_ret = pd.Series(0.0, index=idx)
    log_ret.loc[pd.Timestamp("2020-03-16")] = -0.12
    panel = pd.DataFrame({
        "log_return": log_ret, "realized_vol_10": 10.0,
        "realized_vol_21": 10.0, "realized_vol_63": 10.0,
    }, index=idx)
    check = RV.SpikeCheck(
        name="covid", date_window=(date(2020, 3, 9), date(2020, 3, 20)),
        metric="log_return", op="min<", threshold=-0.10,
    )
    r = RV._evaluate_check(panel, check)
    assert r.passed
    assert r.observed == pytest.approx(-0.12)


def test_evaluate_check_no_data_in_window():
    panel = _make_panel_with_spike(date(2008, 10, 1))
    check = RV.SpikeCheck(
        name="future", date_window=(date(2030, 1, 1), date(2030, 12, 31)),
        metric="realized_vol_21", op="max>", threshold=60.0,
    )
    r = RV._evaluate_check(panel, check)
    assert not r.passed
    assert "no data" in r.summary.lower()


# ---------------------------------------------------------------------------
# validate_spike_events — full battery
# ---------------------------------------------------------------------------

def test_validate_spike_events_all_pass_when_all_spikes_present():
    """Construct a panel containing all 5 known spikes."""
    full_idx = pd.date_range("2008-01-01", "2024-12-31", freq="B")
    panel = pd.DataFrame({
        "log_return": pd.Series(0.0, index=full_idx),
        "realized_vol_10": pd.Series(10.0, index=full_idx),
        "realized_vol_21": pd.Series(10.0, index=full_idx),
        "realized_vol_63": pd.Series(10.0, index=full_idx),
    })
    # 2008 Lehman: realized_vol_21 > 60 in Sep-Nov 2008.
    panel.loc[pd.Timestamp("2008-10-15"), "realized_vol_21"] = 80.0
    # 2010 Flash Crash: log_return < -0.035 in early May.
    panel.loc[pd.Timestamp("2010-05-06"), "log_return"] = -0.04
    # 2015 China devaluation: realized_vol_21 > 20 in late Aug.
    panel.loc[pd.Timestamp("2015-08-26"), "realized_vol_21"] = 25.0
    # 2018 Volmageddon: realized_vol_21 > 20 in Feb-Mar.
    panel.loc[pd.Timestamp("2018-02-08"), "realized_vol_21"] = 35.0
    # 2020 COVID Monday: log_return < -0.10 mid-March.
    panel.loc[pd.Timestamp("2020-03-16"), "log_return"] = -0.12

    report = RV.validate_spike_events(panel)
    assert report.all_passed
    assert report.n_passed == 5


def test_validate_spike_events_some_fail():
    """Panel missing the 2020 COVID spike → 4 of 5 pass."""
    full_idx = pd.date_range("2008-01-01", "2024-12-31", freq="B")
    panel = pd.DataFrame({
        "log_return": pd.Series(0.0, index=full_idx),
        "realized_vol_10": pd.Series(10.0, index=full_idx),
        "realized_vol_21": pd.Series(10.0, index=full_idx),
        "realized_vol_63": pd.Series(10.0, index=full_idx),
    })
    panel.loc[pd.Timestamp("2008-10-15"), "realized_vol_21"] = 80.0
    panel.loc[pd.Timestamp("2010-05-06"), "log_return"] = -0.04
    panel.loc[pd.Timestamp("2015-08-26"), "realized_vol_21"] = 25.0
    panel.loc[pd.Timestamp("2018-02-08"), "realized_vol_21"] = 35.0
    # 2020 NOT spiked.

    report = RV.validate_spike_events(panel)
    assert not report.all_passed
    assert report.n_passed == 4
    failures = [r for r in report.results if not r.passed]
    assert any("covid" in r.name.lower() for r in failures)
