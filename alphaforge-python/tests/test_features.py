"""
Feature engineering tests — vectorized feature computations.
"""

import math
import numpy as np
import pytest

from data.features import (
    log_returns,
    volume_ratio,
    realized_vol,
    rsi,
    autocorrelation,
    hurst_exponent,
    z_score,
    normalize_cross_sectional,
)


class TestLogReturns:
    def test_basic(self):
        prices = np.array([100.0, 110.0, 105.0, 115.0])
        lr = log_returns(prices)
        assert np.isnan(lr[0])
        assert lr[1] == pytest.approx(math.log(110 / 100))
        assert lr[2] == pytest.approx(math.log(105 / 110))

    def test_window(self):
        prices = np.array([100.0, 110.0, 120.0, 130.0])
        lr = log_returns(prices, window=2)
        assert np.isnan(lr[0])
        assert np.isnan(lr[1])
        assert lr[2] == pytest.approx(math.log(120 / 100))

    def test_empty(self):
        lr = log_returns(np.array([]))
        assert len(lr) == 0


class TestVolumeRatio:
    def test_constant_volume(self):
        vols = np.full(30, 1e6)
        vr = volume_ratio(vols, window=20)
        assert vr[20] == pytest.approx(1.0)

    def test_spike(self):
        vols = np.full(30, 1e6)
        vols[25] = 3e6
        vr = volume_ratio(vols, window=20)
        assert vr[25] > 2.5


class TestRealizedVol:
    def test_zero_returns(self):
        rets = np.zeros(30)
        rv = realized_vol(rets, window=21)
        assert rv[21] == pytest.approx(0.0)

    def test_positive_vol(self):
        rng = np.random.RandomState(42)
        rets = rng.normal(0, 0.01, 100)
        rv = realized_vol(rets, window=21)
        assert rv[21] > 0
        assert rv[21] < 1.0  # ~16% annualized


class TestRSI:
    def test_range(self):
        prices = np.array([100 + i * (-1) ** i for i in range(30)], dtype=float)
        r = rsi(prices, period=14)
        finite = r[np.isfinite(r)]
        assert np.all(finite >= 0)
        assert np.all(finite <= 100)

    def test_uptrend(self):
        prices = np.arange(100, 130, dtype=float)
        r = rsi(prices, period=14)
        assert r[-1] == 100.0  # all gains, no losses → RSI=100

    def test_insufficient_data(self):
        prices = np.array([100.0, 105.0])
        r = rsi(prices, period=14)
        assert np.all(np.isnan(r))


class TestAutocorrelation:
    def test_white_noise(self):
        rng = np.random.RandomState(42)
        rets = rng.normal(0, 0.01, 200)
        ac = autocorrelation(rets, lag=1)
        finite = ac[np.isfinite(ac)]
        # White noise → autocorrelation near 0
        assert abs(np.mean(finite)) < 0.3

    def test_range(self):
        rng = np.random.RandomState(42)
        rets = rng.normal(0, 0.01, 200)
        ac = autocorrelation(rets, lag=1)
        finite = ac[np.isfinite(ac)]
        assert np.all(finite >= -1.0)
        assert np.all(finite <= 1.0)


class TestHurstExponent:
    def test_range(self):
        rng = np.random.RandomState(42)
        prices = np.cumsum(rng.normal(0, 1, 300)) + 100
        prices = np.maximum(prices, 1.0)
        h = hurst_exponent(prices, window=100)
        finite = h[np.isfinite(h)]
        assert len(finite) > 0
        assert np.all(finite >= 0.0)
        assert np.all(finite <= 1.0)

    def test_short_series(self):
        prices = np.array([100.0, 101.0, 102.0])
        h = hurst_exponent(prices, window=100)
        assert np.all(np.isnan(h))


class TestZScore:
    def test_standard(self):
        series = np.arange(300, dtype=float)
        z = z_score(series, window=252)
        finite = z[np.isfinite(z)]
        assert len(finite) > 0
        # Last z-score should be positive (above mean)
        assert z[-1] > 0

    def test_short(self):
        series = np.array([1.0, 2.0])
        z = z_score(series, window=252)
        assert np.all(np.isnan(z))


class TestNormalizeCrossSectional:
    def test_1d(self):
        row = np.array([10.0, 20.0, 30.0, 40.0, 50.0])
        normed = normalize_cross_sectional(row)
        assert normed.shape == (5,)
        assert abs(np.mean(normed)) < 1e-10
        assert abs(np.std(normed, ddof=1) - 1.0) < 0.01

    def test_2d(self):
        matrix = np.array([
            [10.0, 20.0, 30.0],
            [1.0, 2.0, 3.0],
        ])
        normed = normalize_cross_sectional(matrix)
        assert normed.shape == (2, 3)
        for i in range(2):
            assert abs(np.mean(normed[i])) < 1e-10

    def test_nan_handling(self):
        row = np.array([10.0, np.nan, 30.0, 40.0, 50.0])
        normed = normalize_cross_sectional(row)
        assert normed[1] == 0.0
        assert np.isfinite(normed[0])
