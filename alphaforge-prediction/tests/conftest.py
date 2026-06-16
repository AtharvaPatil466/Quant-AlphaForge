"""Shared fixtures for the prediction sub-project tests.

Schemas mirror the EXACT Kalshi API shapes observed in the 2026-06-16 spike
(see `research/SPIKE_NOTES.md`). No test makes a live network call — every
client interaction goes through `FakeSession`. "Test against reality, not
expectations": these fixtures replay real response shapes, including the
string-typed numerics and the event-vs-market category split.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Fake requests.Session / Response — scripted by URL.
# ---------------------------------------------------------------------------

@dataclass
class FakeResponse:
    status_code: int
    _json: Any = None
    text: str = ""
    headers: dict[str, str] = field(default_factory=lambda: {"content-type": "application/json"})

    def json(self) -> Any:
        if self._json is None:
            raise ValueError("no json body")
        return self._json


@dataclass
class FakeSession:
    """Returns a scripted response sequence per (url, frozenset(params)).

    A simpler routing model than the india fake: a callable router lets tests
    branch on path + params (needed for cursor pagination + candlesticks).
    """
    router: Any = None                      # callable(url, params) -> FakeResponse
    calls: list[tuple[str, dict]] = field(default_factory=list)

    def get(self, url: str, params=None, headers=None, timeout=None) -> FakeResponse:
        params = dict(params or {})
        self.calls.append((url, params))
        if self.router is None:
            return FakeResponse(599, _json={"msg": "no router"})
        return self.router(url, params)


# ---------------------------------------------------------------------------
# Real-shape market / event / candle fixtures (from SPIKE_NOTES.md).
# ---------------------------------------------------------------------------

def make_market(
    ticker: str,
    event_ticker: str = "EVT-1",
    status: str = "finalized",
    result: str = "yes",
    settlement_value: str = "1.0000",
    volume_fp: str = "47398.43",
    open_time: str = "2026-06-16T06:00:00Z",
    close_time: str = "2026-06-16T08:00:00Z",
    settlement_ts: str = "2026-06-16T08:05:13.379965Z",
    market_type: str = "binary",
    last_price: str = "0.8670",
) -> dict[str, Any]:
    """A resolved market with string-typed numerics, matching the live shape."""
    return {
        "ticker": ticker,
        "event_ticker": event_ticker,
        "status": status,
        "result": result,
        "settlement_value_dollars": settlement_value,
        "last_price_dollars": last_price,
        "yes_bid_dollars": "0.8500",
        "yes_ask_dollars": "0.8800",
        "no_bid_dollars": "0.1200",
        "no_ask_dollars": "0.1500",
        "volume_fp": volume_fp,
        "volume": None,
        "open_time": open_time,
        "close_time": close_time,
        "expiration_time": close_time,
        "settlement_ts": settlement_ts,
        "market_type": market_type,
        "strike_type": "custom",
        "category": None,            # category lives on the event, not here
        "title": f"title for {ticker}",
    }


def make_event(event_ticker: str = "EVT-1",
               series_ticker: str = "SERIES-1",
               category: str = "Crypto") -> dict[str, Any]:
    return {
        "event": {
            "event_ticker": event_ticker,
            "series_ticker": series_ticker,
            "category": category,
            "title": "an event",
            "sub_title": "MVE",
        }
    }


def make_candle(end_period_ts: int,
                close_dollars: str | None,
                yes_bid: str = "0.8500",
                yes_ask: str = "0.8800",
                volume_fp: str = "100.0",
                previous_dollars: str | None = None) -> dict[str, Any]:
    """A candle. `close_dollars=None` models a no-trade bucket (carries previous)."""
    if close_dollars is None:
        price = {"previous_dollars": previous_dollars or "0.5000"}
    else:
        price = {
            "open_dollars": close_dollars, "high_dollars": close_dollars,
            "low_dollars": close_dollars, "close_dollars": close_dollars,
            "mean_dollars": close_dollars,
        }
    return {
        "end_period_ts": end_period_ts,
        "price": price,
        "yes_bid": {"open_dollars": yes_bid, "high_dollars": yes_bid,
                    "low_dollars": yes_bid, "close_dollars": yes_bid},
        "yes_ask": {"open_dollars": yes_ask, "high_dollars": yes_ask,
                    "low_dollars": yes_ask, "close_dollars": yes_ask},
        "volume_fp": volume_fp,
        "open_interest_fp": "303.03",
    }


@pytest.fixture
def make_market_fixture():
    return make_market


@pytest.fixture
def make_event_fixture():
    return make_event


@pytest.fixture
def make_candle_fixture():
    return make_candle
