"""Unit tests for the kill-switch trigger + ladder + re-arm logic."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd
import pytest

from risk.kill_switch import (
    KillSwitch,
    compute_unwind_target_weights,
    DEFAULT_LADDER,
)
from storage.database import get_connection


def _history(n_days: int = 30, n_tickers: int = 6, adv_usd: float = 5e7) -> Dict[str, pd.DataFrame]:
    idx = pd.date_range("2024-01-01", periods=n_days, freq="B")
    out = {}
    for i in range(n_tickers):
        px = 100.0 + np.arange(n_days) * 0.01
        vol = np.full(n_days, adv_usd / px.mean())
        out[f"T{i}"] = pd.DataFrame({"Close": px, "Volume": vol}, index=idx)
    return out


def _cfg(**overrides):
    base = {
        "execution": {"starting_nav": 100_000.0, "slippage_bps": 5.0},
        "kill_switch": {
            "enabled": True,
            "triggers": {
                "max_drawdown_pct": 0.15,
                "single_day_loss_pct": 0.05,
                "consecutive_losing_days": 5,
                "realized_slippage_median_bps": 50.0,
                "realized_cum_drag_vs_nav_pct": 0.02,
                "min_liquid_tickers": 3,
            },
            "unwind_ladder": [[0.25, 0], [0.50, 4], [1.00, 24]],
            "notifications": {"pager_file": "pager.log",
                              "also_write_sqlite_event": False},
        },
    }
    for k, v in overrides.items():
        base[k] = v
    return base


class TestTriggers:
    def test_max_drawdown_fires(self, tmp_path):
        ks = KillSwitch(_cfg(), pager_path=tmp_path / "pager.log")
        ks.end_of_day("2024-01-05", daily_return=0.0, drawdown=0.20,
                       history=_history(), nav=80_000.0)
        assert ks.state.halted
        assert any("max_drawdown_pct" in r for r in ks.state.halt_reasons)

    def test_single_day_loss_fires(self, tmp_path):
        ks = KillSwitch(_cfg(), pager_path=tmp_path / "pager.log")
        ks.end_of_day("2024-01-05", daily_return=-0.07, drawdown=0.05,
                       history=_history(), nav=93_000.0)
        assert ks.state.halted
        assert any("single_day_loss_pct" in r for r in ks.state.halt_reasons)

    def test_consecutive_losses_fires(self, tmp_path):
        ks = KillSwitch(_cfg(), pager_path=tmp_path / "pager.log")
        # 5 losing days in a row — matches the trigger threshold
        for i in range(5):
            ks.end_of_day(f"2024-01-{i+1:02d}", daily_return=-0.001,
                          drawdown=0.01, history=_history(), nav=99_000.0)
        assert ks.state.halted
        assert any("consecutive_losing_days" in r for r in ks.state.halt_reasons)

    def test_consecutive_losses_reset_on_positive_day(self, tmp_path):
        ks = KillSwitch(_cfg(), pager_path=tmp_path / "pager.log")
        for _ in range(3):
            ks.end_of_day("2024-01-01", daily_return=-0.001, drawdown=0.01,
                          history=_history(), nav=99_000.0)
        ks.end_of_day("2024-01-04", daily_return=+0.001, drawdown=0.0,
                      history=_history(), nav=99_100.0)
        for _ in range(3):
            ks.end_of_day("2024-01-05", daily_return=-0.001, drawdown=0.01,
                          history=_history(), nav=98_000.0)
        assert not ks.state.halted

    def test_illiquid_universe_fires(self, tmp_path):
        ks = KillSwitch(_cfg(), pager_path=tmp_path / "pager.log")
        thin_hist = _history(adv_usd=1e6)  # below $10M floor
        ks.end_of_day("2024-01-05", daily_return=0.0, drawdown=0.0,
                       history=thin_hist, nav=100_000.0)
        assert ks.state.halted
        assert any("min_liquid_tickers" in r for r in ks.state.halt_reasons)


class TestDBTriggers:
    def test_realized_slippage_median(self, tmp_path):
        db = tmp_path / "exec.db"
        conn = get_connection(db)
        for i in range(40):
            conn.execute(
                """INSERT INTO orders
                   (order_id, date, ticker, side, quantity, fill_price,
                    fill_quantity, status, slippage_bps, tx_cost)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (f"o{i}", "2024-01-05", "AAPL", "BUY", 10.0, 100.0, 10.0,
                 "FILLED", 80.0, 1.0),
            )
        conn.commit()
        ks = KillSwitch(_cfg(), db_conn=conn, pager_path=tmp_path / "pager.log")
        ks.end_of_day("2024-01-05", daily_return=0.0, drawdown=0.0,
                       history=_history(), nav=100_000.0)
        assert ks.state.halted
        assert any("realized_slippage_median_bps" in r for r in ks.state.halt_reasons)


class TestLadderAndRearm:
    def test_unwind_same_day_then_flat(self):
        cw = {"AAPL": 0.10, "MSFT": 0.10, "GOOG": -0.05}
        # Same-session target is max rung with hours < 24 → 0.50 with default ladder
        new_w, frac = compute_unwind_target_weights(cw, 0.50, 0.0)
        assert frac == pytest.approx(0.50)
        # All weights halved
        for t in cw:
            assert new_w[t] == pytest.approx(cw[t] * 0.5)

    def test_unwind_target_fraction_schedule(self, tmp_path):
        ks = KillSwitch(_cfg(), pager_path=tmp_path / "pager.log")
        # Not halted → 0
        assert ks.unwind_target_fraction_today("2024-01-05") == 0.0
        # Halt
        ks.end_of_day("2024-01-05", daily_return=-0.07, drawdown=0.05,
                       history=_history(), nav=93_000.0)
        # Same day target is the max of rungs with hours < 24 (=0.50)
        assert ks.unwind_target_fraction_today("2024-01-05") == pytest.approx(0.50)
        # Next day target is the >=24h rung (=1.00)
        assert ks.unwind_target_fraction_today("2024-01-06") == pytest.approx(1.00)

    def test_pager_ack_rearms(self, tmp_path):
        pager = tmp_path / "pager.log"
        ks = KillSwitch(_cfg(), pager_path=pager)
        ks.end_of_day("2024-01-05", daily_return=-0.07, drawdown=0.05,
                       history=_history(), nav=93_000.0)
        assert ks.state.halted
        # Append an ACK line and call end_of_day again on the next trading day.
        with open(pager, "a") as f:
            f.write("ACK: operator confirmed, proceed\n")
        ks.end_of_day("2024-01-08", daily_return=0.0, drawdown=0.0,
                       history=_history(), nav=93_500.0)
        assert not ks.state.halted

    def test_blocks_new_entries_flag(self, tmp_path):
        ks = KillSwitch(_cfg(), pager_path=tmp_path / "pager.log")
        assert not ks.blocks_new_entries()
        ks.end_of_day("2024-01-05", daily_return=-0.07, drawdown=0.05,
                       history=_history(), nav=93_000.0)
        assert ks.blocks_new_entries()


class TestDisabled:
    def test_disabled_never_halts(self, tmp_path):
        cfg = _cfg()
        cfg["kill_switch"]["enabled"] = False
        ks = KillSwitch(cfg, pager_path=tmp_path / "pager.log")
        ks.end_of_day("2024-01-05", daily_return=-0.20, drawdown=0.50,
                       history=_history(), nav=50_000.0)
        assert not ks.state.halted
