"""Pairs-trading strategy tests."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from strategies.pairs_trading import (
    _adf_tstat, _ols_beta_residual, find_pairs,
    PairsConfig, pairs_backtest,
)


class TestADFAndOLS:
    def test_ols_recovers_beta(self):
        rng = np.random.default_rng(0)
        x = rng.normal(0, 1, 500)
        y = 3.0 + 2.0 * x + rng.normal(0, 0.01, 500)
        a, b, _ = _ols_beta_residual(y, x)
        assert a == pytest.approx(3.0, abs=0.1)
        assert b == pytest.approx(2.0, abs=0.05)

    def test_adf_rejects_stationary_series(self):
        rng = np.random.default_rng(1)
        # White noise is stationary → very negative t-stat
        x = rng.normal(0, 1, 500)
        t = _adf_tstat(x)
        assert t < -5.0

    def test_adf_does_not_reject_random_walk(self):
        rng = np.random.default_rng(2)
        x = np.cumsum(rng.normal(0, 1, 500))
        t = _adf_tstat(x)
        # Random walks should NOT be strongly rejected
        assert t > -3.0


class TestFindPairs:
    def test_finds_constructed_cointegrated_pair(self):
        rng = np.random.default_rng(3)
        n = 300
        idx = pd.date_range("2022-01-01", periods=n, freq="B")
        x_log = np.cumsum(rng.normal(0, 0.01, n))
        # y = x + stationary noise → cointegrated with β ≈ 1
        y_log = x_log + rng.normal(0, 0.005, n)
        # Plus some noisy unrelated tickers
        z1 = np.cumsum(rng.normal(0, 0.01, n))
        z2 = np.cumsum(rng.normal(0, 0.01, n))
        close = pd.DataFrame({
            "X": np.exp(x_log + 4.0),
            "Y": np.exp(y_log + 4.0),
            "Z1": np.exp(z1 + 4.0),
            "Z2": np.exp(z2 + 4.0),
        }, index=idx)
        pairs = find_pairs(close, adf_t_threshold=-2.5, top_n=5)
        # At least one Y/X (or X/Y) pair should be found
        names = [(p.y_ticker, p.x_ticker) for p in pairs]
        assert any({a, b} == {"X", "Y"} for a, b in names), names


class TestPairsBacktest:
    def test_runs_and_emits_series(self):
        rng = np.random.default_rng(4)
        n = 400
        idx = pd.date_range("2022-01-01", periods=n, freq="B")
        x_log = np.cumsum(rng.normal(0, 0.01, n))
        y_log = x_log + rng.normal(0, 0.005, n)
        z_log = np.cumsum(rng.normal(0, 0.01, n))
        close = pd.DataFrame({
            "X": np.exp(x_log + 4.0),
            "Y": np.exp(y_log + 4.0),
            "Z": np.exp(z_log + 4.0),
        }, index=idx)
        cfg = PairsConfig(formation_days=200, rebal_days=63, max_pairs=5)
        bt = pairs_backtest(close, cfg, tx_bps_per_turnover=10.0)
        assert len(bt["gross"]) == n
        assert len(bt["net"]) == n
        # Net should be ≤ gross (costs deducted)
        assert bt["net"].sum() <= bt["gross"].sum() + 1e-9
