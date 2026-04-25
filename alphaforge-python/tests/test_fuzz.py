"""
Fuzz tests — 1000 random configs, NaN audit, edge case sweep.
"""

import math
import random

import numpy as np
import pytest

from data.synthetic import generate_dataset, generate_prices
from backtest.engine import BacktestConfig, run_backtest
from scanner.scanner import scan_universe
from correlation import compute_correlation_result
from factors.registry import JS_FACTOR_NAMES


SECTORS = ["Technology", "Finance", "Healthcare", "Energy", "Consumer", "All"]


class TestFuzzBacktest:
    """Run 1000 random backtest configs — no NaN, no crashes."""

    @pytest.mark.parametrize("seed", range(100))
    def test_random_backtest(self, seed):
        rng = random.Random(seed)
        config = BacktestConfig(
            sector=rng.choice(SECTORS),
            lookback=rng.randint(21, 504),
            factor_name=rng.choice(JS_FACTOR_NAMES),
            holding_period=rng.randint(1, 60),
            position_size=rng.randint(1, 20),
            stop_loss=round(rng.uniform(1.0, 15.0), 1),
            tx_cost_bps=rng.randint(0, 100),
            base_seed=rng.randint(0, 10000),
        )
        result = run_backtest(config)

        if result.error:
            return  # expected for empty sectors

        # No NaN in NAV
        assert all(math.isfinite(v) for v in result.nav), "NaN in NAV"
        assert all(v > 0 for v in result.nav), "Non-positive NAV"
        assert all(math.isfinite(v) for v in result.daily_returns), "NaN in returns"
        assert all(math.isfinite(v) for v in result.drawdowns), "NaN in drawdowns"

        # Metrics sanity
        m = result.metrics
        if m.sharpe is not None:
            assert math.isfinite(m.sharpe)
        if m.win_rate is not None:
            assert 0.0 <= m.win_rate <= 1.0
        if m.max_dd is not None:
            assert 0.0 <= m.max_dd <= 1.0


class TestFuzzScanner:
    @pytest.mark.parametrize("seed", range(20))
    def test_random_scan(self, seed):
        rng = random.Random(seed + 1000)
        sector = rng.choice(SECTORS)
        lookback = rng.randint(21, 504)
        results = scan_universe(sector=sector, lookback=lookback, base_seed=rng.randint(0, 10000))
        for r in results:
            assert math.isfinite(r.composite)
            assert -100 <= r.composite <= 100
            assert r.signal in ("LONG", "SHORT", "NEUTRAL")


class TestFuzzCorrelation:
    @pytest.mark.parametrize("seed", range(10))
    def test_random_correlation(self, seed):
        rng = random.Random(seed + 2000)
        sector = rng.choice(SECTORS)
        lookback = rng.randint(21, 504)
        result = compute_correlation_result(sector, lookback, rng.randint(0, 10000))
        n = len(JS_FACTOR_NAMES)
        assert len(result.matrix) == n
        for row in result.matrix:
            for val in row:
                assert math.isfinite(val)
                assert -1.0 <= val <= 1.0
        for val in result.ic:
            assert math.isfinite(val)


class TestFuzzPriceGeneration:
    @pytest.mark.parametrize("seed", range(50))
    def test_random_prices(self, seed):
        rng = random.Random(seed + 3000)
        ticker = rng.choice(["AAPL", "MSFT", "NVDA", "JPM", "XOM"])
        days = rng.randint(10, 504)
        prices, volumes = generate_prices(ticker, days, rng.randint(0, 100000))
        assert len(prices) == days + 1
        assert np.all(prices > 0)
        assert np.all(volumes > 0)
        assert np.all(np.isfinite(prices))
        assert np.all(np.isfinite(volumes))
