"""Unit tests for the self-contained KS helper and end-to-end reconciliation."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pytest

from research.slippage_reconciliation import _ks_two_sample, reconcile
from storage.database import get_connection


class TestKSTwoSample:
    def test_identical_distributions_large_p(self):
        rng = np.random.default_rng(0)
        a = rng.normal(0, 1, 500)
        b = rng.normal(0, 1, 500)
        d, p = _ks_two_sample(a, b)
        assert p > 0.05
        assert 0.0 <= d <= 1.0

    def test_different_distributions_small_p(self):
        rng = np.random.default_rng(1)
        a = rng.normal(0, 1, 500)
        b = rng.normal(5, 1, 500)  # very different mean
        d, p = _ks_two_sample(a, b)
        assert p < 0.01
        assert d > 0.5

    def test_too_few_samples(self):
        d, p = _ks_two_sample(np.array([1.0]), np.array([1.0]))
        assert d == 0.0 and p == 1.0


def _make_db_with_orders(path: Path, realized_bps_list):
    conn = get_connection(path)
    for i, bps in enumerate(realized_bps_list):
        conn.execute(
            """INSERT INTO orders
               (order_id, date, ticker, side, quantity, fill_price,
                fill_quantity, status, slippage_bps, tx_cost)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (f"ord{i}", "2026-01-02", "AAPL", "BUY", 10.0, 100.0,
             10.0, "FILLED", float(bps), 1.0),
        )
    conn.commit()
    conn.close()


class TestReconcileSmoke:
    def test_zero_drag_when_realized_matches_simulated(self, tmp_path):
        db = tmp_path / "exec.db"
        _make_db_with_orders(db, [5.0] * 50)
        out = reconcile(db, simulated_bps=5.0)
        assert out["n_orders"] == 50
        assert out["cumulative_drag_usd"] == pytest.approx(0.0, abs=1e-9)
        assert out["fill_error_bps_stats"]["mean"] == pytest.approx(0.0)

    def test_positive_drag_when_realized_worse(self, tmp_path):
        db = tmp_path / "exec.db"
        _make_db_with_orders(db, [15.0] * 50)  # 10bps worse than simulated
        out = reconcile(db, simulated_bps=5.0)
        # 50 orders × $1000 × 10bps = $50
        assert out["cumulative_drag_usd"] == pytest.approx(50.0, rel=1e-9)
        assert out["fill_error_bps_stats"]["mean"] == pytest.approx(10.0)
