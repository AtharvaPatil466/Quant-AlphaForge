"""Unit tests for ingest.kalshi_client — all against FakeSession (no network)."""
from __future__ import annotations

import pytest

from ingest.kalshi_client import (
    KalshiClient, KalshiClientConfig, KalshiAPIError, RateLimitedError,
    VALID_PERIOD_INTERVALS, MAX_CANDLES_PER_REQUEST,
)
from tests.conftest import FakeResponse, FakeSession, make_market, make_event, make_candle


def _client(router) -> KalshiClient:
    cfg = KalshiClientConfig(rate_limit_seconds=0.0, max_attempts=3)
    return KalshiClient(cfg, session=FakeSession(router=router))


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def test_single_page_no_cursor():
    def router(url, params):
        assert url.endswith("/markets")
        return FakeResponse(200, _json={"markets": [make_market("A"), make_market("B")], "cursor": ""})
    c = _client(router)
    markets, cursor = c.get_markets_page()
    assert [m["ticker"] for m in markets] == ["A", "B"]
    assert cursor is None


def test_iter_settled_markets_follows_cursor():
    pages = {
        None: {"markets": [make_market("A")], "cursor": "c1"},
        "c1": {"markets": [make_market("B")], "cursor": "c2"},
        "c2": {"markets": [make_market("C")], "cursor": ""},
    }

    def router(url, params):
        return FakeResponse(200, _json=pages[params.get("cursor")])

    c = _client(router)
    seen = [m["ticker"] for m, _ in c.iter_settled_markets(limit=1)]
    assert seen == ["A", "B", "C"]


def test_iter_settled_markets_respects_max_pages():
    def router(url, params):
        # Always a full page with a next cursor → would loop forever w/o max_pages.
        return FakeResponse(200, _json={"markets": [make_market("X")], "cursor": "next"})

    c = _client(router)
    seen = list(c.iter_settled_markets(limit=1, max_pages=2))
    assert len(seen) == 2


def test_iter_stops_on_empty_markets():
    def router(url, params):
        return FakeResponse(200, _json={"markets": [], "cursor": "next"})

    c = _client(router)
    assert list(c.iter_settled_markets()) == []


def test_status_none_omits_status_param_and_passes_close_window():
    captured = {}

    def router(url, params):
        captured.update(params)
        return FakeResponse(200, _json={"markets": [make_market("A")], "cursor": ""})

    c = _client(router)
    list(c.iter_settled_markets(status=None, min_close_ts=1000, max_close_ts=2000))
    assert "status" not in captured
    assert captured["min_close_ts"] == 1000
    assert captured["max_close_ts"] == 2000


def test_status_sent_when_provided():
    captured = {}

    def router(url, params):
        captured.update(params)
        return FakeResponse(200, _json={"markets": [], "cursor": ""})

    c = _client(router)
    c.get_markets_page(status="settled")
    assert captured["status"] == "settled"


# ---------------------------------------------------------------------------
# Retry / error handling
# ---------------------------------------------------------------------------

def test_retries_5xx_then_succeeds():
    calls = {"n": 0}

    def router(url, params):
        calls["n"] += 1
        if calls["n"] < 3:
            return FakeResponse(503, _json={"error": {"message": "down"}})
        return FakeResponse(200, _json={"markets": [], "cursor": ""})

    c = _client(router)
    markets, _ = c.get_markets_page()
    assert markets == []
    assert calls["n"] == 3


def test_4xx_other_than_429_raises_immediately():
    def router(url, params):
        return FakeResponse(404, _json={"error": {"message": "not found"}})

    c = _client(router)
    with pytest.raises(KalshiAPIError) as e:
        c.get_markets_page()
    assert e.value.status == 404


def test_429_persisted_raises_rate_limited():
    def router(url, params):
        return FakeResponse(429, _json={"msg": "slow down"}, headers={"content-type": "application/json", "Retry-After": "0"})

    c = _client(router)
    with pytest.raises(RateLimitedError):
        c.get_markets_page()


def test_non_dict_json_raises():
    def router(url, params):
        return FakeResponse(200, _json=[1, 2, 3])

    c = _client(router)
    with pytest.raises(KalshiAPIError):
        c.get_markets_page()


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

def test_get_event_returns_inner_event():
    def router(url, params):
        assert "/events/EVT-1" in url
        return FakeResponse(200, _json=make_event("EVT-1", "SER-9", "Sports"))

    c = _client(router)
    ev = c.get_event("EVT-1")
    assert ev["series_ticker"] == "SER-9"
    assert ev["category"] == "Sports"


# ---------------------------------------------------------------------------
# Candlesticks
# ---------------------------------------------------------------------------

def test_candlesticks_rejects_invalid_interval():
    c = _client(lambda u, p: FakeResponse(200, _json={"candlesticks": []}))
    with pytest.raises(ValueError):
        c.get_candlesticks("S", "T", 0, 60, period_interval=5)
    # Valid intervals do not raise on the guard (they hit the router).
    for iv in sorted(VALID_PERIOD_INTERVALS):
        c.get_candlesticks("S", "T", 0, iv * 60, period_interval=iv)


def test_candlesticks_rejects_oversized_window():
    c = _client(lambda u, p: FakeResponse(200, _json={"candlesticks": []}))
    # 1-min interval over > 5000 minutes → guard raises before any request.
    span = (MAX_CANDLES_PER_REQUEST + 10) * 60
    with pytest.raises(ValueError):
        c.get_candlesticks("S", "T", 0, span, period_interval=1)


def test_candlesticks_returns_list_and_passes_params():
    captured = {}

    def router(url, params):
        captured.update(params)
        assert "/series/SER/markets/MKT/candlesticks" in url
        return FakeResponse(200, _json={"ticker": "MKT", "candlesticks": [make_candle(100, "0.30")]})

    c = _client(router)
    candles = c.get_candlesticks("SER", "MKT", 0, 600, period_interval=1)
    assert len(candles) == 1
    assert captured["start_ts"] == 0 and captured["end_ts"] == 600
    assert captured["period_interval"] == 1


def test_candlesticks_end_before_start_raises():
    c = _client(lambda u, p: FakeResponse(200, _json={"candlesticks": []}))
    with pytest.raises(ValueError):
        c.get_candlesticks("S", "T", 600, 0, period_interval=1)
