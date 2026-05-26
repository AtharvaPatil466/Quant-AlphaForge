"""Kill-switch enforcement.

Reads the ``kill_switch:`` section of ``configs/execution_config.yaml`` and
evaluates the configured triggers at the end of every trading day. When
any trigger fires, the switch engages and:

  * Blocks new entries on subsequent days.
  * Walks the ``unwind_ladder`` across days, emitting SELL / BUY-TO-COVER
    orders that close down the book on the prescribed schedule.
  * Writes a pager line (timestamp + reason) to ``pager_file`` so human
    operators can acknowledge.

Re-arming requires a line in the pager file starting with ``ACK:``
(operator confirmation). Without it, the halt persists.

Triggers sit in one class so the config is the single source of truth.
The class is stateful — one instance lives on ``ExecutionEngine``.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

import pandas as pd


DEFAULT_TRIGGERS = {
    "max_drawdown_pct": 0.15,
    "single_day_loss_pct": 0.05,
    "consecutive_losing_days": 10,
    "realized_slippage_median_bps": 50.0,
    "realized_cum_drag_vs_nav_pct": 0.02,
    "min_liquid_tickers": 3,
}

DEFAULT_LADDER: List[List[float]] = [
    [0.25, 0.0],   # 25% of remaining book immediately
    [0.50, 4.0],   # 50% cumulative by +4h  (same session for a daily loop)
    [1.00, 24.0],  # flat by next session
]

_MIN_ADV_USD = 10_000_000.0


@dataclass
class KillSwitchState:
    halted: bool = False
    halt_date: Optional[str] = None
    halt_reasons: List[str] = field(default_factory=list)
    consecutive_losing_days: int = 0
    # Fraction of notional closed so far *relative to the book at halt time*.
    # Used to walk the unwind ladder without over-selling.
    fraction_closed_so_far: float = 0.0


def _same_day_target_fraction(ladder: List[List[float]]) -> float:
    """Maximum fraction to close on the halt day (all ladder rungs with
    hours < 24 are treated as same-session in a daily loop)."""
    same = [frac for frac, hours in ladder if hours < 24.0]
    return max(same) if same else 0.0


def _next_day_target_fraction(ladder: List[List[float]]) -> float:
    """Fraction to reach by the session after the halt day."""
    any_next = [frac for frac, hours in ladder if 24.0 <= hours < 48.0]
    return max(any_next) if any_next else 1.0


def _median(values: List[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return float(s[mid]) if n % 2 == 1 else float(0.5 * (s[mid - 1] + s[mid]))


class KillSwitch:
    """Owns halt state + trigger evaluation + pager file I/O."""

    def __init__(self, cfg: Mapping[str, Any], db_conn: Optional[sqlite3.Connection] = None,
                 starting_nav: float = 100_000.0, simulated_bps: float = 5.0,
                 pager_path: Optional[Path] = None):
        ks_cfg = dict(cfg.get("kill_switch") or {})
        self.enabled: bool = bool(ks_cfg.get("enabled", True))
        self.triggers: Dict[str, float] = {
            **DEFAULT_TRIGGERS,
            **(ks_cfg.get("triggers") or {}),
        }
        ladder = ks_cfg.get("unwind_ladder") or DEFAULT_LADDER
        self.ladder: List[List[float]] = [list(r) for r in ladder]
        notif = ks_cfg.get("notifications") or {}
        if pager_path is not None:
            self.pager_path = Path(pager_path)
        else:
            self.pager_path = Path(notif.get("pager_file",
                                             "alphaforge_execution_pager.log"))
        self.write_sqlite_event: bool = bool(
            notif.get("also_write_sqlite_event", True))
        self.state = KillSwitchState()
        self.db_conn = db_conn
        self.starting_nav = starting_nav
        self.simulated_bps = simulated_bps

    # ─── trigger evaluation ──────────────────────────────────────────────

    def _evaluate_triggers(
        self,
        snap_daily_return: float,
        snap_drawdown: float,
        history: Mapping[str, pd.DataFrame],
        current_nav: float,
    ) -> List[str]:
        fired: List[str] = []
        t = self.triggers

        if snap_drawdown > t["max_drawdown_pct"]:
            fired.append(
                f"max_drawdown_pct ({snap_drawdown:.2%} > {t['max_drawdown_pct']:.2%})")

        if snap_daily_return < -t["single_day_loss_pct"]:
            fired.append(
                f"single_day_loss_pct ({snap_daily_return:.2%} < "
                f"{-t['single_day_loss_pct']:.2%})")

        # Track consecutive losing days — reset on any non-negative day.
        if snap_daily_return < 0:
            self.state.consecutive_losing_days += 1
        else:
            self.state.consecutive_losing_days = 0
        if self.state.consecutive_losing_days >= t["consecutive_losing_days"]:
            fired.append(
                f"consecutive_losing_days ({self.state.consecutive_losing_days})")

        # Query DB for realized slippage stats. Only meaningful if we have a
        # populated orders table — in a fresh session this is a no-op.
        if self.db_conn is not None:
            bps_list = self._fetch_slippage_bps()
            if bps_list:
                med = _median(bps_list)
                if med > t["realized_slippage_median_bps"]:
                    fired.append(
                        f"realized_slippage_median_bps ({med:.1f} > "
                        f"{t['realized_slippage_median_bps']:.1f})")
                cum_drag = self._compute_cum_drag()
                if current_nav > 0:
                    drag_pct = cum_drag / current_nav
                    if drag_pct > t["realized_cum_drag_vs_nav_pct"]:
                        fired.append(
                            f"realized_cum_drag_vs_nav_pct "
                            f"({drag_pct:.2%} > "
                            f"{t['realized_cum_drag_vs_nav_pct']:.2%})")

        # Universe liquidity floor: any ticker whose trailing 21-day dollar
        # volume mean is ≥ $10M counts as liquid.
        liquid = 0
        for ticker, df in history.items():
            if df is None or df.empty:
                continue
            tail = df.iloc[-21:]
            if "Volume" not in tail.columns or "Close" not in tail.columns:
                continue
            adv = float((tail["Close"] * tail["Volume"]).mean())
            if adv >= _MIN_ADV_USD:
                liquid += 1
        if liquid < int(t["min_liquid_tickers"]):
            fired.append(f"min_liquid_tickers ({liquid} < {int(t['min_liquid_tickers'])})")

        return fired

    def _fetch_slippage_bps(self) -> List[float]:
        try:
            rows = self.db_conn.execute(
                "SELECT slippage_bps FROM orders WHERE status='FILLED' "
                "AND slippage_bps IS NOT NULL"
            ).fetchall()
            return [float(r[0]) for r in rows]
        except sqlite3.Error:
            return []

    def _compute_cum_drag(self) -> float:
        """Sum of (realized_bps - simulated_bps) × filled_notional across
        the orders table. Positive = realized execution is worse than the
        backtest assumption."""
        try:
            rows = self.db_conn.execute(
                "SELECT slippage_bps, fill_price, fill_quantity "
                "FROM orders WHERE status='FILLED' AND fill_price IS NOT NULL "
                "AND fill_quantity IS NOT NULL AND slippage_bps IS NOT NULL"
            ).fetchall()
        except sqlite3.Error:
            return 0.0
        drag = 0.0
        for bps, px, qty in rows:
            notional = float(px) * float(qty)
            drag += notional * (float(bps) - self.simulated_bps) * 1e-4
        return drag

    # ─── external API ────────────────────────────────────────────────────

    def end_of_day(
        self,
        trade_date: str,
        daily_return: float,
        drawdown: float,
        history: Mapping[str, pd.DataFrame],
        nav: float,
    ) -> None:
        """Called once per trading day after snapshot is recorded."""
        if not self.enabled:
            return
        if self.state.halted:
            # Still check ACK so we can re-arm next day
            self._maybe_rearm()
            return
        fired = self._evaluate_triggers(daily_return, drawdown, history, nav)
        if fired:
            self.state.halted = True
            self.state.halt_date = trade_date
            self.state.halt_reasons = fired
            self.state.fraction_closed_so_far = 0.0
            self._write_pager(trade_date, fired)

    def unwind_target_fraction_today(self, trade_date: str) -> float:
        """How much of the halt-day book should be closed by end of `trade_date`.

        Returns 0.0 if not halted, halt-day same-session target on the halt
        date, and next-session (100%) target on any later date.
        """
        if not self.state.halted or self.state.halt_date is None:
            return 0.0
        if trade_date == self.state.halt_date:
            return _same_day_target_fraction(self.ladder)
        # Any subsequent session: flat per the >= 24h rung.
        return _next_day_target_fraction(self.ladder)

    def blocks_new_entries(self) -> bool:
        return self.enabled and self.state.halted

    def _maybe_rearm(self) -> None:
        """If the pager file contains an ACK: line *after* the halt line,
        clear the halt. The halt pager line is matched by timestamp."""
        if not self.pager_path.exists():
            return
        lines = self.pager_path.read_text().splitlines()
        seen_halt = False
        for line in lines:
            if self.state.halt_date and self.state.halt_date in line and "HALT" in line:
                seen_halt = True
            elif seen_halt and line.strip().startswith("ACK:"):
                # Operator acknowledged; clear state
                self.state = KillSwitchState()
                return

    # ─── pager output ────────────────────────────────────────────────────

    def _write_pager(self, trade_date: str, reasons: List[str]) -> None:
        self.pager_path.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        line = (f"{ts} HALT date={trade_date} reasons="
                + "; ".join(reasons) + "\n")
        with open(self.pager_path, "a") as f:
            f.write(line)
        if self.write_sqlite_event and self.db_conn is not None:
            try:
                self.db_conn.execute(
                    """INSERT OR REPLACE INTO snapshots
                       (date, nav, daily_return, cumulative_return, drawdown,
                        sharpe_to_date, long_exposure, short_exposure, cash,
                        n_positions, weights)
                       VALUES (?, 0, 0, 0, 0, 0, 0, 0, 0, -1, ?)""",
                    (f"KILL_{trade_date}", "; ".join(reasons)),
                )
                self.db_conn.commit()
            except sqlite3.Error:
                pass


def compute_unwind_target_weights(
    current_weights: Mapping[str, float],
    fraction_closed_target_today: float,
    fraction_closed_so_far: float,
) -> Tuple[Dict[str, float], float]:
    """Given the current portfolio and the ladder's cumulative target, return
    the target weights for today and the new fraction_closed_so_far.

    Weights are scaled down *uniformly* across tickers — we don't pick
    which names to close first. Shorts and longs are reduced symmetrically.
    """
    fraction_closed_today = max(0.0, min(1.0, fraction_closed_target_today))
    if fraction_closed_today <= fraction_closed_so_far:
        # Nothing to do; ladder has already been reached.
        return {t: w for t, w in current_weights.items()}, fraction_closed_so_far
    scale = 1.0 - fraction_closed_today
    new_weights = {t: w * scale for t, w in current_weights.items()}
    return new_weights, fraction_closed_today
