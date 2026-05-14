"""Universe selection tests with a mocked Binance client."""

from __future__ import annotations

import httpx

from data.binance_client import BinanceClient
from data.universe import (
    discover_usdt_perpetuals,
    load_universe_manifest,
    select_top_n_by_volume,
    write_universe_manifest,
)


def _client_with_fixtures(spot_symbols, fapi_symbols, fapi_tickers) -> BinanceClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "fapi.binance.com" and request.url.path == "/fapi/v1/exchangeInfo":
            return httpx.Response(200, json={"symbols": fapi_symbols})
        if request.url.host == "fapi.binance.com" and request.url.path == "/fapi/v1/ticker/24hr":
            return httpx.Response(200, json=fapi_tickers)
        if request.url.host == "api.binance.com" and request.url.path == "/api/v3/exchangeInfo":
            return httpx.Response(200, json={"symbols": spot_symbols})
        return httpx.Response(404, json={"msg": "not stubbed"})

    return BinanceClient(transport=httpx.MockTransport(handler))


def test_discover_filters_to_trading_usdt_perps() -> None:
    spot = [
        {"symbol": "BTCUSDT", "status": "TRADING"},
        {"symbol": "ETHUSDT", "status": "TRADING"},
        {"symbol": "RAREUSDT", "status": "BREAK"},
    ]
    fapi = [
        {"symbol": "BTCUSDT", "status": "TRADING", "contractType": "PERPETUAL",
         "quoteAsset": "USDT", "baseAsset": "BTC", "onboardDate": 1568102400000},
        {"symbol": "ETHUSDT", "status": "TRADING", "contractType": "PERPETUAL",
         "quoteAsset": "USDT", "baseAsset": "ETH", "onboardDate": 1569369600000},
        {"symbol": "BTCBUSD", "status": "TRADING", "contractType": "PERPETUAL",
         "quoteAsset": "BUSD", "baseAsset": "BTC", "onboardDate": 1600000000000},
        {"symbol": "OLDUSDT", "status": "SETTLING", "contractType": "PERPETUAL",
         "quoteAsset": "USDT", "baseAsset": "OLD", "onboardDate": 1500000000000},
        {"symbol": "BTCUSDT_240329", "status": "TRADING", "contractType": "CURRENT_QUARTER",
         "quoteAsset": "USDT", "baseAsset": "BTC", "onboardDate": 1700000000000},
    ]
    client = _client_with_fixtures(spot, fapi, [])
    perps = discover_usdt_perpetuals(client)
    client.close()
    symbols = {p.symbol for p in perps}
    assert symbols == {"BTCUSDT", "ETHUSDT"}
    by_symbol = {p.symbol: p for p in perps}
    assert by_symbol["BTCUSDT"].has_spot_pair is True
    assert by_symbol["ETHUSDT"].has_spot_pair is True


def test_select_top_n_ranks_by_quote_volume() -> None:
    spot = [{"symbol": s, "status": "TRADING"} for s in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]]
    fapi = [
        {"symbol": s, "status": "TRADING", "contractType": "PERPETUAL",
         "quoteAsset": "USDT", "baseAsset": s.replace("USDT", ""), "onboardDate": 0}
        for s in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    ]
    tickers = [
        {"symbol": "BTCUSDT", "quoteVolume": "1000000000"},
        {"symbol": "ETHUSDT", "quoteVolume": "500000000"},
        {"symbol": "SOLUSDT", "quoteVolume": "5000000000"},
    ]
    client = _client_with_fixtures(spot, fapi, tickers)
    perps = discover_usdt_perpetuals(client)
    top = select_top_n_by_volume(client, perps, top_n=2)
    client.close()
    assert [p.symbol for p in top] == ["SOLUSDT", "BTCUSDT"]


def test_require_spot_pair_excludes_perp_only_symbols() -> None:
    spot = [{"symbol": "BTCUSDT", "status": "TRADING"}]
    fapi = [
        {"symbol": "BTCUSDT", "status": "TRADING", "contractType": "PERPETUAL",
         "quoteAsset": "USDT", "baseAsset": "BTC", "onboardDate": 0},
        {"symbol": "PERPONLYUSDT", "status": "TRADING", "contractType": "PERPETUAL",
         "quoteAsset": "USDT", "baseAsset": "PERPONLY", "onboardDate": 0},
    ]
    tickers = [
        {"symbol": "BTCUSDT", "quoteVolume": "1"},
        {"symbol": "PERPONLYUSDT", "quoteVolume": "1000000"},
    ]
    client = _client_with_fixtures(spot, fapi, tickers)
    perps = discover_usdt_perpetuals(client)
    top = select_top_n_by_volume(client, perps, top_n=5, require_spot_pair=True)
    client.close()
    assert {p.symbol for p in top} == {"BTCUSDT"}


def test_manifest_roundtrip(tmp_path) -> None:
    spot = [{"symbol": "BTCUSDT", "status": "TRADING"}]
    fapi = [{"symbol": "BTCUSDT", "status": "TRADING", "contractType": "PERPETUAL",
             "quoteAsset": "USDT", "baseAsset": "BTC", "onboardDate": 0}]
    tickers = [{"symbol": "BTCUSDT", "quoteVolume": "1000000"}]
    client = _client_with_fixtures(spot, fapi, tickers)
    perps = discover_usdt_perpetuals(client)
    top = select_top_n_by_volume(client, perps, top_n=1)
    client.close()

    base = tmp_path / "binance"
    path = write_universe_manifest(top, top_n=1, base_dir=base, quote_volume_by_symbol={"BTCUSDT": 1_000_000})
    assert path.exists()
    loaded = load_universe_manifest(base_dir=base)
    assert loaded["top_n"] == 1
    assert loaded["symbols"][0]["symbol"] == "BTCUSDT"
    assert loaded["symbols"][0]["quote_volume_24h_usd"] == 1_000_000
