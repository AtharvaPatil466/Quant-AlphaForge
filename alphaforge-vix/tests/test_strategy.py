"""Unit tests for gauntlet/strategy.py."""
from __future__ import annotations

import math

import pandas as pd
import pytest

from gauntlet import strategy as strat


# ---------------------------------------------------------------------------
# Frozen constants — guardrails so accidental edits are caught
# ---------------------------------------------------------------------------

def test_frozen_constants_match_design():
    assert strat.SIZING_CONSTANT == 0.10
    assert strat.HEDGE_NOTIONAL_RATIO == 0.10
    assert strat.HARD_STOP_VIX_PCT == 0.40
    assert strat.TIME_EXIT_CALENDAR_DAYS == 60
    assert strat.SVXY_RESTRUCTURING_DATE == pd.Timestamp("2018-02-27")
    assert strat.SVXY_EXPOSURE_PRE == -1.0
    assert strat.SVXY_EXPOSURE_POST == -0.5
    assert strat.VXX_FIRST_AVAILABLE == pd.Timestamp("2018-01-25")


# ---------------------------------------------------------------------------
# Sizing
# ---------------------------------------------------------------------------

def test_size_position_formula():
    out = strat.size_position(strat.SizingInputs(
        portfolio_value=1_000_000, vix_level=20.0, cash_available=1_000_000,
    ))
    # 0.10 * 1e6 / 20 = 5000
    assert math.isclose(out.max_notional, 5000.0)
    assert math.isclose(out.short_vol_notional, 5000.0)
    assert not out.cash_floor_binding


def test_size_position_caps_at_cash():
    out = strat.size_position(strat.SizingInputs(
        portfolio_value=1_000_000, vix_level=20.0, cash_available=2_000.0,
    ))
    # cash cap 0.99 * 2000 = 1980 < raw 5000.
    assert out.max_notional == 5000.0
    assert math.isclose(out.short_vol_notional, 1980.0)
    assert out.cash_floor_binding


def test_size_position_auto_deleverages_on_vix_spike():
    pv = 1_000_000
    cash = 1_000_000
    low = strat.size_position(strat.SizingInputs(pv, 10.0, cash))
    high = strat.size_position(strat.SizingInputs(pv, 40.0, cash))
    # VIX 4× higher → notional 4× smaller.
    assert math.isclose(low.short_vol_notional / high.short_vol_notional, 4.0)


def test_size_position_rejects_zero_vix():
    with pytest.raises(ValueError):
        strat.size_position(strat.SizingInputs(1e6, 0.0, 1e6))


def test_size_position_zero_portfolio_returns_zero():
    out = strat.size_position(strat.SizingInputs(0.0, 20.0, 0.0))
    assert out.short_vol_notional == 0.0


# ---------------------------------------------------------------------------
# Substrate-#8 sizing rule
# ---------------------------------------------------------------------------

def test_baseline_vix_sizing_at_baseline_gives_10pct_nav():
    out = strat.size_position_baseline_vix(strat.SizingInputs(
        portfolio_value=1_000_000, vix_level=20.0, cash_available=1_000_000,
    ))
    # SIZING_CONSTANT (0.10) × pv × (20 / 20) = 100_000
    assert math.isclose(out.max_notional, 100_000.0)
    assert math.isclose(out.short_vol_notional, 100_000.0)


def test_baseline_vix_sizing_inverse_relationship():
    pv = 1_000_000
    cash = 1_000_000
    out_low = strat.size_position_baseline_vix(strat.SizingInputs(pv, 10.0, cash))
    out_high = strat.size_position_baseline_vix(strat.SizingInputs(pv, 40.0, cash))
    # 4× VIX → 4× smaller notional.
    assert math.isclose(out_low.short_vol_notional / out_high.short_vol_notional, 4.0)


