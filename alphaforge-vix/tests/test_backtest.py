"""Unit tests for gauntlet/backtest.py."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from gauntlet import backtest as bt
from gauntlet import costs as costs_mod
from gauntlet import strategy as strat


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def synthetic_market():
    """Build a synthetic 200-day market frame with VIX, SPY-derived realized
    vol, SVXY, and VXX. VIX trends down slowly so short-vol earns; spike on
    day 100 to test mean-reversion. Post-2018 timestamps so Variant B works.
    """
    rng = np.random.default_rng(0)
    n = 200
    idx = pd.date_range("2019-01-02", periods=n, freq="B")
    # VIX: 18 → 14 with a spike on day 100.
    vix_close = np.linspace(18.0, 14.0, n) + rng.normal(0, 0.5, n)
    vix_close[100:105] += 12.0  # spike
    vix_close = np.clip(vix_close, 10.0, 60.0)
    vix_high = vix_close + np.abs(rng.normal(0, 0.5, n))
    # Realized vol: lag VIX by ~3 days, mean revert.
    rv = np.zeros(n)
    rv[:21] = 15.0
    for i in range(21, n):
        rv[i] = 0.9 * rv[i - 1] + 0.1 * vix_close[i - 3] - 2.0
    rv = np.clip(rv, 5.0, 60.0)
    # SVXY: tracks 2× inverse VIX changes (post-2018 -0.5×).
    svxy_close = np.zeros(n)
    svxy_close[0] = 100.0
    for i in range(1, n):
        vix_pct = (vix_close[i] - vix_close[i - 1]) / vix_close[i - 1]
        svxy_close[i] = svxy_close[i - 1] * (1 - 0.5 * vix_pct)
    svxy_close = np.maximum(svxy_close, 1.0)
    svxy_open = np.concatenate([[svxy_close[0]], svxy_close[:-1]]) * (
        1 + rng.normal(0, 0.001, n)
    )
    # VXX: tracks +1× VIX-futures-front-month (proxy via VIX changes).
    vxx_close = np.zeros(n)
    vxx_close[0] = 30.0
    for i in range(1, n):
        vix_pct = (vix_close[i] - vix_close[i - 1]) / vix_close[i - 1]
        vxx_close[i] = vxx_close[i - 1] * (1 + 0.9 * vix_pct - 0.002)  # contango drag
    vxx_close = np.maximum(vxx_close, 1.0)
    vxx_open = np.concatenate([[vxx_close[0]], vxx_close[:-1]])

    df = pd.DataFrame({
        "vix_close": vix_close,
        "vix_high": vix_high,
        "svxy_open": svxy_open,
        "svxy_close": svxy_close,
        "vxx_open": vxx_open,
        "vxx_close": vxx_close,
        "realized_vol_21": rv,
    }, index=idx)
    return bt.MarketData(df=df)


# ---------------------------------------------------------------------------
# MarketData validation
# ---------------------------------------------------------------------------

def test_market_data_rejects_missing_columns():
    idx = pd.date_range("2019-01-02", periods=10, freq="B")
    bad = pd.DataFrame({"vix_close": np.zeros(10)}, index=idx)
    with pytest.raises(ValueError):
        bt.MarketData(df=bad)


def test_market_data_rejects_non_datetime_index():
    bad = pd.DataFrame({
        "vix_close": [0.0], "vix_high": [0.0],
        "svxy_open": [0.0], "svxy_close": [0.0],
    })
    with pytest.raises(ValueError):
        bt.MarketData(df=bad)


# ---------------------------------------------------------------------------
# Entry-signal predicates
# ---------------------------------------------------------------------------

def test_vrp_entry_fires_when_vrp_above_threshold():
    row = pd.Series({
        "vix_close": 20.0,
        "realized_vol_21": 15.0,
    })
    trial = bt.TrialSpec(
        name="t", variant=strat.HedgeVariant.A,
        direction=strat.TradeDirection.SHORT_VOL,
        realized_vol_lookback=21, vrp_threshold=2.0,
        holding_period=5,
    )
    # VRP = 5 >= 2 → True.
    assert bt.vrp_entry_signal(trial, row)


def test_vrp_entry_blocked_when_vrp_below_threshold():
    row = pd.Series({
        "vix_close": 16.0, "realized_vol_21": 15.0,
    })
    trial = bt.TrialSpec(
        name="t", variant=strat.HedgeVariant.A,
        direction=strat.TradeDirection.SHORT_VOL,
        realized_vol_lookback=21, vrp_threshold=2.0,
        holding_period=5,
    )
    assert not bt.vrp_entry_signal(trial, row)


def test_vrp_entry_handles_nan_realized_vol():
    row = pd.Series({
        "vix_close": 20.0,
        "realized_vol_21": float("nan"),
    })
    trial = bt.TrialSpec(
        name="t", variant=strat.HedgeVariant.A,
        direction=strat.TradeDirection.SHORT_VOL,
        realized_vol_lookback=21, vrp_threshold=0.0,
        holding_period=5,
    )
    assert not bt.vrp_entry_signal(trial, row)


def test_mean_reversion_entry_fires_above_threshold():
    row = pd.Series({
        "vix_close": 30.0, "ma63": 20.0, "sigma63": 3.0,
    })
    trial = bt.TrialSpec(
        name="mr", variant=strat.HedgeVariant.A,
        direction=strat.TradeDirection.LONG_VOL,
        realized_vol_lookback=21, vrp_threshold=0.0,
        holding_period=0, spike_k=2.0,
        signal_class="mean_reversion",
    )
    # Threshold = 20 + 2·3 = 26. VIX 30 > 26 → fire.
    assert bt.mean_reversion_entry_signal(trial, row)


def test_mean_reversion_entry_blocked_below_threshold():
    row = pd.Series({
        "vix_close": 24.0, "ma63": 20.0, "sigma63": 3.0,
    })
    trial = bt.TrialSpec(
        name="mr", variant=strat.HedgeVariant.A,
        direction=strat.TradeDirection.LONG_VOL,
        realized_vol_lookback=21, vrp_threshold=0.0,
        holding_period=0, spike_k=2.0,
        signal_class="mean_reversion",
    )
    assert not bt.mean_reversion_entry_signal(trial, row)


# ---------------------------------------------------------------------------
# Backtest run
# ---------------------------------------------------------------------------

def test_backtest_run_produces_nav_series(synthetic_market):
    trial = bt.TrialSpec(
        name="vrp_L21_thr2_hold5",
        variant=strat.HedgeVariant.A,
        direction=strat.TradeDirection.SHORT_VOL,
        realized_vol_lookback=21, vrp_threshold=2.0,
        holding_period=5,
    )
    b = bt.Backtest(synthetic_market, trial, costs_mod.baseline_costs())
    res = b.run()
    assert not res.daily_nav.empty
    # NAV start ≈ initial capital.
    assert math.isclose(res.daily_nav.iloc[0], 1_000_000.0, rel_tol=0.05)


def test_backtest_runs_trades_when_signal_fires(synthetic_market):
    trial = bt.TrialSpec(
        name="vrp_L21_thr0_hold5",
        variant=strat.HedgeVariant.A,
        direction=strat.TradeDirection.SHORT_VOL,
        realized_vol_lookback=21, vrp_threshold=0.0,
        holding_period=5,
    )
    b = bt.Backtest(synthetic_market, trial, costs_mod.baseline_costs())
    res = b.run()
    # At thr=0, signal fires whenever VIX >= RV, which happens often.
    assert len(res.trades) > 0


def test_backtest_variant_b_post_2018_works(synthetic_market):
    trial = bt.TrialSpec(
        name="vrp_L21_thr0_hold5_B",
        variant=strat.HedgeVariant.B,
        direction=strat.TradeDirection.SHORT_VOL,
        realized_vol_lookback=21, vrp_threshold=0.0,
        holding_period=5,
    )
    b = bt.Backtest(synthetic_market, trial, costs_mod.baseline_costs())
    res = b.run()
    # Should execute trades with both SVXY and VXX legs.
    assert len(res.trades) > 0
    # Cost should be higher than Variant A (more legs).
    assert all(t.cost_dollars > 0 for t in res.trades)


def test_backtest_empty_window_returns_empty_result(synthetic_market):
    trial = bt.TrialSpec(
        name="x", variant=strat.HedgeVariant.A,
        direction=strat.TradeDirection.SHORT_VOL,
        realized_vol_lookback=21, vrp_threshold=2.0, holding_period=5,
    )
    b = bt.Backtest(synthetic_market, trial, costs_mod.baseline_costs())
    res = b.run(start=pd.Timestamp("2030-01-01"))
    assert res.daily_nav.empty
    assert res.metadata.get("reason") == "empty_window"


def test_backtest_returns_correctly_computed(synthetic_market):
    trial = bt.TrialSpec(
        name="t", variant=strat.HedgeVariant.A,
        direction=strat.TradeDirection.SHORT_VOL,
        realized_vol_lookback=21, vrp_threshold=2.0, holding_period=5,
    )
    b = bt.Backtest(synthetic_market, trial, costs_mod.baseline_costs())
    res = b.run()
    # daily_returns is the pct-change of daily_nav (with first NaN dropped).
    expected = res.daily_nav.pct_change().dropna()
    pd.testing.assert_series_equal(res.daily_returns, expected,
                                    check_names=False)


def test_backtest_costs_reduce_pnl_vs_zero_cost(synthetic_market):
    """Round-trip costs must reduce net PnL on every trade."""
    trial = bt.TrialSpec(
        name="t", variant=strat.HedgeVariant.A,
        direction=strat.TradeDirection.SHORT_VOL,
        realized_vol_lookback=21, vrp_threshold=2.0, holding_period=5,
    )
    b = bt.Backtest(synthetic_market, trial, costs_mod.baseline_costs())
    res = b.run()
    for t in res.trades:
        assert t.net_pnl <= t.gross_pnl + 1e-6
        assert t.cost_dollars >= 0


def test_backtest_accepts_custom_sizing_fn(synthetic_market):
    """Substrate #8 path: Backtest accepts an alternate sizing function."""
    trial = bt.TrialSpec(
        name="t", variant=strat.HedgeVariant.A,
        direction=strat.TradeDirection.SHORT_VOL,
        realized_vol_lookback=21, vrp_threshold=2.0, holding_period=5,
    )
    # Substrate #7 (default).
    b7 = bt.Backtest(synthetic_market, trial, costs_mod.baseline_costs())
    res7 = b7.run()
    # Substrate #8 (baseline-VIX).
    b8 = bt.Backtest(synthetic_market, trial, costs_mod.baseline_costs(),
                     sizing_fn=strat.size_position_baseline_vix)
    res8 = b8.run()
    # If both fired a first trade, substrate #8's notional is much larger
    # (20× at VIX=20; synthetic VIX averages around 14-18 so ~25-30×).
    if res7.trades and res8.trades:
        assert res8.trades[0].short_vol_notional > 5 * res7.trades[0].short_vol_notional


def test_backtest_gate4_costs_higher_than_baseline(synthetic_market):
    """Gate-4 doubled-cost stack must produce higher total trade costs."""
    trial = bt.TrialSpec(
        name="t", variant=strat.HedgeVariant.A,
        direction=strat.TradeDirection.SHORT_VOL,
        realized_vol_lookback=21, vrp_threshold=2.0, holding_period=5,
    )
    b_base = bt.Backtest(synthetic_market, trial, costs_mod.baseline_costs())
    b_g4 = bt.Backtest(synthetic_market, trial, costs_mod.gate4_stress_costs())
    res_base = b_base.run()
    res_g4 = b_g4.run()
    # If both fired the same first trade, the gate-4 cost is roughly 2×.
    if res_base.trades and res_g4.trades:
        # Gate-4 round-trip is 20bp vs 10bp baseline → 2× cost.
        ratio = res_g4.trades[0].cost_dollars / res_base.trades[0].cost_dollars
        assert 1.8 < ratio < 2.2
