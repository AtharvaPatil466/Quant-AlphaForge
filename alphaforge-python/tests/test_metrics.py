"""
Metrics tests — all 9 plan-specified performance metrics + rolling_sharpe.
"""

import math
import numpy as np
import pytest

from backtest.metrics import (
    sharpe_ratio,
    max_drawdown,
    calmar_ratio,
    win_rate,
    annualized_return,
    annualized_vol,
    information_ratio,
    sortino_ratio,
    monthly_returns,
    rolling_sharpe,
)


class TestSharpeRatio:
    def test_zero_vol(self):
        assert sharpe_ratio([0.01, 0.01, 0.01]) == 0.0

    def test_positive_returns(self):
        rets = np.random.RandomState(42).normal(0.001, 0.01, 252)
        s = sharpe_ratio(rets)
        assert np.isfinite(s)
        assert s > 0

    def test_empty(self):
        assert sharpe_ratio([]) == 0.0

    def test_single(self):
        assert sharpe_ratio([0.05]) == 0.0


class TestMaxDrawdown:
    def test_no_drawdown(self):
        nav = [100, 110, 120, 130]
        dd, peak, trough = max_drawdown(nav)
        assert dd == pytest.approx(0.0)

    def test_known_drawdown(self):
        nav = [100, 120, 90, 110]
        dd, peak, trough = max_drawdown(nav)
        assert dd == pytest.approx(0.25)  # 30/120
        assert peak == 1  # index of 120
        assert trough == 2  # index of 90

    def test_empty(self):
        dd, p, t = max_drawdown([])
        assert dd == 0.0

    def test_single(self):
        dd, p, t = max_drawdown([100])
        assert dd == 0.0


class TestCalmarRatio:
    def test_no_drawdown(self):
        nav = [100, 110, 120]
        assert calmar_ratio([], nav) == 0.0  # dd=0 → return 0

    def test_with_drawdown(self):
        nav = [100, 120, 90, 110, 130]
        rets = np.diff(nav) / np.array(nav[:-1])
        c = calmar_ratio(rets, nav)
        assert np.isfinite(c)


class TestWinRate:
    def test_all_positive(self):
        assert win_rate([0.01, 0.02, 0.03]) == pytest.approx(1.0)

    def test_all_negative(self):
        assert win_rate([-0.01, -0.02]) == pytest.approx(0.0)

    def test_mixed(self):
        assert win_rate([0.01, -0.01, 0.01, -0.01]) == pytest.approx(0.5)

    def test_empty(self):
        assert win_rate([]) == 0.0


class TestAnnualizedReturn:
    def test_flat(self):
        nav = [100.0] * 253
        assert annualized_return(nav) == pytest.approx(0.0, abs=1e-10)

    def test_doubling(self):
        """NAV doubles in 252 days → ann return = 100%."""
        nav = np.linspace(100, 200, 253)
        ann = annualized_return(nav)
        assert ann == pytest.approx(1.0, rel=0.05)

    def test_empty(self):
        assert annualized_return([]) == 0.0


class TestAnnualizedVol:
    def test_zero_vol(self):
        assert annualized_vol([0.0, 0.0, 0.0]) == 0.0

    def test_positive_vol(self):
        rets = np.random.RandomState(42).normal(0, 0.01, 252)
        vol = annualized_vol(rets)
        assert vol > 0
        assert vol < 1.0  # 1% daily vol → ~16% annual

    def test_empty(self):
        assert annualized_vol([]) == 0.0


class TestInformationRatio:
    def test_identical(self):
        """Identical strategy and benchmark → IR = 0."""
        r = [0.01, 0.02, -0.01, 0.005]
        assert information_ratio(r, r) == 0.0

    def test_outperformance(self):
        s = [0.02, 0.03, 0.01, 0.015]
        b = [0.01, 0.01, 0.01, 0.01]
        ir = information_ratio(s, b)
        assert ir > 0

    def test_empty(self):
        assert information_ratio([], []) == 0.0


class TestSortinoRatio:
    def test_all_positive(self):
        """No downside → inf or 0 depending on implementation."""
        r = [0.01, 0.02, 0.03]
        s = sortino_ratio(r)
        # with only positive returns, downside count < 2, returns inf
        assert s == float("inf") or s == 0.0

    def test_mixed(self):
        rets = np.random.RandomState(42).normal(0.001, 0.01, 252)
        s = sortino_ratio(rets)
        assert np.isfinite(s)

    def test_empty(self):
        assert sortino_ratio([]) == 0.0


class TestMonthlyReturns:
    def test_252_days(self):
        """252 days → 12 months (21-day chunks)."""
        nav = np.linspace(100, 120, 253)
        m = monthly_returns(nav)
        assert len(m) == 12

    def test_all_finite(self):
        nav = np.linspace(100, 130, 253)
        m = monthly_returns(nav)
        assert all(math.isfinite(v) for v in m)

    def test_empty(self):
        assert monthly_returns([]) == []


class TestRollingSharpe:
    def test_output_length(self):
        nav = np.linspace(100, 120, 253)
        rs = rolling_sharpe(nav, window=63)
        assert len(rs) == 252  # len(nav) - 1

    def test_early_nan(self):
        nav = np.linspace(100, 120, 253)
        rs = rolling_sharpe(nav, window=63)
        assert np.isnan(rs[0])

    def test_later_finite(self):
        nav = np.linspace(100, 120, 253)
        rs = rolling_sharpe(nav, window=63)
        assert np.isfinite(rs[-1])

    def test_short_series(self):
        nav = [100, 101, 102]
        rs = rolling_sharpe(nav, window=63)
        assert len(rs) == 0
