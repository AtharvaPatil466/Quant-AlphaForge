"""TSMOM strategy tests."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from strategies.tsmom import TSMOMConfig, tsmom_weights, tsmom_backtest


@pytest.fixture
def trending_panel():
    rng = np.random.default_rng(0)
    n, k = 600, 5
    idx = pd.date_range("2018-01-01", periods=n, freq="B")
    # Drifts ~3x the noise so TSMOM's 12-month sign is stable under any seed.
    drifts = np.array([0.003, 0.003, -0.003, -0.003, 0.0])
    shocks = rng.normal(0, 0.01, size=(n, k))
    log_rets = shocks + drifts[None, :]
    close = pd.DataFrame(100.0 * np.exp(np.cumsum(log_rets, axis=0)),
                         index=idx, columns=[f"T{i}" for i in range(k)])
    return close


class TestTSMOMWeights:
    def test_sign_follows_trend(self, trending_panel):
        cfg = TSMOMConfig()
        w = tsmom_weights(trending_panel, cfg)
        latest = w.iloc[-1]
        # T0, T1 are up-trending; T2, T3 are down-trending
        assert latest["T0"] > 0 and latest["T1"] > 0
        assert latest["T2"] < 0 and latest["T3"] < 0

    def test_gross_leverage_cap_respected(self, trending_panel):
        cfg = TSMOMConfig(max_gross_leverage=1.5)
        w = tsmom_weights(trending_panel, cfg)
        gross = w.abs().sum(axis=1).dropna()
        assert (gross <= 1.5 + 1e-9).all()

    def test_per_leg_leverage_cap_respected(self, trending_panel):
        cfg = TSMOMConfig(max_leg_leverage=0.3, max_gross_leverage=10.0)
        w = tsmom_weights(trending_panel, cfg)
        # After the per-leg cap, no single weight exceeds 0.3 in magnitude.
        # (The gross cap scales all legs uniformly so it can only shrink further.)
        assert (w.abs() <= 0.3 + 1e-9).all().all()


class TestTSMOMBacktest:
    def test_backtest_net_less_than_gross_under_cost(self, trending_panel):
        cfg = TSMOMConfig()
        bt = tsmom_backtest(trending_panel, cfg, tx_bps_per_turnover=10.0)
        assert bt["net"].sum() <= bt["gross"].sum() + 1e-9
        assert bt["turnover"].sum() > 0

    def test_backtest_outputs_are_aligned(self, trending_panel):
        bt = tsmom_backtest(trending_panel, TSMOMConfig())
        for k in ("gross", "net", "turnover"):
            assert len(bt[k]) == len(trending_panel)
        assert bt["weights"].shape == trending_panel.shape
