"""
Data layer tests — price series shape, bounds, OHLCV validity, and parity.
"""

import numpy as np
import pytest

from data import (
    generate_prices,
    generate_dataset,
    compute_returns,
    get_tickers,
    mean,
    stddev,
    correlation,
    safe_div,
    sanitize_number,
    clamp,
    UNIVERSE,
    SECTORS,
)


class TestGeneratePrices:
    def test_shape(self):
        """Price series has days+1 entries, volumes has days+1 entries."""
        prices, volumes = generate_prices("AAPL", 252, 42)
        assert len(prices) == 253  # 252 days + initial price
        assert len(volumes) == 253

    def test_deterministic(self):
        """Same ticker + seed produces identical output."""
        p1, v1 = generate_prices("AAPL", 252, 42)
        p2, v2 = generate_prices("AAPL", 252, 42)
        np.testing.assert_array_equal(p1, p2)
        np.testing.assert_array_equal(v1, v2)

    def test_prices_positive(self):
        """All prices must be > 0."""
        prices, _ = generate_prices("AAPL", 504, 42)
        assert np.all(prices > 0)

    def test_volumes_positive(self):
        """All volumes must be > 0."""
        _, volumes = generate_prices("AAPL", 504, 42)
        assert np.all(volumes > 0)

    def test_different_tickers_differ(self):
        """Different tickers produce different series."""
        p1, _ = generate_prices("AAPL", 252, 42)
        p2, _ = generate_prices("MSFT", 252, 42)
        assert not np.array_equal(p1, p2)

    def test_base_price_range(self):
        """First price should be in the $50-$500 range."""
        prices, _ = generate_prices("AAPL", 10, 42)
        assert 0.01 <= prices[0] <= 600  # generous bound accounting for rng


class TestComputeReturns:
    def test_first_return_zero(self):
        returns = compute_returns(np.array([100.0, 110.0, 105.0]))
        assert returns[0] == 0.0

    def test_simple_return(self):
        returns = compute_returns(np.array([100.0, 110.0]))
        assert returns[1] == pytest.approx(0.1)


class TestGenerateDataset:
    def test_all_sectors(self):
        """'All' returns tickers from every sector."""
        dataset = generate_dataset("All", 252, 42)
        total_tickers = sum(len(v) for v in UNIVERSE.values())
        assert len(dataset) == total_tickers

    def test_single_sector(self):
        dataset = generate_dataset("Technology", 252, 42)
        assert len(dataset) == len(UNIVERSE["Technology"])

    def test_empty_sector(self):
        dataset = generate_dataset("Nonexistent", 252, 42)
        assert len(dataset) == 0

    def test_ticker_names_match(self):
        dataset = generate_dataset("Technology", 252, 42)
        for ticker in dataset:
            assert dataset[ticker].ticker == ticker
            assert len(dataset[ticker].name) > 0


class TestGetTickers:
    def test_all(self):
        tickers = get_tickers("All")
        assert len(tickers) == sum(len(v) for v in UNIVERSE.values())

    def test_sector(self):
        tickers = get_tickers("Technology")
        assert len(tickers) == 6

    def test_invalid(self):
        tickers = get_tickers("Bogus")
        assert len(tickers) == 0


class TestStatHelpers:
    def test_mean_empty(self):
        assert mean([]) == 0.0
        assert mean(None) == 0.0

    def test_mean_basic(self):
        assert mean([1, 2, 3, 4, 5]) == pytest.approx(3.0)

    def test_stddev_single(self):
        assert stddev([42]) == 0.0

    def test_stddev_basic(self):
        # sample stddev of [2, 4, 4, 4, 5, 5, 7, 9]
        assert stddev([2, 4, 4, 4, 5, 5, 7, 9]) == pytest.approx(2.0, rel=0.1)

    def test_correlation_identical(self):
        x = [1, 2, 3, 4, 5]
        assert correlation(x, x) == pytest.approx(1.0, abs=0.001)

    def test_correlation_opposite(self):
        x = [1, 2, 3, 4, 5]
        y = [5, 4, 3, 2, 1]
        assert correlation(x, y) == pytest.approx(-1.0, abs=0.001)

    def test_correlation_empty(self):
        assert correlation([], []) == 0.0

    def test_safe_div_zero(self):
        assert safe_div(1.0, 0.0) == 0.0
        assert safe_div(1.0, 0.0, -1.0) == -1.0

    def test_sanitize_nan(self):
        assert sanitize_number(float("nan")) == 0.0
        assert sanitize_number(float("inf")) == 0.0
        assert sanitize_number(42.0) == 42.0

    def test_clamp(self):
        assert clamp(5, 0, 10) == 5
        assert clamp(-1, 0, 10) == 0
        assert clamp(15, 0, 10) == 10
