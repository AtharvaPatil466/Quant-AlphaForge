"""Tests for portfolio tracker."""

import math

import pytest

from portfolio.tracker import DailySnapshot, PortfolioTracker


class TestPortfolioTracker:
    def _tracker(self, nav=100_000.0):
        return PortfolioTracker(starting_nav=nav)

    def test_initial_state(self):
        t = self._tracker()
        assert t.nav_history == [100_000.0]
        assert t.daily_returns == []
        assert t.snapshots == []

    def test_record_day_basic(self):
        t = self._tracker()
        snap = t.record_day("2024-01-02", 101_000.0, 80_000.0, {"AAPL": 21_000.0})
        assert snap.nav == 101_000.0
        assert abs(snap.daily_return - 0.01) < 1e-6
        assert abs(snap.cumulative_return - 0.01) < 1e-6
        assert snap.drawdown == 0.0
        assert snap.n_positions == 1

    def test_drawdown_calculation(self):
        t = self._tracker(100_000.0)
        t.record_day("2024-01-02", 110_000.0, 100_000.0, {})
        snap = t.record_day("2024-01-03", 100_000.0, 100_000.0, {})
        expected_dd = (110_000 - 100_000) / 110_000
        assert abs(snap.drawdown - expected_dd) < 1e-6

    def test_peak_tracking(self):
        t = self._tracker(100_000.0)
        t.record_day("2024-01-02", 120_000.0, 100_000.0, {})
        t.record_day("2024-01-03", 110_000.0, 100_000.0, {})
        assert t.peak_nav == 120_000.0

    def test_long_short_exposure(self):
        t = self._tracker()
        snap = t.record_day(
            "2024-01-02", 100_000.0, 50_000.0,
            {"AAPL": 30_000.0, "MSFT": 20_000.0},
        )
        assert abs(snap.long_exposure - 0.50) < 1e-6
        assert snap.short_exposure == 0.0

    def test_weights_computed(self):
        t = self._tracker()
        snap = t.record_day(
            "2024-01-02", 100_000.0, 50_000.0,
            {"AAPL": 25_000.0, "MSFT": 25_000.0},
        )
        assert abs(snap.weights["AAPL"] - 0.25) < 1e-6
        assert abs(snap.weights["MSFT"] - 0.25) < 1e-6

    def test_sharpe_too_few_returns(self):
        t = self._tracker()
        for i in range(3):
            t.record_day(f"2024-01-0{i+2}", 100_000.0 + i * 100, 100_000.0, {})
        assert t.sharpe() == 0.0

    def test_sharpe_with_enough_returns(self):
        t = self._tracker()
        for i in range(10):
            nav = 100_000.0 + i * 500
            t.record_day(f"2024-01-{i+2:02d}", nav, 100_000.0, {})
        s = t.sharpe()
        assert math.isfinite(s)
        assert s > 0  # steadily increasing NAV → positive Sharpe

    def test_sharpe_zero_vol(self):
        t = self._tracker()
        for i in range(10):
            t.record_day(f"2024-01-{i+2:02d}", 100_000.0, 100_000.0, {})
        assert t.sharpe() == 0.0

    def test_max_drawdown(self):
        t = self._tracker(100_000.0)
        t.record_day("d1", 110_000, 100_000, {})
        t.record_day("d2", 95_000, 100_000, {})
        t.record_day("d3", 105_000, 100_000, {})
        assert t.max_drawdown() > 0.13  # ~13.6%

    def test_max_drawdown_no_snapshots(self):
        t = self._tracker()
        assert t.max_drawdown() == 0.0

    def test_win_rate(self):
        t = self._tracker()
        navs = [100_000, 101_000, 100_500, 101_500, 100_000, 102_000]
        for i, nav in enumerate(navs[1:]):
            t.record_day(f"d{i}", nav, 100_000, {})
        # returns: +1%, -0.5%, +1%, -1.5%, +2% → 3 wins / 5
        assert abs(t.win_rate() - 0.6) < 1e-6

    def test_win_rate_empty(self):
        t = self._tracker()
        assert t.win_rate() == 0.0

    def test_total_return(self):
        t = self._tracker(100_000)
        t.record_day("d1", 110_000, 100_000, {})
        assert abs(t.total_return() - 0.10) < 1e-6

    def test_total_return_insufficient_data(self):
        t = self._tracker()
        assert t.total_return() == 0.0  # only starting NAV

    def test_sharpe_annualize_flag(self):
        t = self._tracker()
        for i in range(10):
            nav = 100_000.0 + i * 500
            t.record_day(f"d{i}", nav, 100_000.0, {})
        s_ann = t.sharpe(annualize=True)
        s_raw = t.sharpe(annualize=False)
        assert abs(s_ann / s_raw - math.sqrt(252)) < 0.01
