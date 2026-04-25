"""Tests for the honest cost model (square-root impact + spread + borrow)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.cost_model import (
    SquareRootImpactModel,
    BorrowCostTable,
    HonestCostModel,
    corwin_schultz_spread,
)


class TestSquareRootImpact:
    def test_zero_trade_hits_floor(self):
        m = SquareRootImpactModel(k_bps=15.0, floor_bps=0.5)
        # A zero-size trade still pays the floor (models unavoidable concession)
        bps = m.cost_bps(np.array([0.0]), np.array([1e9]))
        assert bps[0] == pytest.approx(0.5)

    def test_monotone_in_participation(self):
        m = SquareRootImpactModel(k_bps=15.0)
        adv = np.full(3, 1e8)
        trades = np.array([1e5, 1e6, 1e7])
        bps = m.cost_bps(trades, adv)
        assert bps[0] < bps[1] < bps[2]

    def test_sqrt_scaling(self):
        """Quadrupling participation should roughly double impact bps."""
        m = SquareRootImpactModel(k_bps=15.0, floor_bps=0.01)
        adv = np.array([1e9, 1e9])
        trades = np.array([1e6, 4e6])
        bps = m.cost_bps(trades, adv)
        assert bps[1] / bps[0] == pytest.approx(2.0, rel=1e-6)

    def test_ceiling_clip(self):
        m = SquareRootImpactModel(k_bps=15.0, ceil_bps=200.0)
        bps = m.cost_bps(np.array([1e12]), np.array([1e6]))
        assert bps[0] == 200.0

    def test_dollar_cost(self):
        m = SquareRootImpactModel(k_bps=15.0, floor_bps=0.01)
        # participation = 1e6 / 1e9 = 0.001; impact = 15*sqrt(0.001) ≈ 0.4743 bps
        cost = m.cost_dollar(np.array([1e6]), np.array([1e9]))
        assert cost[0] == pytest.approx(1e6 * 15.0 * np.sqrt(0.001) * 1e-4, rel=1e-4)


class TestBorrowCostTable:
    def test_default_mega_cap(self):
        tbl = BorrowCostTable(default_bps_per_year=25.0)
        # Shorting $1M for 252 trading days at 25 bp/yr → $2500
        cost = tbl.daily_cost("AAPL", -1_000_000, days=252)
        assert cost == pytest.approx(2500.0, rel=1e-9)

    def test_htb_override(self):
        tbl = BorrowCostTable(default_bps_per_year=25.0, htb_map={"GME": 5000.0})
        cost_htb = tbl.daily_cost("GME", -1_000_000, days=252)
        cost_gc = tbl.daily_cost("AAPL", -1_000_000, days=252)
        assert cost_htb == pytest.approx(500_000.0, rel=1e-9)
        assert cost_htb == 200.0 * cost_gc

    def test_case_insensitive_ticker(self):
        tbl = BorrowCostTable(htb_map={"GME": 1000.0})
        assert tbl.bps_per_year("gme") == 1000.0


class TestCorwinSchultzSpread:
    def test_zero_spread_on_collapsed_range(self):
        """If High==Low for every day, CS estimator should be ≈ 0."""
        n = 50
        idx = pd.date_range("2024-01-01", periods=n)
        h = pd.DataFrame({"A": np.full(n, 100.0)}, index=idx)
        l = h.copy()
        s = corwin_schultz_spread(h, l, window=21)
        assert (s.dropna() >= 0).all().all()
        assert s.iloc[-1, 0] == pytest.approx(0.0, abs=1e-6)

    def test_wider_range_wider_spread(self):
        """Doubling daily high/low range should widen CS spread monotonically."""
        n = 60
        idx = pd.date_range("2024-01-01", periods=n)
        rng = np.random.default_rng(0)
        mid = 100 + np.cumsum(rng.normal(0, 0.2, n))
        narrow_h = pd.DataFrame({"A": mid * 1.005}, index=idx)
        narrow_l = pd.DataFrame({"A": mid * 0.995}, index=idx)
        wide_h = pd.DataFrame({"A": mid * 1.02}, index=idx)
        wide_l = pd.DataFrame({"A": mid * 0.98}, index=idx)
        s_narrow = corwin_schultz_spread(narrow_h, narrow_l, window=21).iloc[-1, 0]
        s_wide = corwin_schultz_spread(wide_h, wide_l, window=21).iloc[-1, 0]
        assert s_wide > s_narrow


class TestHonestCostModel:
    def test_rebalance_cost_components_stack(self):
        m = HonestCostModel(
            impact=SquareRootImpactModel(k_bps=15.0, floor_bps=0.01),
            commission_bps=0.5,
            spread_fallback_half_bps=2.0,
        )
        trade = pd.Series({"A": 1_000_000.0, "B": -500_000.0})
        adv = pd.Series({"A": 1e9, "B": 5e8})
        cost = m.rebalance_cost_dollars(trade, adv)
        assert (cost >= 0).all()
        # Spread + commission floor: 2.5 bps × $1M = $250
        # Impact on A: 15*sqrt(0.001) ≈ 0.47 bps × $1M ≈ $47
        assert cost["A"] > 250.0

    def test_borrow_bills_only_shorts(self):
        m = HonestCostModel()
        short_notional = pd.Series({"A": -1_000_000.0, "B": 500_000.0})
        borrow = m.holding_borrow_cost_dollars(short_notional, days=21)
        # Only A should be billed
        assert borrow["A"] > 0.0
        assert borrow["B"] == 0.0
