"""Binance client tests — all HTTP mocked via httpx.MockTransport."""

from __future__ import annotations

import json

import httpx
import pytest

from data.binance_client import (
    BinanceAPIError,
    BinanceClient,
    RateLimitedError,
)


def _build_client(handler) -> BinanceClient:
    transport = httpx.MockTransport(handler)
    return BinanceClient(transport=transport, max_retries=2)


def test_spot_klines_request_shape() -> None:
    seen_request: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_request["url"] = str(request.url)
        seen_request["params"] = dict(request.url.params)
        body = [[1700000000000, "1", "2", "0.5", "1.5", "10", 1700003599999, "15", 3, "5", "7", "x"]]
        return httpx.Response(200, headers={"X-MBX-USED-WEIGHT-1M": "10"}, json=body)

    client = _build_client(handler)
    rows = client.spot_klines("btcusdt", "1h", start_time_ms=1700000000000, limit=500)
    client.close()

    assert seen_request["params"]["symbol"] == "BTCUSDT"
    assert seen_request["params"]["interval"] == "1h"
    assert seen_request["params"]["limit"] == "500"
    assert rows[0][0] == 1700000000000


def test_funding_rate_history_returns_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {"symbol": "BTCUSDT", "fundingTime": 1700000000000, "fundingRate": "0.0001", "markPrice": "42000.0"},
                {"symbol": "BTCUSDT", "fundingTime": 1700028800000, "fundingRate": "-0.00005", "markPrice": "42100.0"},
            ],
        )

    client = _build_client(handler)
    rows = client.funding_rate_history("BTCUSDT", start_time_ms=1700000000000)
    client.close()
    assert len(rows) == 2
    assert rows[0]["fundingTime"] == 1700000000000


def test_429_retry_then_success() -> None:
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={"msg": "Too many"})
        return httpx.Response(200, headers={"X-MBX-USED-WEIGHT-1M": "5"}, json=[])

    client = _build_client(handler)
    rows = client.fapi_klines("BTCUSDT", "1h")
    client.close()
    assert call_count["n"] == 2
    assert rows == []


def test_418_raises_immediately_without_retry() -> None:
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(418, text="banned")

    client = _build_client(handler)
    with pytest.raises(RateLimitedError) as excinfo:
        client.fapi_klines("BTCUSDT", "1h")
    client.close()
    assert excinfo.value.status_code == 418
    assert call_count["n"] == 1, "418 should not be retried"


def test_5xx_retries_then_gives_up() -> None:
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(503, json={"msg": "unavailable"})

    client = _build_client(handler)
    with pytest.raises(BinanceAPIError) as excinfo:
        client.fapi_klines("BTCUSDT", "1h")
    client.close()
    assert excinfo.value.status_code == 503
    assert call_count["n"] == 3  # 1 initial + 2 retries


def test_exchange_info_endpoints() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "fapi.binance.com":
            return httpx.Response(200, json={"symbols": [{"symbol": "BTCUSDT"}]})
        return httpx.Response(200, json={"symbols": [{"symbol": "BTCUSDT"}, {"symbol": "ETHUSDT"}]})

    client = _build_client(handler)
    spot = client.spot_exchange_info()
    fapi = client.fapi_exchange_info()
    client.close()
    assert len(spot["symbols"]) == 2
    assert len(fapi["symbols"]) == 1


def test_open_interest_history_request_shape() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = dict(request.url.params)
        return httpx.Response(
            200,
            json=[
                {"timestamp": 1700000000000, "sumOpenInterest": "100", "sumOpenInterestValue": "4200000"},
            ],
        )

    client = _build_client(handler)
    rows = client.open_interest_history("BTCUSDT", period="1h", limit=200)
    client.close()
    assert seen["params"]["period"] == "1h"
    assert seen["params"]["limit"] == "200"
    assert rows[0]["sumOpenInterest"] == "100"
