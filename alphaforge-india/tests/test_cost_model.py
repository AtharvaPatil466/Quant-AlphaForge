"""Tests for the Indian equity cost model (signals/cost_model.py).

Validates every component of the NSE regulatory cost stack as defined
in INDIA_DESIGN.md §6, the Corwin-Schultz half-spread estimator, and
the Gate 4 stress-doubling logic.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from signals.cost_model import (
    BUY_SIDE_BPS,
    EXCHANGE_TXN_BPS,
    GST_ON_BROKERAGE_BPS,
    GST_RATE,
    IMPACT_BPS_PER_UNIT,
    ROUND_TRIP_BPS,
    SEBI_CHARGES_BPS,
    SELL_SIDE_BPS,
    STAMP_DUTY_BPS,
    STRESS_MULTIPLIER,
    STT_BPS,
    BROKERAGE_BPS,
    IndianCostModel,
    corwin_schultz_spread,
)


# =========================================================================
# Module-level constants
# =========================================================================

class TestModuleConstants:
    """Verify the module-level constant definitions match §6."""

    def test_brokerage_bps(self) -> None:
        assert BROKERAGE_BPS == 10.0

    def test_gst_rate(self) -> None:
        assert GST_RATE == 0.18

    def test_gst_on_brokerage(self) -> None:
        assert GST_ON_BROKERAGE_BPS == pytest.approx(1.8)

    def test_exchange_txn(self) -> None:
        assert EXCHANGE_TXN_BPS == 0.3

    def test_sebi_charges(self) -> None:
        assert SEBI_CHARGES_BPS == 0.1

    def test_stamp_duty(self) -> None:
        assert STAMP_DUTY_BPS == 1.5

    def test_stt(self) -> None:
        assert STT_BPS == 10.0

    def test_buy_side_total(self) -> None:
        assert BUY_SIDE_BPS == pytest.approx(13.7)

    def test_sell_side_total(self) -> None:
        assert SELL_SIDE_BPS == pytest.approx(22.2)

    def test_round_trip(self) -> None:
        assert ROUND_TRIP_BPS == pytest.approx(35.9)

    def test_impact_coefficient(self) -> None:
        assert IMPACT_BPS_PER_UNIT == 10.0

    def test_stress_multiplier(self) -> None:
        assert STRESS_MULTIPLIER == 2.0


# =========================================================================
# IndianCostModel — default instance
# =========================================================================

class TestIndianCostModelDefaults:
    """Default-parameter model must reproduce the §6 table exactly."""

    @pytest.fixture()
    def model(self) -> IndianCostModel:
        return IndianCostModel()

    def test_buy_side(self, model: IndianCostModel) -> None:
        assert model.buy_cost_bps() == pytest.approx(13.7)

    def test_sell_side(self, model: IndianCostModel) -> None:
        assert model.sell_cost_bps() == pytest.approx(22.2)

    def test_round_trip_at_unit_turnover(self, model: IndianCostModel) -> None:
        # 13.7 + 22.2 + 10.0 * 1.0 = 45.9
        assert model.round_trip_cost_bps(turnover=1.0) == pytest.approx(45.9)

    def test_round_trip_at_zero_turnover(self, model: IndianCostModel) -> None:
        # 13.7 + 22.2 + 0 = 35.9
        assert model.round_trip_cost_bps(turnover=0.0) == pytest.approx(35.9)

    def test_round_trip_at_half_turnover(self, model: IndianCostModel) -> None:
        # 35.9 + 10.0 * 0.5 = 40.9
        assert model.round_trip_cost_bps(turnover=0.5) == pytest.approx(40.9)

    def test_round_trip_negative_turnover_clamps(
        self, model: IndianCostModel,
    ) -> None:
        # Negative turnover should be treated as zero impact.
        assert model.round_trip_cost_bps(turnover=-0.5) == pytest.approx(35.9)

    def test_stressed_at_unit_turnover(self, model: IndianCostModel) -> None:
        # 2 * (35.9 + 10.0) = 91.8
        assert model.stressed_round_trip_cost_bps(turnover=1.0) == pytest.approx(
            91.8
        )

    def test_stressed_at_zero_turnover(self, model: IndianCostModel) -> None:
        # 2 * 35.9 = 71.8
        assert model.stressed_round_trip_cost_bps(turnover=0.0) == pytest.approx(
            71.8
        )

    def test_stressed_matches_design_doc(self, model: IndianCostModel) -> None:
        """§6 explicitly states: 71.8 bp round-trip + 20 bp per unit impact."""
        stressed = model.stressed_round_trip_cost_bps(turnover=1.0)
        # 71.8 + 20.0 = 91.8
        assert stressed == pytest.approx(71.8 + 20.0)

    def test_notional_argument_accepted(self, model: IndianCostModel) -> None:
        """notional is accepted for interface symmetry but does not
        change the flat-bps result."""
        assert model.buy_cost_bps(notional=1_000_000) == model.buy_cost_bps()
        assert model.sell_cost_bps(notional=1_000_000) == model.sell_cost_bps()


# =========================================================================
# IndianCostModel — component decomposition
# =========================================================================

class TestIndianCostModelComponents:
    """Verify buy and sell breakdowns match §6 table row-by-row."""

    @pytest.fixture()
    def model(self) -> IndianCostModel:
        return IndianCostModel()

    def test_gst_on_brokerage_property(self, model: IndianCostModel) -> None:
        assert model.gst_on_brokerage_bps == pytest.approx(1.8)

    def test_buy_equals_common_plus_stamp(self, model: IndianCostModel) -> None:
        common = (
            model.brokerage_bps
            + model.gst_on_brokerage_bps
            + model.exchange_txn_bps
            + model.sebi_charges_bps
        )
        assert model.buy_cost_bps() == pytest.approx(common + model.stamp_duty_bps)

    def test_sell_equals_common_plus_stt(self, model: IndianCostModel) -> None:
        common = (
            model.brokerage_bps
            + model.gst_on_brokerage_bps
            + model.exchange_txn_bps
            + model.sebi_charges_bps
        )
        assert model.sell_cost_bps() == pytest.approx(common + model.stt_bps)

    def test_sell_minus_buy_is_stt_minus_stamp(
        self, model: IndianCostModel,
    ) -> None:
        diff = model.sell_cost_bps() - model.buy_cost_bps()
        assert diff == pytest.approx(model.stt_bps - model.stamp_duty_bps)

    def test_cost_breakdown_dict(self, model: IndianCostModel) -> None:
        bd = model.cost_breakdown()
        assert bd["brokerage_bps"] == 10.0
        assert bd["gst_on_brokerage_bps"] == pytest.approx(1.8)
        assert bd["exchange_txn_bps"] == 0.3
        assert bd["sebi_charges_bps"] == 0.1
        assert bd["stamp_duty_bps"] == 1.5
        assert bd["stt_bps"] == 10.0
        assert bd["buy_side_total_bps"] == pytest.approx(13.7)
        assert bd["sell_side_total_bps"] == pytest.approx(22.2)
        assert bd["impact_bps_per_unit"] == 10.0
        assert bd["stress_multiplier"] == 2.0


# =========================================================================
# IndianCostModel — custom parameters
# =========================================================================

class TestIndianCostModelCustom:
    """Verify that custom parameters flow through correctly."""

    def test_zero_brokerage(self) -> None:
        model = IndianCostModel(brokerage_bps=0.0)
        # Buy: 0 + 0 + 0.3 + 0.1 + 1.5 = 1.9
        assert model.buy_cost_bps() == pytest.approx(1.9)

    def test_higher_stt(self) -> None:
        model = IndianCostModel(stt_bps=20.0)
        # Sell: 10 + 1.8 + 0.3 + 0.1 + 20 = 32.2
        assert model.sell_cost_bps() == pytest.approx(32.2)

    def test_custom_impact(self) -> None:
        model = IndianCostModel(impact_bps_per_unit=20.0)
        rt = model.round_trip_cost_bps(turnover=1.0)
        # 35.9 + 20.0 = 55.9
        assert rt == pytest.approx(55.9)

    def test_custom_stress_multiplier(self) -> None:
        model = IndianCostModel(stress_multiplier=3.0)
        stressed = model.stressed_round_trip_cost_bps(turnover=1.0)
        # 3 * (35.9 + 10.0) = 137.7
        assert stressed == pytest.approx(137.7)


# =========================================================================
# Corwin-Schultz half-spread estimator
# =========================================================================

class TestCorwinSchultzSpread:
    """Validate the Corwin-Schultz (2012) spread estimator."""

    @pytest.fixture()
    def random_ohlc(self) -> dict[str, pd.DataFrame]:
        """Generate synthetic OHLC data with known spread properties."""
        rng = np.random.default_rng(42)
        n = 100
        dates = pd.bdate_range("2020-01-01", periods=n)
        close = 1000.0 + np.cumsum(rng.normal(0, 2.0, n))
        # Construct high/low around close with a controlled range.
        spread_frac = 0.005  # 50 bps total range
        high = close * (1.0 + spread_frac * rng.uniform(0.5, 1.0, n))
        low = close * (1.0 - spread_frac * rng.uniform(0.5, 1.0, n))
        return {
            "high": pd.DataFrame({"STOCK": high}, index=dates),
            "low": pd.DataFrame({"STOCK": low}, index=dates),
            "close": pd.DataFrame({"STOCK": close}, index=dates),
        }

    def test_returns_dataframe(self, random_ohlc: dict) -> None:
        result = corwin_schultz_spread(
            random_ohlc["high"], random_ohlc["low"], random_ohlc["close"],
        )
        assert isinstance(result, pd.DataFrame)
        assert result.shape == random_ohlc["high"].shape

    def test_values_non_negative(self, random_ohlc: dict) -> None:
        result = corwin_schultz_spread(
            random_ohlc["high"], random_ohlc["low"], random_ohlc["close"],
        )
        assert (result.values[~np.isnan(result.values)] >= 0.0).all()

    def test_window_nans(self, random_ohlc: dict) -> None:
        """First `window` rows should be NaN."""
        window = 10
        result = corwin_schultz_spread(
            random_ohlc["high"], random_ohlc["low"], window=window,
        )
        # The first (window) rows should be NaN because of the rolling
        # window PLUS the 1-period shift in β computation.
        # Exactly how many NaN rows depends on both window and shift.
        first_valid_idx = result["STOCK"].first_valid_index()
        if first_valid_idx is not None:
            first_valid_pos = result.index.get_loc(first_valid_idx)
            assert first_valid_pos >= window

    def test_shape_mismatch_raises(self) -> None:
        h = pd.DataFrame({"A": [1, 2, 3]})
        l_ = pd.DataFrame({"A": [1, 2], "B": [1, 2]})
        with pytest.raises(ValueError, match="same shape"):
            corwin_schultz_spread(h, l_)

    def test_window_too_small_raises(self) -> None:
        h = pd.DataFrame({"A": [1, 2, 3]})
        l_ = pd.DataFrame({"A": [1, 2, 3]})
        with pytest.raises(ValueError, match="window must be >= 2"):
            corwin_schultz_spread(h, l_, window=1)

    def test_series_input(self) -> None:
        """Should accept pd.Series and return pd.Series."""
        rng = np.random.default_rng(99)
        n = 50
        dates = pd.bdate_range("2021-01-01", periods=n)
        close = 500.0 + np.cumsum(rng.normal(0, 1.0, n))
        high = pd.Series(close * 1.003, index=dates)
        low = pd.Series(close * 0.997, index=dates)
        result = corwin_schultz_spread(high, low, window=5)
        assert isinstance(result, pd.Series)
        assert len(result) == n

    def test_wider_spread_yields_larger_estimate(self) -> None:
        """A stock with wider H/L range should have a larger half-spread."""
        rng = np.random.default_rng(123)
        n = 60
        dates = pd.bdate_range("2022-01-01", periods=n)
        close = 200.0 + np.cumsum(rng.normal(0, 0.5, n))

        # Narrow spread
        h_narrow = pd.DataFrame({"S": close * 1.001}, index=dates)
        l_narrow = pd.DataFrame({"S": close * 0.999}, index=dates)

        # Wide spread
        h_wide = pd.DataFrame({"S": close * 1.01}, index=dates)
        l_wide = pd.DataFrame({"S": close * 0.99}, index=dates)

        cs_narrow = corwin_schultz_spread(h_narrow, l_narrow, window=10)
        cs_wide = corwin_schultz_spread(h_wide, l_wide, window=10)

        # Compare the median of the non-NaN tail.
        narrow_med = cs_narrow["S"].dropna().median()
        wide_med = cs_wide["S"].dropna().median()
        assert wide_med > narrow_med

    def test_constant_price_returns_zero(self) -> None:
        """If H == L every day, spread estimate should be zero."""
        n = 30
        dates = pd.bdate_range("2023-01-01", periods=n)
        price = pd.DataFrame({"S": np.full(n, 100.0)}, index=dates)
        result = corwin_schultz_spread(price, price, window=5)
        valid = result["S"].dropna()
        assert (valid == 0.0).all()

    def test_multi_column(self) -> None:
        """Works with multiple tickers in columns."""
        rng = np.random.default_rng(7)
        n = 40
        dates = pd.bdate_range("2023-06-01", periods=n)
        c1 = 500.0 + np.cumsum(rng.normal(0, 1, n))
        c2 = 1500.0 + np.cumsum(rng.normal(0, 3, n))
        high = pd.DataFrame(
            {"RELIANCE": c1 * 1.003, "TCS": c2 * 1.005}, index=dates,
        )
        low = pd.DataFrame(
            {"RELIANCE": c1 * 0.997, "TCS": c2 * 0.995}, index=dates,
        )
        result = corwin_schultz_spread(high, low, window=10)
        assert list(result.columns) == ["RELIANCE", "TCS"]
        assert result.shape == (n, 2)

    def test_default_window_is_21(self) -> None:
        """Default window parameter is 21 (one Indian trading month)."""
        rng = np.random.default_rng(55)
        n = 50
        dates = pd.bdate_range("2024-01-01", periods=n)
        close = 300.0 + np.cumsum(rng.normal(0, 1, n))
        high = pd.DataFrame({"S": close * 1.002}, index=dates)
        low = pd.DataFrame({"S": close * 0.998}, index=dates)

        result = corwin_schultz_spread(high, low)
        # First valid at index 21 or later (window=21 + shift).
        first_valid = result["S"].first_valid_index()
        assert first_valid is not None
        pos = result.index.get_loc(first_valid)
        assert pos >= 21


# =========================================================================
# Integration: cost model + spread estimator together
# =========================================================================

class TestIntegration:
    """Sanity-check the cost model values against §6 numeric targets."""

    def test_section6_round_trip_before_impact(self) -> None:
        """§6: 'Round-trip parametric cost: 13.7 + 22.2 = 35.9 bp
        before market impact.'"""
        model = IndianCostModel()
        assert model.round_trip_cost_bps(turnover=0.0) == pytest.approx(35.9)

    def test_section6_gate4_stressed(self) -> None:
        """§6: 'Gate 4 stress: doubled to 71.8 bp round-trip + 20 bp
        per unit impact.'"""
        model = IndianCostModel()
        # At zero turnover: 2 * 35.9 = 71.8
        assert model.stressed_round_trip_cost_bps(turnover=0.0) == pytest.approx(
            71.8
        )
        # At unit turnover: 71.8 + 20 = 91.8
        assert model.stressed_round_trip_cost_bps(turnover=1.0) == pytest.approx(
            91.8
        )

    def test_stt_is_sell_only(self) -> None:
        """§6 table: STT = 0 bp buy, 10 bp sell."""
        model = IndianCostModel()
        # Build buy side from scratch excluding STT.
        buy_manual = 10.0 + 1.8 + 0.3 + 0.1 + 1.5
        assert model.buy_cost_bps() == pytest.approx(buy_manual)
        # Build sell side from scratch including STT.
        sell_manual = 10.0 + 1.8 + 0.3 + 0.1 + 10.0
        assert model.sell_cost_bps() == pytest.approx(sell_manual)

    def test_stamp_duty_is_buy_only(self) -> None:
        """§6 table: stamp duty = 1.5 bp buy, 0 bp sell."""
        model = IndianCostModel()
        # Sell side should NOT include stamp duty.
        sell_common = model.brokerage_bps + model.gst_on_brokerage_bps + \
            model.exchange_txn_bps + model.sebi_charges_bps
        assert model.sell_cost_bps() == pytest.approx(sell_common + model.stt_bps)
