"""Unit tests for the assumed-vs-realized cost calibration math.

These test the calibration arithmetic on KNOWN synthetic slippage arrays
(e.g. realized 2x assumed -> multiplier 2.0) and the database-provenance
classifier that separates simulated paper-broker fills (assumption echoed
back, circular) from genuine live fills.
"""

from __future__ import annotations

import numpy as np
import pytest

from research.cost_calibration import (
    calibrate,
    classify_db,
    cost_multiplier,
    implied_impact_k,
    slippage_distribution,
)
from research.slippage_reconciliation import load_orders  # noqa: F401  (loader reuse)
from storage.database import get_connection


class TestCostMultiplier:
    def test_realized_double_assumed_gives_two(self):
        # Realized slippage is uniformly 2x the assumption -> multiplier 2.0
        realized = np.full(50, 10.0)
        assert cost_multiplier(realized, assumed_bps=5.0, statistic="median") == pytest.approx(2.0)
        assert cost_multiplier(realized, assumed_bps=5.0, statistic="mean") == pytest.approx(2.0)

    def test_realized_equals_assumed_gives_one(self):
        realized = np.full(20, 5.0)
        assert cost_multiplier(realized, assumed_bps=5.0) == pytest.approx(1.0)

    def test_median_robust_to_outliers_mean_is_not(self):
        # 9 fills at the assumption, 1 extreme fill. Median ignores it; mean doesn't.
        realized = np.array([5.0] * 9 + [500.0])
        assert cost_multiplier(realized, 5.0, "median") == pytest.approx(1.0)
        assert cost_multiplier(realized, 5.0, "mean") > 10.0

    def test_nonpositive_assumed_is_nan(self):
        assert np.isnan(cost_multiplier(np.array([5.0]), assumed_bps=0.0))

    def test_empty_realized_is_nan(self):
        assert np.isnan(cost_multiplier(np.array([]), assumed_bps=5.0))


class TestSlippageDistribution:
    def test_basic_stats(self):
        s = slippage_distribution(np.array([1.0, 2.0, 3.0, 4.0, 5.0]))
        assert s["n"] == 5
        assert s["median"] == pytest.approx(3.0)
        assert s["mean"] == pytest.approx(3.0)
        assert s["min"] == pytest.approx(1.0)
        assert s["max"] == pytest.approx(5.0)

    def test_drops_non_finite(self):
        s = slippage_distribution(np.array([1.0, np.nan, 3.0, np.inf]))
        assert s["n"] == 2
        assert s["median"] == pytest.approx(2.0)


class TestImpactKIdentifiability:
    def test_k_not_identifiable_without_participation(self):
        out = implied_impact_k(np.array([10.0, 20.0]), participation=None)
        assert out["identifiable"] is False
        assert out["k_bps"] is None

    def test_k_recovered_when_participation_present(self):
        # impact_bps = k * sqrt(participation); choose k=15, participation=0.04
        # -> sqrt = 0.2 -> impact = 3.0 bps
        part = np.full(10, 0.04)
        realized = np.full(10, 3.0)
        out = implied_impact_k(realized, participation=part)
        assert out["identifiable"] is True
        assert out["k_bps"] == pytest.approx(15.0)
        assert out["k_multiplier"] == pytest.approx(1.0)


class TestClassifyDb:
    def test_constant_slippage_is_simulated(self):
        orders = [{"status": "FILLED", "ticker": "A", "slippage_bps": 5.0} for _ in range(10)]
        assert classify_db(orders) == "simulated"

    def test_varied_slippage_is_live(self):
        orders = [{"status": "FILLED", "ticker": "A", "slippage_bps": v}
                  for v in (5.0, 140.0, -9.0)]
        assert classify_db(orders) == "live"

    def test_empty_is_empty(self):
        assert classify_db([]) == "empty"


def _make_db(path, slippage_list):
    conn = get_connection(path)
    for i, bps in enumerate(slippage_list):
        conn.execute(
            """INSERT INTO orders
               (order_id, date, ticker, side, quantity, fill_price,
                fill_quantity, status, slippage_bps, tx_cost)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (f"o{i}", "2026-01-02", "AAPL", "BUY", 10.0, 100.0,
             10.0, "FILLED", float(bps), 1.0),
        )
    conn.commit()
    conn.close()


class TestCalibrateEndToEnd:
    def test_live_db_yields_multiplier(self, tmp_path):
        db = tmp_path / "live.db"
        _make_db(db, [10.0, 10.0, 10.0, 12.0, 8.0])  # varied -> live; median 10
        out = calibrate([db], assumed_bps=5.0)
        assert out["live_fills_found"] is True
        assert out["n_live_fills"] == 5
        assert out["cost_multiplier"]["median"] == pytest.approx(2.0)
        assert out["impact_k_calibration"]["identifiable"] is False

    def test_simulated_db_flagged_circular(self, tmp_path):
        db = tmp_path / "sim.db"
        _make_db(db, [5.0] * 30)  # constant -> simulated
        out = calibrate([db], assumed_bps=5.0)
        assert out["live_fills_found"] is False
        entry = out["databases"][0]
        assert entry["kind"] == "simulated"
        assert entry["multiplier_median"] == pytest.approx(1.0)
        assert "warning" in entry

    def test_missing_db_reported_not_crashed(self, tmp_path):
        out = calibrate([tmp_path / "nope.db"], assumed_bps=5.0)
        assert out["databases"][0]["exists"] is False
        assert out["live_fills_found"] is False
