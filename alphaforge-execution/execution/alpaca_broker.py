"""Alpaca paper trading broker — submits real orders to Alpaca's paper API."""

from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional

from dotenv import load_dotenv

from execution.broker import AccountState, Broker, Order, Position

logger = logging.getLogger(__name__)

# Alpaca API base URLs
PAPER_BASE_URL = "https://paper-api.alpaca.markets"
LIVE_BASE_URL = "https://api.alpaca.markets"


class AlpacaBroker(Broker):
    """Broker backed by Alpaca's paper (or live) trading API.

    Implements the same interface as PaperBroker so it can be swapped in
    via config without changing the execution engine.
    """

    def __init__(
        self,
        api_key: str | None = None,
        secret_key: str | None = None,
        paper: bool = True,
        fill_timeout: int = 60,
        key_prefix: str = "ALPACA",
    ):
        load_dotenv()
        # Support two env naming schemes:
        #   ALPACA_API_KEY / ALPACA_SECRET_KEY                (default)
        #   ALPACA_API_KEY_<suffix> / ALPACA_SECRET_KEY_<suffix>  (e.g. _MARL)
        # `key_prefix` may be "ALPACA" or "ALPACA_<suffix>"; we accept both.
        if key_prefix == "ALPACA" or not key_prefix.startswith("ALPACA_"):
            api_env, secret_env = f"{key_prefix}_API_KEY", f"{key_prefix}_SECRET_KEY"
        else:
            suffix = key_prefix[len("ALPACA_"):]
            api_env, secret_env = f"ALPACA_API_KEY_{suffix}", f"ALPACA_SECRET_KEY_{suffix}"

        try:
            self._api_key = api_key or os.environ[api_env]
            self._secret_key = secret_key or os.environ[secret_env]
        except KeyError:
            # Fall back to base ALPACA_* credentials so a missing per-strategy
            # key isn't fatal (shared paper account is fine for dev).
            logger.warning(
                f"{api_env}/{secret_env} not set — falling back to ALPACA_API_KEY/ALPACA_SECRET_KEY"
            )
            self._api_key = api_key or os.environ["ALPACA_API_KEY"]
            self._secret_key = secret_key or os.environ["ALPACA_SECRET_KEY"]
        self._paper = paper
        self._fill_timeout = fill_timeout
        self._prices: Dict[str, float] = {}

        # Lazy import so the SDK is only required when AlpacaBroker is used
        from alpaca.trading.client import TradingClient

        self._client = TradingClient(
            api_key=self._api_key,
            secret_key=self._secret_key,
            paper=self._paper,
        )

        # Verify connectivity
        acct = self._client.get_account()
        logger.info(
            f"Connected to Alpaca {'paper' if paper else 'LIVE'} | "
            f"Account: {acct.id} | Equity: ${float(acct.equity):,.2f}"
        )

    def submit_order(self, order: Order) -> Order:
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest

        now = datetime.now(timezone.utc).isoformat()
        order.submitted_at = now

        # Round to integer shares — Alpaca paper doesn't support fractional
        # for all tickers. Use notional for sub-share amounts.
        qty = round(order.quantity)

        # For SELLs, clamp to actual held position so rounding-up can't
        # produce an "insufficient qty" rejection (e.g. want 13.85 → 14,
        # but only 13 held).
        if order.side == "SELL":
            try:
                raw_positions = self._client.get_all_positions()
                held = next(
                    (int(float(p.qty)) for p in raw_positions if p.symbol == order.ticker),
                    0,
                )
            except Exception as e:
                logger.warning(f"Could not fetch position for {order.ticker}: {e}")
                held = qty
            if held <= 0:
                logger.warning(f"No position to sell for {order.ticker}, skipping")
                order.status = "REJECTED"
                return order
            if qty > held:
                logger.info(
                    f"Clamping SELL {order.ticker} {qty}→{held} (held position limit)"
                )
                qty = held

        if qty < 1:
            logger.warning(f"Order quantity < 1 share for {order.ticker}, skipping")
            order.status = "REJECTED"
            return order

        side = OrderSide.BUY if order.side == "BUY" else OrderSide.SELL
        req = MarketOrderRequest(
            symbol=order.ticker,
            qty=qty,
            side=side,
            time_in_force=TimeInForce.DAY,
        )

        try:
            alpaca_order = self._client.submit_order(req)
            order.order_id = str(alpaca_order.id)
            logger.info(
                f"Submitted {order.side} {qty} {order.ticker} → order_id={order.order_id}"
            )
        except Exception as e:
            logger.error(f"Order submission failed for {order.ticker}: {e}")
            order.status = "REJECTED"
            return order

        # Wait for fill
        filled_order = self._wait_for_fill(order.order_id)

        if filled_order and filled_order.status.value == "filled":
            order.status = "FILLED"
            order.fill_price = float(filled_order.filled_avg_price)
            order.fill_quantity = float(filled_order.filled_qty)
            order.filled_at = (
                filled_order.filled_at.isoformat()
                if filled_order.filled_at
                else now
            )

            # Compute actual slippage vs last known price
            ref_price = self._prices.get(order.ticker, order.fill_price)
            if ref_price > 0:
                if order.side == "BUY":
                    order.slippage_bps = (
                        (order.fill_price - ref_price) / ref_price
                    ) * 10_000
                else:
                    order.slippage_bps = (
                        (ref_price - order.fill_price) / ref_price
                    ) * 10_000
            order.tx_cost = abs(order.fill_price * order.fill_quantity * order.slippage_bps / 10_000)

            logger.info(
                f"Filled {order.side} {order.fill_quantity} {order.ticker} "
                f"@ ${order.fill_price:.2f} (slippage: {order.slippage_bps:.1f} bps)"
            )
        else:
            status_val = filled_order.status.value if filled_order else "unknown"
            logger.warning(
                f"Order {order.order_id} not filled within {self._fill_timeout}s "
                f"(status: {status_val})"
            )
            order.status = "REJECTED"
            # Cancel the unfilled order
            try:
                self._client.cancel_order_by_id(order.order_id)
            except Exception:
                pass

        return order

    def _wait_for_fill(self, order_id: str, poll_interval: float = 1.0):
        """Poll Alpaca until order is filled or timeout."""
        elapsed = 0.0
        while elapsed < self._fill_timeout:
            try:
                o = self._client.get_order_by_id(order_id)
                if o.status.value in ("filled", "canceled", "expired", "rejected"):
                    return o
            except Exception as e:
                logger.warning(f"Error polling order {order_id}: {e}")
            time.sleep(poll_interval)
            elapsed += poll_interval
        # One last check
        try:
            return self._client.get_order_by_id(order_id)
        except Exception:
            return None

    def get_order_status(self, order_id: str) -> Optional[Order]:
        """Check status of a previously submitted order."""
        try:
            o = self._client.get_order_by_id(order_id)
            order = Order(
                ticker=o.symbol,
                side=o.side.value.upper(),
                quantity=float(o.qty),
                order_id=str(o.id),
                status=o.status.value.upper(),
                fill_price=float(o.filled_avg_price) if o.filled_avg_price else 0.0,
                fill_quantity=float(o.filled_qty) if o.filled_qty else 0.0,
            )
            return order
        except Exception as e:
            logger.error(f"Failed to get order {order_id}: {e}")
            return None

    def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order. Returns True if successfully cancelled."""
        try:
            self._client.cancel_order_by_id(order_id)
            logger.info(f"Cancelled order {order_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            return False

    def get_account(self) -> AccountState:
        acct = self._client.get_account()
        positions = self.get_positions()
        return AccountState(
            nav=float(acct.equity),
            cash=float(acct.cash),
            positions=positions,
        )

    def get_positions(self) -> Dict[str, Position]:
        raw_positions = self._client.get_all_positions()
        positions: Dict[str, Position] = {}
        for p in raw_positions:
            positions[p.symbol] = Position(
                ticker=p.symbol,
                quantity=float(p.qty),
                avg_cost=float(p.avg_entry_price),
                current_price=float(p.current_price),
            )
        return positions

    def update_prices(self, prices: Dict[str, float]) -> None:
        """Store reference prices for slippage calculation.

        Unlike PaperBroker, we don't need to update position prices
        since Alpaca tracks current prices server-side.
        """
        self._prices.update(prices)
