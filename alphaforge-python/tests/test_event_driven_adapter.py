"""Regression test for `backtest.event_driven_adapter`.

Exercises the legacy `BacktestConfig` → `BacktestResult` API surface
running through `EventDrivenEngine`. This is the contract that lets
`api/routes/backtest.py` swap engines without changing the response
schema (per ENGINE_CONSOLIDATION_DESIGN.md §4).

Numerical equivalence to the legacy `real_engine.run_real_backtest` is
NOT asserted — see the design memo for why.
"""

from __future__ import annotations

import math
from datetime import date

import pytest

from backtest.event_driven_adapter import run_real_backtest_via_event_driven
from backtest.synthetic_demo import BacktestConfig, BacktestResult


def _has_real_market_data() -> bool:
    """Skip the test if the local parquet store isn't populated. Most
    CI environments don't carry yfinance data; developer workstations do."""
    from data.market.loader import MarketDataLoader

    try:
        loader = MarketDataLoader()
        # Use a single well-known ticker as the smoke check.
        df = loader.load_history(["AAPL"], min_rows=2).get("AAPL")
        return df is not None and not df.empty
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _has_real_market_data(),
    reason="local parquet market-data store not populated",
)


@pytest.fixture(scope="module")
def basic_result() -> BacktestResult:
    config = BacktestConfig(
        sector="Technology",
        lookback=63,
        factor_name="Momentum (12-1)",
        holding_period=21,
        position_size=20,
        stop_loss=10.0,
        tx_cost_bps=5,
    )
    return run_real_backtest_via_event_driven(config, end_date="2025-12-31")


def test_adapter_returns_backtest_result_shape(basic_result: BacktestResult):
    assert basic_result.error is None, f"adapter errored: {basic_result.error}"
    assert isinstance(basic_result, BacktestResult)
    # Lists must be populated and have consistent lengths
    assert len(basic_result.nav) >= 2
    assert len(basic_result.benchmark_nav) == len(basic_result.nav)
    # daily_returns and drawdowns are length nav-1 in the legacy schema
    assert len(basic_result.daily_returns) == len(basic_result.nav) - 1
    assert len(basic_result.drawdowns) == len(basic_result.nav) - 1


def test_adapter_metrics_are_finite(basic_result: BacktestResult):
    m = basic_result.metrics
    assert m.sharpe is None or math.isfinite(m.sharpe)
    assert m.total_return is None or math.isfinite(m.total_return)
    assert m.bench_return is None or math.isfinite(m.bench_return)
    assert m.max_dd is None or math.isfinite(m.max_dd)
    assert m.ann_vol is None or math.isfinite(m.ann_vol)
    assert m.calmar is None or math.isfinite(m.calmar)


def test_adapter_nav_starts_at_100(basic_result: BacktestResult):
    """The legacy contract is NAV expressed on a base-100 scale."""
    assert basic_result.nav[0] == pytest.approx(100.0, abs=1e-6)
    assert basic_result.benchmark_nav[0] == pytest.approx(100.0, abs=1e-6)


def test_adapter_nav_values_strictly_positive(basic_result: BacktestResult):
    assert all(n > 0 for n in basic_result.nav)
    assert all(b > 0 for b in basic_result.benchmark_nav)


def test_adapter_drawdowns_in_unit_interval(basic_result: BacktestResult):
    assert all(0.0 <= d <= 1.0 for d in basic_result.drawdowns)


def test_adapter_portfolio_actually_trades(basic_result: BacktestResult):
    """Sanity: the portfolio NAV must move from its starting value of 100.

    A flat NAV across the entire window means orders are being silently
    skipped — this exact regression occurred during session 3 development
    when EngineConfig.min_order_notional=100 (default) clashed with
    initial_cash=100, sizing all orders below the notional floor."""
    nav = basic_result.nav
    assert len(set(round(n, 4) for n in nav)) > 1, (
        f"NAV is constant — strategy never traded. "
        f"All {len(nav)} marks equal {nav[0]:.4f}."
    )


def test_adapter_benchmark_diverges_from_portfolio(basic_result: BacktestResult):
    """Sanity: an active strategy's NAV should differ from the equal-
    weight benchmark over a meaningful window."""
    nav = basic_result.nav
    bench = basic_result.benchmark_nav
    assert len(nav) == len(bench) and len(nav) > 5
    diffs = [abs(n - b) for n, b in zip(nav, bench)]
    assert max(diffs) > 0.5, "portfolio NAV is essentially equal to benchmark — strategy may be flat"
