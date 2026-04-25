"""Unit tests for the new factor_study helpers (C4, D2, D4)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.factor_study import (
    build_factor_panels,
    sector_neutralize,
    split_train_test,
    slice_metrics,
)


@pytest.fixture
def toy_panel():
    """Deterministic 600-day × 12-ticker OHLCV panel — enough to exercise
    the 252-day momentum + 60-day rolling-regression windows."""
    rng = np.random.default_rng(0)
    n, k = 600, 12
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    tickers = [f"T{i}" for i in range(k)]
    drift = rng.uniform(-0.0005, 0.001, size=k)
    shocks = rng.normal(0, 0.015, size=(n, k))
    log_rets = shocks + drift
    prices = pd.DataFrame(100.0 * np.exp(np.cumsum(log_rets, axis=0)),
                          index=idx, columns=tickers)
    volume = pd.DataFrame(rng.uniform(1e6, 5e6, size=(n, k)),
                          index=idx, columns=tickers)
    return prices, volume


class TestBuildFactorPanelsExpanded:
    def test_all_eight_factors_present(self, toy_panel):
        close, vol = toy_panel
        panels = build_factor_panels(close, vol)
        assert set(panels) == {
            "Momentum (12-1)", "Mean Reversion (5d)", "Volume Surge",
            "RSI Divergence", "Earnings Drift",
            "Amihud Illiquidity", "Idiosyncratic Volatility",
            "Residual Reversal (5d)",
        }

    def test_new_panels_shape_and_finiteness(self, toy_panel):
        close, vol = toy_panel
        panels = build_factor_panels(close, vol)
        for name in ("Amihud Illiquidity", "Idiosyncratic Volatility",
                     "Residual Reversal (5d)"):
            p = panels[name]
            assert p.shape == close.shape
            # After the longest window (252 for momentum, 60 for IVOL/RR),
            # the last 200 rows should be populated.
            tail = p.iloc[-200:]
            assert tail.notna().to_numpy().mean() > 0.9, name

    def test_ivol_is_non_positive(self, toy_panel):
        """IVOL is negated annualized vol; valid values are ≤ 0."""
        close, vol = toy_panel
        ivol = build_factor_panels(close, vol)["Idiosyncratic Volatility"]
        vals = ivol.dropna(how="all").to_numpy()
        finite = vals[np.isfinite(vals)]
        assert (finite <= 1e-9).all()


class TestSectorNeutralize:
    def test_sector_means_are_zero(self, toy_panel):
        close, vol = toy_panel
        sector_map = {t: ("A" if i < 6 else "B")
                      for i, t in enumerate(close.columns)}
        mom = (close.shift(21) - close.shift(252)) / close.shift(252)
        neut = sector_neutralize(mom, sector_map)
        # Pick a date well into the window
        row = neut.iloc[-5]
        a_cols = [c for c in row.index if sector_map[c] == "A"]
        b_cols = [c for c in row.index if sector_map[c] == "B"]
        assert row[a_cols].mean() == pytest.approx(0.0, abs=1e-10)
        assert row[b_cols].mean() == pytest.approx(0.0, abs=1e-10)

    def test_singleton_sector_is_passthrough(self, toy_panel):
        """A sector with < 2 tickers can't be demeaned and is left alone."""
        close, vol = toy_panel
        # Put one ticker in its own sector
        sector_map = {t: ("A" if t != "T0" else "SOLO")
                      for t in close.columns}
        mom = (close.shift(21) - close.shift(252)) / close.shift(252)
        neut = sector_neutralize(mom, sector_map)
        pd.testing.assert_series_equal(neut["T0"], mom["T0"])


class TestTrainTestSplit:
    def test_cut_respects_embargo(self):
        idx = pd.date_range("2020-01-01", periods=2000, freq="B")
        s = pd.Series(np.arange(len(idx), dtype=float), index=idx)
        parts = split_train_test(s, oos_start="2024-01-02", embargo_days=21)
        assert parts["train"].index.max() < pd.Timestamp("2024-01-02")
        assert parts["test"].index.min() >= pd.Timestamp("2024-01-02")
        # Calendar embargo: train end at least ~42 calendar days before test start
        gap_days = (parts["test"].index.min() - parts["train"].index.max()).days
        assert gap_days >= 30

    def test_slice_metrics_on_known_series(self):
        # Constant positive return → positive Sharpe, no drawdown
        r = pd.Series([0.001] * 300)
        m = slice_metrics(r)
        assert m["n_days"] == 300
        assert m["max_drawdown"] == pytest.approx(0.0, abs=1e-12)
        assert m["ann_return"] > 0.0