def test_baseline_vix_sizing_is_20x_substrate7_at_baseline():
    inputs = strat.SizingInputs(
        portfolio_value=1_000_000, vix_level=20.0, cash_available=1_000_000,
    )
    s7 = strat.size_position(inputs)
    s8 = strat.size_position_baseline_vix(inputs)
    # Substrate #8 is exactly 20× substrate #7 (because baseline=20.0).
    assert math.isclose(s8.max_notional / s7.max_notional, 20.0)


def test_baseline_vix_sizing_custom_baseline():
    out = strat.size_position_baseline_vix(
        strat.SizingInputs(1_000_000, 20.0, 1_000_000),
        baseline_vix=15.0,
    )
    # 0.10 × 1e6 × (15 / 20) = 75_000
    assert math.isclose(out.max_notional, 75_000.0)


def test_baseline_vix_sizing_rejects_zero_baseline():
    with pytest.raises(ValueError):
        strat.size_position_baseline_vix(
            strat.SizingInputs(1_000_000, 20.0, 1_000_000),
            baseline_vix=0.0,
        )


def test_baseline_vix_sizing_rejects_zero_vix():
    with pytest.raises(ValueError):
        strat.size_position_baseline_vix(
            strat.SizingInputs(1_000_000, 0.0, 1_000_000),
        )


# ---------------------------------------------------------------------------
# SVXY exposure multiplier
# ---------------------------------------------------------------------------

def test_svxy_multiplier_pre_restructuring():
    assert strat.svxy_exposure_multiplier(pd.Timestamp("2015-06-15")) == 1.0


def test_svxy_multiplier_post_restructuring():
    assert strat.svxy_exposure_multiplier(pd.Timestamp("2018-02-27")) == 2.0
    assert strat.svxy_exposure_multiplier(pd.Timestamp("2024-01-01")) == 2.0


def test_svxy_multiplier_boundary_day_is_post():
    # On 2018-02-27 itself the post-restructuring exposure applies.
    assert strat.svxy_exposure_multiplier(strat.SVXY_RESTRUCTURING_DATE) == 2.0


def test_svxy_effective_exposure_values():
    assert strat.svxy_effective_exposure(pd.Timestamp("2015-01-01")) == -1.0
    assert strat.svxy_effective_exposure(pd.Timestamp("2020-01-01")) == -0.5


# ---------------------------------------------------------------------------
# Variant A leg construction (unhedged)
# ---------------------------------------------------------------------------

def test_variant_a_short_vol_pre_2018():
    spec = strat.build_legs(
        short_vol_notional=10_000.0,
        direction=strat.TradeDirection.SHORT_VOL,
        variant=strat.HedgeVariant.A,
        svxy_price=100.0,
        vxx_price=None,
        trade_date=pd.Timestamp("2015-06-15"),
    )
    assert len(spec.legs) == 1
    leg = spec.legs[0]
    assert leg.instrument == "SVXY"
    # pre-2018 multiplier = 1.0 → 10000 / 100 = 100 shares.
    assert math.isclose(leg.shares, 100.0)
    assert math.isclose(leg.notional, 10_000.0)
    assert not spec.hedge_active


def test_variant_a_short_vol_post_2018_doubles_svxy():
    spec = strat.build_legs(
        short_vol_notional=10_000.0,
        direction=strat.TradeDirection.SHORT_VOL,
        variant=strat.HedgeVariant.A,
        svxy_price=100.0,
        vxx_price=None,
        trade_date=pd.Timestamp("2020-06-15"),
    )
    leg = spec.legs[0]
    # post-2018 multiplier = 2.0 → SVXY notional = 20000, shares = 200.
    assert math.isclose(leg.notional, 20_000.0)
    assert math.isclose(leg.shares, 200.0)


# ---------------------------------------------------------------------------
# Variant B leg construction (SVXY + VXX hedge)
# ---------------------------------------------------------------------------

