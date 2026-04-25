"""Local paper broker — simulates order execution without any external API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Dict

from execution.broker import AccountState, Broker, Order, Position


class PaperBroker(Broker):
    """Simulates a broker locally. Fills at reference price + slippage."""

    def __init__(self, starting_cash: float = 100_000.0, slippage_bps: float = 5.0):
        self._cash = starting_cash
        self._starting_nav = starting_cash
        self._positions: Dict[str, Position] = {}
        self._slippage_bps = slippage_bps
        self._prices: Dict[str, float] = {}

    def submit_order(self, order: Order) -> Order:
        ticker = order.ticker
        ref_price = self._prices.get(ticker, 0.0)
        # Fall back to position's last known price if current price is missing
        if ref_price <= 0 and ticker in self._positions:
            ref_price = self._positions[ticker].current_price
        if ref_price <= 0:
            order.status = "REJECTED"
            return order

        # Apply slippage
        slip = self._slippage_bps / 10_000
        if order.side == "BUY":
            fill_price = ref_price * (1 + slip)
        else:
            fill_price = ref_price * (1 - slip)

        cost = fill_price * order.quantity
        now = datetime.utcnow().isoformat()

        if order.side == "BUY":
            if cost > self._cash:
                # Reduce quantity to what we can afford
                order.quantity = self._cash / fill_price
                cost = fill_price * order.quantity
            self._cash -= cost
            pos = self._positions.get(ticker)
            if pos:
                total_qty = pos.quantity + order.quantity
                pos.avg_cost = (pos.avg_cost * pos.quantity + fill_price * order.quantity) / total_qty
                pos.quantity = total_qty
            else:
                self._positions[ticker] = Position(
                    ticker=ticker,
                    quantity=order.quantity,
                    avg_cost=fill_price,
                    current_price=ref_price,
                )
        else:  # SELL
            pos = self._positions.get(ticker)
            if not pos:
                order.status = "REJECTED"
                return order
            # Clamp order quantity to position size (avoids float rounding rejections)
            if order.quantity > pos.quantity:
                if order.quantity - pos.quantity < 0.01:
                    order.quantity = pos.quantity
                else:
                    order.status = "REJECTED"
                    return order
            self._cash += cost
            pos.quantity -= order.quantity
            if pos.quantity < 0.001:
                del self._positions[ticker]

        order.order_id = str(uuid.uuid4())[:8]
        order.status = "FILLED"
        order.fill_price = fill_price
        order.fill_quantity = order.quantity
        order.submitted_at = now
        order.filled_at = now
        order.slippage_bps = self._slippage_bps
        order.tx_cost = cost * (self._slippage_bps / 10_000)

        return order

    def get_account(self) -> AccountState:
        return AccountState(
            nav=self._cash + sum(p.market_value for p in self._positions.values()),
            cash=self._cash,
            positions=dict(self._positions),
        )

    def get_positions(self) -> Dict[str, Position]:
        return dict(self._positions)

    def update_prices(self, prices: Dict[str, float]) -> None:
        self._prices.update(prices)
        for ticker, pos in self._positions.items():
            if ticker in prices:
                pos.current_price = prices[ticker]
