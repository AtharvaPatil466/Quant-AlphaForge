"""Daily execution loop — orchestrates the full trading cycle.

Can run for a single date (live) or backtest over a date range.
"""

from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import requests

from config import get_tickers, load_config
from data.market_data import fetch_history
from data.validator import DataValidationError, validate_history
from execution.broker import Broker, Order
from execution.paper_broker import PaperBroker
from portfolio.tracker import DailySnapshot, PortfolioTracker
from risk.limits import check_circuit_breakers, check_pre_trade
from risk.kill_switch import KillSwitch, compute_unwind_target_weights
from storage.database import get_connection
from storage.trade_log import log_order, log_signals, log_snapshot
from strategy.momentum import generate_target_weights

logger = logging.getLogger(__name__)

ALERT_LOG = Path(__file__).parent.parent / "alerts.log"


def _alert(level: str, msg: str) -> None:
    """Append a timestamped alert to alerts.log."""
    from datetime import datetime
    ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
    line = f"{ts} [{level}] {msg}\n"
    with open(ALERT_LOG, "a") as f:
        f.write(line)


def is_alpaca_market_open() -> bool:
    """Check if US market is currently open via Alpaca's clock endpoint.

    Returns False on any error (fail-safe: don't trade when unsure).
    """
    from dotenv import load_dotenv
    load_dotenv()
    api_key = os.environ.get("ALPACA_API_KEY", "")
    secret_key = os.environ.get("ALPACA_SECRET_KEY", "")
    if not api_key or not secret_key:
        logger.error("ALPACA_API_KEY / ALPACA_SECRET_KEY not set")
        return False
    try:
        r = requests.get(
            "https://paper-api.alpaca.markets/v2/clock",
            headers={
                "APCA-API-KEY-ID": api_key,
                "APCA-API-SECRET-KEY": secret_key,
            },
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        is_open = data.get("is_open", False)
        logger.info(f"Alpaca clock check: is_open={is_open}, next_open={data.get('next_open')}")
        return is_open
    except Exception as e:
        logger.error(f"Alpaca clock check failed: {e}")
        return False


def create_broker(cfg: Dict[str, Any]) -> Broker:
    """Factory: create broker from config (paper or alpaca)."""
    exec_cfg = cfg.get("execution", {})
    strat_cfg = cfg.get("strategy", {})
    broker_type = exec_cfg.get("broker", "paper")
    starting_nav = exec_cfg.get("starting_nav", 100_000.0)
    slippage_bps = exec_cfg.get("slippage_bps", 5.0)

    if broker_type == "alpaca":
        from execution.alpaca_broker import AlpacaBroker
        # Use separate Alpaca credentials for MARL strategy
        key_prefix = "ALPACA_MARL" if strat_cfg.get("type") == "marl" else "ALPACA"
        return AlpacaBroker(
            paper=True,
            fill_timeout=exec_cfg.get("fill_timeout", 60),
            key_prefix=key_prefix,
        )
    else:
        return PaperBroker(
            starting_cash=starting_nav,
            slippage_bps=slippage_bps,
        )


class ExecutionEngine:
    """Orchestrates the daily trading cycle."""

    def __init__(
        self,
        broker: Broker,
        tracker: PortfolioTracker,
        cfg: Dict[str, Any],
        db_path: str | None = None,
    ):
        self.broker = broker
        self.tracker = tracker
        self.cfg = cfg
        self.tickers = get_tickers(cfg)
        self.conn = get_connection(db_path) if db_path else None
        self.halted = False
        self.halt_reason = ""
        exec_cfg = cfg.get("execution", {})
        self.kill_switch = KillSwitch(
            cfg,
            db_conn=self.conn,
            starting_nav=exec_cfg.get("starting_nav", 100_000.0),
            simulated_bps=exec_cfg.get("slippage_bps", 5.0),
        )

    def run_day(
        self,
        history: Dict[str, pd.DataFrame],
        trade_date: str,
    ) -> Optional[DailySnapshot]:
        """Execute one trading day.

        Args:
            history: ticker -> DataFrame with OHLCV up to trade_date
            trade_date: date string (YYYY-MM-DD)

        Returns:
            DailySnapshot or None if skipped.
        """
        # Legacy halt path: callers that set `engine.halted = True` directly
        # (e.g. after a plain circuit-breaker trip) get the pre-existing
        # "skip the day entirely" behavior. The kill-switch has its own
        # state and runs an active unwind instead — handled below.
        if self.halted and not self.kill_switch.state.halted:
            logger.warning(f"[{trade_date}] HALTED: {self.halt_reason}")
            return None

        # 1. Update broker prices to latest close
        prices = {}
        for ticker, df in history.items():
            if not df.empty:
                prices[ticker] = float(df["Close"].iloc[-1])
        self.broker.update_prices(prices)

        # Kill-switch gate — if halted, compute the unwind target for today
        # instead of generating entries.
        account = self.broker.get_account()
        nav = account.nav
        current_weights = {
            t: p.market_value / nav for t, p in account.positions.items()
        } if nav > 0 else {}

        if self.kill_switch.blocks_new_entries():
            target_frac = self.kill_switch.unwind_target_fraction_today(trade_date)
            unwind_weights, new_frac = compute_unwind_target_weights(
                current_weights, target_frac,
                self.kill_switch.state.fraction_closed_so_far,
            )
            self.kill_switch.state.fraction_closed_so_far = new_frac
            logger.warning(
                f"[{trade_date}] KILL-SWITCH unwinding to {target_frac:.0%} "
                f"closed (reasons: {'; '.join(self.kill_switch.state.halt_reasons)})"
            )
            orders = self._compute_orders(unwind_weights, current_weights, nav, prices)
            # Submit the unwind orders, then record snapshot and evaluate EOD
            for order in orders:
                filled = self.broker.submit_order(order)
                if self.conn:
                    log_order(self.conn, trade_date, filled)
            snap = self._record_snapshot(trade_date)
            if snap is not None:
                self.kill_switch.end_of_day(
                    trade_date, snap.daily_return, snap.drawdown, history, snap.nav,
                )
            # Legacy halted flag for compat with existing callers
            self.halted = True
            self.halt_reason = "; ".join(self.kill_switch.state.halt_reasons)
            return snap

        # 2. Generate target weights from strategy
        strat_cfg = self.cfg.get("strategy", {})
        strat_type = strat_cfg.get("type", "momentum")

        if strat_type == "marl":
            from strategy.marl_strategy import generate_target_weights as marl_weights
            target = marl_weights(
                history,
                checkpoint_path=strat_cfg.get("marl_checkpoint"),
                max_position=strat_cfg.get("position_weight", 0.05),
            )
        else:
            target = generate_target_weights(
                history,
                top_n=strat_cfg.get("top_n", 5),
                position_weight=strat_cfg.get("position_weight", 0.05),
                mom_5d_weight=strat_cfg.get("mom_5d_weight", 0.4),
                mom_21d_weight=strat_cfg.get("mom_21d_weight", 0.4),
                mr_weight=strat_cfg.get("mean_reversion_weight", 0.2),
            )

        # Log signals
        if self.conn:
            log_signals(self.conn, trade_date, target.signals)

        # 3. Portfolio state was captured above for the kill-switch gate.

        # 4. Pre-trade risk checks
        risk_cfg = self.cfg.get("risk", {})
        risk_result = check_pre_trade(
            target_weights=target.weights,
            current_nav=nav,
            max_position_pct=risk_cfg.get("max_position_pct", 0.10),
            max_gross_exposure=risk_cfg.get("max_gross_exposure", 1.50),
            max_daily_turnover=risk_cfg.get("max_daily_turnover", 0.30),
            current_weights=current_weights,
        )
        if not risk_result.passed:
            logger.warning(f"[{trade_date}] Risk check failed: {risk_result.failures}")
            # Still record snapshot with no trades
            snap = self._record_snapshot(trade_date)
            return snap

        # 5. Compute order deltas
        orders = self._compute_orders(target.weights, current_weights, nav, prices)

        if not orders:
            logger.info(f"[{trade_date}] No rebalancing orders needed")
            snap = self._record_snapshot(trade_date)
            return snap

        # 5b. Alpaca clock guard — only for live Alpaca broker
        exec_cfg = self.cfg.get("execution", {})
        if exec_cfg.get("broker") == "alpaca":
            if not is_alpaca_market_open():
                msg = (f"[{trade_date}] MARKET CLOSED — skipping {len(orders)} orders. "
                       "Fix cron schedule to run during US market hours (9:30AM-4PM ET).")
                logger.error(msg)
                _alert("BLOCKED", msg)
                # Record snapshot but don't trade
                snap = self._record_snapshot(trade_date)
                return snap

        # 6. Submit orders
        rejected_orders: list[Order] = []
        for order in orders:
            filled = self.broker.submit_order(order)
            logger.info(
                f"[{trade_date}] {filled.side} {filled.quantity:.2f} {filled.ticker} "
                f"@ {filled.fill_price:.2f} ({filled.status})"
            )
            if self.conn:
                log_order(self.conn, trade_date, filled)

            # 6b. Rejected order alert
            if filled.status == "REJECTED":
                rejected_orders.append(filled)
                msg = (f"REJECTED: {filled.side} {filled.quantity:.2f} {filled.ticker} "
                       f"on {trade_date} — order_id={filled.order_id}")
                logger.error(msg)
                _alert("REJECTED", msg)

        if rejected_orders:
            summary = (f"[{trade_date}] {len(rejected_orders)}/{len(orders)} orders REJECTED. "
                       "Check alerts.log and broker dashboard.")
            logger.error(summary)
            _alert("REJECTED_SUMMARY", summary)

        # 7. Record daily snapshot
        snap = self._record_snapshot(trade_date)

        # 8. Circuit breakers
        if snap:
            cb = check_circuit_breakers(
                daily_return=snap.daily_return,
                drawdown=snap.drawdown,
                max_daily_loss=risk_cfg.get("max_daily_loss", 0.02),
                max_drawdown=risk_cfg.get("max_drawdown", 0.10),
            )
            if not cb.passed:
                self.halted = True
                self.halt_reason = "; ".join(cb.failures)
                logger.error(f"[{trade_date}] CIRCUIT BREAKER: {self.halt_reason}")

            # 8b. Kill-switch — evaluates the full trigger set. Engages
            # independently of the circuit breakers so e.g. slippage drift
            # can halt the strategy even on a green-P&L day.
            self.kill_switch.end_of_day(
                trade_date, snap.daily_return, snap.drawdown, history, snap.nav,
            )
            if self.kill_switch.state.halted and not self.halted:
                self.halted = True
                self.halt_reason = "; ".join(self.kill_switch.state.halt_reasons)
                logger.error(f"[{trade_date}] KILL-SWITCH: {self.halt_reason}")

        return snap

    def _compute_orders(
        self,
        target_weights: Dict[str, float],
        current_weights: Dict[str, float],
        nav: float,
        prices: Dict[str, float],
    ) -> List[Order]:
        """Compute buy/sell orders to move from current to target weights."""
        orders: List[Order] = []
        all_tickers = set(target_weights.keys()) | set(current_weights.keys())

        for ticker in all_tickers:
            target_w = target_weights.get(ticker, 0.0)
            current_w = current_weights.get(ticker, 0.0)
            delta_w = target_w - current_w

            if abs(delta_w) < 0.005:  # skip tiny rebalances
                continue

            price = prices.get(ticker, 0.0)
            # Fall back to broker's last known price
            if price <= 0:
                price = self.broker._prices.get(ticker, 0.0)
            if price <= 0:
                continue

            dollar_delta = delta_w * nav
            quantity = abs(dollar_delta / price)

            if quantity * price < 50:  # skip orders under $50
                continue

            orders.append(Order(
                ticker=ticker,
                side="BUY" if delta_w > 0 else "SELL",
                quantity=round(quantity, 4),
            ))

        return orders

    def _record_snapshot(self, trade_date: str) -> DailySnapshot:
        account = self.broker.get_account()
        positions = {
            t: p.market_value for t, p in account.positions.items()
        }
        snap = self.tracker.record_day(
            date=trade_date,
            nav=account.nav,
            cash=account.cash,
            positions=positions,
        )
        if self.conn:
            log_snapshot(self.conn, snap)
        return snap


def backtest(
    cfg: Dict[str, Any],
    start_date: date,
    end_date: date,
    db_path: str | None = None,
) -> PortfolioTracker:
    """Run the strategy over historical data.

    Fetches full history once, then replays day by day.
    """
    tickers = get_tickers(cfg)
    exec_cfg = cfg.get("execution", {})
    starting_nav = exec_cfg.get("starting_nav", 100_000.0)
    slippage_bps = exec_cfg.get("slippage_bps", 5.0)
    lookback = cfg.get("data", {}).get("lookback_days", 252)
    market_dir = cfg.get("data", {}).get("market_dir")

    logger.info(f"Fetching history for {tickers} from {start_date} to {end_date}")
    full_history = fetch_history(
        tickers,
        days=lookback + (end_date - start_date).days,
        end=end_date,
        market_dir=market_dir,
    )

    if not full_history:
        raise RuntimeError("No data fetched")

    # Validate
    validate_history(full_history, tickers, min_days=lookback, check_staleness=False)

    # Get all trading dates in range
    ref_ticker = list(full_history.keys())[0]
    all_dates = full_history[ref_ticker].index
    trade_dates = [d for d in all_dates if start_date <= d.date() <= end_date]

    if not trade_dates:
        raise RuntimeError(f"No trading dates between {start_date} and {end_date}")

    logger.info(f"Backtesting {len(trade_dates)} trading days")

    broker = create_broker(cfg)
    tracker = PortfolioTracker(starting_nav=starting_nav)
    engine = ExecutionEngine(broker, tracker, cfg, db_path=db_path)

    for i, dt in enumerate(trade_dates):
        dt_str = str(dt.date())
        # Slice history up to this date (inclusive)
        sliced = {}
        for ticker, df in full_history.items():
            sliced[ticker] = df.loc[:dt]

        snap = engine.run_day(sliced, dt_str)

        if snap and (i + 1) % 21 == 0:
            logger.info(
                f"  Day {i+1:3d}/{len(trade_dates)} | {dt_str} | "
                f"NAV={snap.nav:,.0f} | ret={snap.cumulative_return:+.2%} | "
                f"Sharpe={snap.sharpe_to_date:.2f} | DD={snap.drawdown:.2%}"
            )

        if engine.halted:
            logger.warning(f"Halted at {dt_str}: {engine.halt_reason}")
            break

    return tracker


def run_live_day(
    cfg: Dict[str, Any],
    db_path: str | None = None,
) -> Optional[DailySnapshot]:
    """Run a single live trading day using the configured broker.

    Fetches fresh market data, computes signals, submits orders via
    the broker (paper or Alpaca), and records the snapshot.
    """
    tickers = get_tickers(cfg)
    exec_cfg = cfg.get("execution", {})
    lookback = cfg.get("data", {}).get("lookback_days", 252)
    market_dir = cfg.get("data", {}).get("market_dir")
    today = date.today().isoformat()

    logger.info(f"[{today}] Loading {lookback}d validated history for {tickers}")
    history = fetch_history(tickers, days=lookback, market_dir=market_dir)

    if not history:
        raise RuntimeError("No data fetched — market may be closed")

    validate_history(history, tickers, min_days=lookback // 2, check_staleness=True)

    broker = create_broker(cfg)
    starting_nav = exec_cfg.get("starting_nav", 100_000.0)

    # For live trading, get actual account NAV from broker
    if exec_cfg.get("broker") == "alpaca":
        account = broker.get_account()
        starting_nav = account.nav
        logger.info(f"[{today}] Alpaca account NAV: ${starting_nav:,.2f}")

    tracker = PortfolioTracker(starting_nav=starting_nav)
    engine = ExecutionEngine(broker, tracker, cfg, db_path=db_path)

    snap = engine.run_day(history, today)

    if snap:
        logger.info(
            f"[{today}] Day complete | NAV=${snap.nav:,.2f} | "
            f"Return={snap.daily_return:+.2%} | Positions={snap.n_positions}"
        )

    if engine.halted:
        logger.error(f"[{today}] CIRCUIT BREAKER: {engine.halt_reason}")

    return snap
