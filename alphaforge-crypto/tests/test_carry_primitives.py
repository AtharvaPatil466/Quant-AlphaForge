"""Unit tests for carry_primitives."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.carry_primitives import (
    BasketSelection,
    compute_lookback_signal,
    compute_period_pnl_bps,
    compute_round_trip_cost_bps,
    cross_sectional_rank,
    deflated_sharpe_ratio,
    form_buckets,
    stationary_bootstrap_sharpe_ci,
)


def _funding_panel():
    rows = []
    for sym, rates in [
        ("BTCUSDT", [0.0001, 0.0001, 0.0002, 0.0003, 0.0002, 0.0001]),
        ("ETHUSDT", [-0.0001, -0.0001, 0.0000, 0.0001, 0.0002, 0.0003]),
        ("XYZUSDT", [0.0005, 0.0006, 0.0004, 0.0005, 0.0004, 0.0003]),
    ]:
        for i, r in enumerate(rates):
            rows.append({"symbol": sym, "funding_time": i, "funding_rate": r})
    return pd.DataFrame(rows)


def test_lookback_signal_excludes_current_event() -> None:
    panel = _funding_panel()
    sig = compute_lookback_signal(panel, lookback_K=2, method="mean")
    btc = sig[sig["symbol"] == "BTCUSDT"].sort_values("funding_time")
    # At funding_time=2, lookback covers events 0 and 1 → mean(0.0001, 0.0001) = 0.0001
    assert btc.iloc[0]["signal"] != btc.iloc[0]["signal"]  # NaN (insufficient lookback)
    assert btc.iloc[1]["signal"] != btc.iloc[1]["signal"]  # NaN
    assert abs(btc.iloc[2]["signal"] - 0.0001) < 1e-12
    # At funding_time=3, lookback covers events 1 and 2 → mean(0.0001, 0.0002) = 0.00015
    assert abs(btc.iloc[3]["signal"] - 0.00015) < 1e-12


def test_lookback_signal_invalid_K() -> None:
    with pytest.raises(ValueError):
        compute_lookback_signal(_funding_panel(), lookback_K=0)


def test_cross_sectional_rank_zscore_zero_mean() -> None:
    panel = _funding_panel()
    sig = compute_lookback_signal(panel, lookback_K=1, method="mean")
    cs = cross_sectional_rank(sig, method="zscore").dropna(subset=["cs_score"])
    # At each funding_time the zscore across symbols should sum to zero.
    sums = cs.groupby("funding_time")["cs_score"].sum()
    for v in sums:
        assert abs(v) < 1e-10


def test_form_buckets_short_high_funding_direction() -> None:
    cs = pd.DataFrame([
        {"symbol": "A", "funding_time": 0, "cs_score": 2.0},
        {"symbol": "B", "funding_time": 0, "cs_score": 1.0},
        {"symbol": "C", "funding_time": 0, "cs_score": 0.0},
        {"symbol": "D", "funding_time": 0, "cs_score": -1.0},
        {"symbol": "E", "funding_time": 0, "cs_score": -2.0},
    ])
    # min_eligible relaxed for the test
    out = form_buckets(cs, n_buckets=5, direction="short_high_funding", min_eligible=1)
    sel = out[0]
    # H1: short the highest-funding symbol (A), long the lowest (E)
    assert sel.short_symbols == ("A",)
    assert sel.long_symbols == ("E",)


def test_form_buckets_long_high_funding_direction() -> None:
    cs = pd.DataFrame([
        {"symbol": "A", "funding_time": 0, "cs_score": 2.0},
        {"symbol": "B", "funding_time": 0, "cs_score": -2.0},
    ])
    out = form_buckets(cs, n_buckets=2, direction="long_high_funding", min_eligible=1)
    assert out[0].long_symbols == ("A",)
    assert out[0].short_symbols == ("B",)


def test_form_buckets_invalid_direction_rejected() -> None:
    cs = pd.DataFrame([{"symbol": "A", "funding_time": 0, "cs_score": 1.0}])
    with pytest.raises(ValueError):
        form_buckets(cs, direction="auto", min_eligible=1)


def test_period_pnl_short_perp_collects_positive_funding() -> None:
    pnl = compute_period_pnl_bps(
        perp_side="short", funding_rate=0.0001,
        spot_return_pct=0.0, perp_return_pct=0.0,
    )
    assert pnl == 1.0


def test_period_pnl_long_perp_pays_funding_and_borrow() -> None:
    pnl = compute_period_pnl_bps(
        perp_side="long", funding_rate=0.0001,
        spot_return_pct=0.0, perp_return_pct=0.0,
        spot_borrow_bps_period=0.5,
    )
    assert pnl == -1.0 - 0.5


def test_period_pnl_basis_drift() -> None:
    # short perp + long spot: if spot ticks up 10 bps but perp doesn't, we gain 10 bps
    pnl = compute_period_pnl_bps(
        perp_side="short", funding_rate=0.0,
        spot_return_pct=0.001, perp_return_pct=0.0,
    )
    assert pnl == 10.0


def test_round_trip_cost_matches_cost_model_default() -> None:
    cost = compute_round_trip_cost_bps(
        perp_taker_bps=4.0, spot_taker_bps=10.0, slippage_bps_per_leg=2.0,
    )
    assert cost == 36.0


def test_stationary_bootstrap_returns_valid_interval() -> None:
    rng = np.random.default_rng(42)
    # autocorrelated returns
    r = np.zeros(500)
    for i in range(1, 500):
        r[i] = 0.3 * r[i - 1] + rng.normal(0.01, 0.05)
    point, lo, hi = stationary_bootstrap_sharpe_ci(r, n_resamples=200, seed=42)
    assert lo <= point <= hi
    assert hi > lo


def test_dsr_decreases_with_more_trials() -> None:
    sharpe = 1.0
    dsr_1 = deflated_sharpe_ratio(
        sharpe, n_trials=1, skewness=0.0, kurtosis=3.0, n_observations=250,
    )
    dsr_50 = deflated_sharpe_ratio(
        sharpe, n_trials=50, skewness=0.0, kurtosis=3.0, n_observations=250,
    )
    assert dsr_50 < dsr_1, "DSR should decrease as trial count rises"


def test_dsr_increases_with_higher_sharpe() -> None:
    dsr_low = deflated_sharpe_ratio(
        0.5, n_trials=10, skewness=0.0, kurtosis=3.0, n_observations=250,
    )
    dsr_high = deflated_sharpe_ratio(
        2.0, n_trials=10, skewness=0.0, kurtosis=3.0, n_observations=250,
    )
    assert dsr_high > dsr_low
