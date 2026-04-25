"""Tests for pre-trade risk checks and circuit breakers."""

import pytest

from risk.limits import RiskCheckResult, check_circuit_breakers, check_pre_trade


class TestCheckPreTrade:
    def test_passes_within_limits(self):
        result = check_pre_trade(
            target_weights={"AAPL": 0.05, "MSFT": 0.05},
            current_nav=100_000,
        )
        assert result.passed is True
        assert result.failures == []

    def test_position_too_large(self):
        result = check_pre_trade(
            target_weights={"AAPL": 0.15},
            current_nav=100_000,
            max_position_pct=0.10,
        )
        assert result.passed is False
        assert any("AAPL" in f for f in result.failures)

    def test_gross_exposure_exceeded(self):
        weights = {f"T{i}": 0.09 for i in range(20)}  # 180% gross
        result = check_pre_trade(
            target_weights=weights,
            current_nav=100_000,
            max_gross_exposure=1.50,
        )
        assert result.passed is False
        assert any("Gross" in f for f in result.failures)

    def test_daily_turnover_exceeded(self):
        result = check_pre_trade(
            target_weights={"AAPL": 0.10, "MSFT": 0.10, "NVDA": 0.10},
            current_nav=100_000,
            max_daily_turnover=0.10,
            current_weights={"GOOGL": 0.10, "META": 0.10, "AVGO": 0.10},
        )
        assert result.passed is False
        assert any("turnover" in f.lower() for f in result.failures)

    def test_boundary_position_passes(self):
        result = check_pre_trade(
            target_weights={"AAPL": 0.10},
            current_nav=100_000,
            max_position_pct=0.10,
        )
        assert result.passed is True

    def test_boundary_exposure_passes(self):
        weights = {f"T{i}": 0.05 for i in range(20)}  # 100% gross, under 150%
        result = check_pre_trade(
            target_weights=weights,
            current_nav=100_000,
            max_gross_exposure=1.50,
            max_daily_turnover=2.0,  # relax turnover for this test
            current_weights=weights,  # no turnover
        )
        assert result.passed is True

    def test_empty_weights_passes(self):
        result = check_pre_trade(target_weights={}, current_nav=100_000)
        assert result.passed is True

    def test_multiple_failures(self):
        result = check_pre_trade(
            target_weights={"AAPL": 0.20, "MSFT": 0.20},
            current_nav=100_000,
            max_position_pct=0.10,
            max_gross_exposure=0.30,
        )
        assert result.passed is False
        assert len(result.failures) >= 2

    def test_no_current_weights(self):
        result = check_pre_trade(
            target_weights={"AAPL": 0.05},
            current_nav=100_000,
        )
        assert result.passed is True


class TestCheckCircuitBreakers:
    def test_passes_normal(self):
        result = check_circuit_breakers(daily_return=0.01, drawdown=0.02)
        assert result.passed is True

    def test_daily_loss_trigger(self):
        result = check_circuit_breakers(
            daily_return=-0.03, drawdown=0.01, max_daily_loss=0.02
        )
        assert result.passed is False
        assert any("Daily" in f for f in result.failures)

    def test_drawdown_trigger(self):
        result = check_circuit_breakers(
            daily_return=0.0, drawdown=0.15, max_drawdown=0.10
        )
        assert result.passed is False
        assert any("Drawdown" in f for f in result.failures)

    def test_both_triggered(self):
        result = check_circuit_breakers(
            daily_return=-0.05, drawdown=0.15,
            max_daily_loss=0.02, max_drawdown=0.10,
        )
        assert result.passed is False
        assert len(result.failures) == 2

    def test_boundary_daily_loss_passes(self):
        result = check_circuit_breakers(
            daily_return=-0.02, drawdown=0.0, max_daily_loss=0.02
        )
        assert result.passed is True

    def test_boundary_drawdown_passes(self):
        result = check_circuit_breakers(
            daily_return=0.0, drawdown=0.10, max_drawdown=0.10
        )
        assert result.passed is True
