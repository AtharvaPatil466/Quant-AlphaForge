"""
Backtest engine tests — mechanics, metric correctness, and edge cases.
"""

import numpy as np
import pytest

from backtest.synthetic_demo import BacktestConfig, BacktestResult, run_synthetic_backtest


@pytest.fixture
def default_result():
    config = BacktestConfig(
        sector="Technology",
        lookback=252,
        factor_name="Momentum (12-1)",
    )
    return run_synthetic_backtest(config)


class TestBacktestMechanics:
    def test_no_error(self, default_result):
        assert default_result.error is None

    def test_nav_starts_at_100(self, default_result):
        assert default_result.nav[0] == 100.0

    def test_benchmark_starts_at_100(self, default_result):
        assert default_result.benchmark_nav[0] == 100.0

    def test_nav_length(self, default_result):
        """NAV should have lookback+1 entries (initial + one per day)."""
        # +1 for initial value, prices array is lookback+1 long,
        # loop runs from day 1 to num_days-1
        assert len(default_result.nav) == 253  # 252 + 1

    def test_benchmark_same_length(self, default_result):
        assert len(default_result.benchmark_nav) == len(default_result.nav)

    def test_drawdowns_length(self, default_result):
        assert len(default_result.drawdowns) == len(default_result.nav) - 1

    def test_daily_returns_length(self, default_result):
        assert len(default_result.daily_returns) == len(default_result.nav) - 1

    def test_nav_always_positive(self, default_result):
        assert all(v > 0 for v in default_result.nav)

    def test_nav_no_nan(self, default_result):
        assert all(np.isfinite(v) for v in default_result.nav)

    def test_drawdowns_non_negative(self, default_result):
        assert all(d >= 0 for d in default_result.drawdowns)


class TestBacktestMetrics:
    def test_sharpe_finite(self, default_result):
        assert default_result.metrics.sharpe is not None
        assert np.isfinite(default_result.metrics.sharpe)

    def test_total_return_finite(self, default_result):
        assert default_result.metrics.total_return is not None

    def test_win_rate_bounded(self, default_result):
        wr = default_result.metrics.win_rate
        assert wr is not None
        assert 0.0 <= wr <= 1.0

    def test_max_dd_bounded(self, default_result):
        dd = default_result.metrics.max_dd
        assert dd is not None
        assert 0.0 <= dd <= 1.0

    def test_monthly_returns_count(self, default_result):
        """Monthly returns should be ~12 for 252 days (252/21 = 12)."""
        assert len(default_result.monthly_returns) == 12


class TestBacktestDeterminism:
    def test_same_config_same_result(self):
        config = BacktestConfig(sector="Technology", lookback=252)
        r1 = run_synthetic_backtest(config)
        r2 = run_synthetic_backtest(config)
        assert r1.nav == r2.nav
        assert r1.metrics.sharpe == r2.metrics.sharpe


class TestBacktestEdgeCases:
    def test_empty_sector(self):
        config = BacktestConfig(sector="Nonexistent", lookback=252)
        result = run_synthetic_backtest(config)
        assert result.error is not None

    def test_minimum_lookback(self):
        config = BacktestConfig(sector="Technology", lookback=21)
        result = run_synthetic_backtest(config)
        assert result.error is None
        assert len(result.nav) > 0

    def test_all_sectors(self):
        config = BacktestConfig(sector="All", lookback=252)
        result = run_synthetic_backtest(config)
        assert result.error is None

    def test_each_factor(self):
        """Each JS factor should produce a valid backtest."""
        from factors.registry import JS_FACTOR_NAMES
        for factor in JS_FACTOR_NAMES:
            config = BacktestConfig(
                sector="Technology", lookback=252, factor_name=factor
            )
            result = run_synthetic_backtest(config)
            assert result.error is None, f"Factor {factor} failed"
            assert len(result.nav) > 0