def test_variant_b_short_vol_post_2018_adds_vxx_hedge():
    spec = strat.build_legs(
        short_vol_notional=10_000.0,
        direction=strat.TradeDirection.SHORT_VOL,
        variant=strat.HedgeVariant.B,
        svxy_price=100.0,
        vxx_price=50.0,
        trade_date=pd.Timestamp("2020-06-15"),
    )
    assert len(spec.legs) == 2
    svxy_leg = next(l for l in spec.legs if l.instrument == "SVXY")
    vxx_leg = next(l for l in spec.legs if l.instrument == "VXX")
    # SVXY notional 20000 (2× short-vol notional); hedge = 10% of SVXY = 2000.
    assert math.isclose(svxy_leg.notional, 20_000.0)
    assert math.isclose(vxx_leg.notional, 2_000.0)
    assert math.isclose(vxx_leg.shares, 40.0)
    assert spec.hedge_active


def test_variant_b_pre_2018_raises():
    with pytest.raises(strat.HedgeUnavailableError):
        strat.build_legs(
            short_vol_notional=10_000.0,
            direction=strat.TradeDirection.SHORT_VOL,
            variant=strat.HedgeVariant.B,
            svxy_price=100.0,
            vxx_price=50.0,
            trade_date=pd.Timestamp("2015-06-15"),
        )


def test_variant_b_requires_vxx_price():
    with pytest.raises(ValueError):
        strat.build_legs(
            short_vol_notional=10_000.0,
            direction=strat.TradeDirection.SHORT_VOL,
            variant=strat.HedgeVariant.B,
            svxy_price=100.0,
            vxx_price=None,
            trade_date=pd.Timestamp("2020-06-15"),
        )


# ---------------------------------------------------------------------------
# Mean-reversion (LONG_VOL) direction
# ---------------------------------------------------------------------------

def test_long_vol_variant_a_uses_vxx():
    spec = strat.build_legs(
        short_vol_notional=10_000.0,
        direction=strat.TradeDirection.LONG_VOL,
        variant=strat.HedgeVariant.A,
        svxy_price=100.0,
        vxx_price=50.0,
        trade_date=pd.Timestamp("2020-06-15"),
    )
    assert len(spec.legs) == 1
    assert spec.legs[0].instrument == "VXX"
    # Notional 10000 / 50 = 200 shares
    assert math.isclose(spec.legs[0].shares, 200.0)
    assert not spec.hedge_active


def test_long_vol_pre_vxx_raises():
    with pytest.raises(strat.HedgeUnavailableError):
        strat.build_legs(
            short_vol_notional=10_000.0,
            direction=strat.TradeDirection.LONG_VOL,
            variant=strat.HedgeVariant.A,
            svxy_price=100.0,
            vxx_price=50.0,
            trade_date=pd.Timestamp("2015-06-15"),
        )


def test_long_vol_variant_b_adds_svxy_counter_hedge():
    spec = strat.build_legs(
        short_vol_notional=10_000.0,
        direction=strat.TradeDirection.LONG_VOL,
        variant=strat.HedgeVariant.B,
        svxy_price=100.0,
        vxx_price=50.0,
        trade_date=pd.Timestamp("2020-06-15"),
    )
    assert len(spec.legs) == 2
    vxx_leg = next(l for l in spec.legs if l.instrument == "VXX")
    svxy_leg = next(l for l in spec.legs if l.instrument == "SVXY")
    assert math.isclose(vxx_leg.notional, 10_000.0)
    assert math.isclose(svxy_leg.notional, 1_000.0)


# ---------------------------------------------------------------------------
# Exit-rule state machine
# ---------------------------------------------------------------------------

def _make_position(direction=strat.TradeDirection.SHORT_VOL,
                   minimum_hold_days=5,
                   days_held=10,
                   entry_date=pd.Timestamp("2020-06-01")) -> strat.Position:
    return strat.Position(
        trial_name="test", variant=strat.HedgeVariant.A,
        direction=direction,
        entry_date=entry_date,
        svxy_entry_price=100.0,
        svxy_shares=100.0,
        short_vol_notional=10_000.0,
        days_held=days_held,
        minimum_hold_days=minimum_hold_days,
    )


def test_hard_stop_fires_on_40pct_intraday_vix_spike():
    ctx = strat.ExitContext(
        trade_date=pd.Timestamp("2020-03-16"),
        vix_close=60.0, vix_high=70.0, vix_close_prev=49.0,
        vrp=10.0, ma63=None, sigma63=None,
    )
    # (70 - 49) / 49 = 0.428 > 0.40 → fire.
    assert strat.hard_stop_fired(ctx)


def test_hard_stop_does_not_fire_on_moderate_move():
    ctx = strat.ExitContext(
        trade_date=pd.Timestamp("2020-03-16"),
        vix_close=22.0, vix_high=23.0, vix_close_prev=20.0,
        vrp=5.0, ma63=None, sigma63=None,
    )
    assert not strat.hard_stop_fired(ctx)


def test_time_exit_fires_after_60_days():
    pos = _make_position(entry_date=pd.Timestamp("2020-01-01"),
                         days_held=70)
    ctx = strat.ExitContext(
        trade_date=pd.Timestamp("2020-03-15"),
        vix_close=20.0, vix_high=22.0, vix_close_prev=20.0,
        vrp=5.0, ma63=None, sigma63=None,
    )
    assert strat.time_exit_fired(pos, ctx)


def test_signal_exit_fires_when_vrp_goes_negative_on_short_vol():
    pos = _make_position(days_held=10)
    ctx = strat.ExitContext(
        trade_date=pd.Timestamp("2020-06-15"),
        vix_close=18.0, vix_high=19.0, vix_close_prev=18.5,
        vrp=-0.5, ma63=None, sigma63=None,
    )
    assert strat.signal_exit_fired(pos, ctx)


def test_signal_exit_blocked_by_minimum_hold():
    pos = _make_position(minimum_hold_days=21, days_held=10)
    ctx = strat.ExitContext(
        trade_date=pd.Timestamp("2020-06-15"),
        vix_close=18.0, vix_high=19.0, vix_close_prev=18.5,
        vrp=-0.5, ma63=None, sigma63=None,
    )
    decision = strat.evaluate_exit(pos, ctx)
    # Minimum hold not satisfied → signal exit suppressed.
    assert not decision.should_exit


def test_evaluate_exit_priority_hard_stop_beats_signal():
    pos = _make_position(days_held=21, minimum_hold_days=21)
    ctx = strat.ExitContext(
        trade_date=pd.Timestamp("2020-03-16"),
        vix_close=60.0, vix_high=80.0, vix_close_prev=40.0,
        vrp=-2.0, ma63=None, sigma63=None,
    )
    decision = strat.evaluate_exit(pos, ctx)
    assert decision.should_exit
    assert decision.reason == strat.ExitReason.HARD_STOP


def test_signal_exit_mean_reversion_long_vol():
    pos = _make_position(direction=strat.TradeDirection.LONG_VOL,
                         days_held=10)
    ctx = strat.ExitContext(
        trade_date=pd.Timestamp("2020-06-15"),
        vix_close=18.0, vix_high=19.0, vix_close_prev=18.5,
        vrp=5.0, ma63=20.0, sigma63=3.0,
    )
    # Exit threshold = MA63 + 1.0·σ63 = 23. VIX 18 is below → exit.
    decision = strat.evaluate_exit(
        pos, ctx, mean_reversion_exit_threshold=23.0,
    )
    assert decision.should_exit
    assert decision.reason == strat.ExitReason.SIGNAL


def test_no_exit_when_nothing_fires():
    pos = _make_position(days_held=10, minimum_hold_days=5)
    ctx = strat.ExitContext(
        trade_date=pd.Timestamp("2020-06-15"),
        vix_close=20.0, vix_high=21.0, vix_close_prev=20.0,
        vrp=5.0, ma63=None, sigma63=None,
    )
    decision = strat.evaluate_exit(pos, ctx)
    assert not decision.should_exit
    assert decision.reason == strat.ExitReason.NONE
