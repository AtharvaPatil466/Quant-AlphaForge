"""
API endpoint tests using httpx TestClient (no live server needed).
"""

from pathlib import Path

import pytest

from fastapi.testclient import TestClient

from api.server import app

client = TestClient(app)

PREFIX = "/api/v1"


class TestHealth:
    def test_health(self):
        r = client.get(f"{PREFIX}/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert "version" in data


class TestSectors:
    def test_sectors(self):
        r = client.get(f"{PREFIX}/sectors")
        assert r.status_code == 200
        data = r.json()
        assert "Technology" in data["sectors"]
        assert len(data["sectors"]) == 5


class TestUniverse:
    def test_default(self):
        r = client.get(f"{PREFIX}/universe?sector=Technology")
        assert r.status_code == 200
        data = r.json()
        assert "AAPL" in data["tickers"]

    def test_all(self):
        r = client.get(f"{PREFIX}/universe?sector=All")
        assert r.status_code == 200
        assert len(r.json()["tickers"]) == 30


class TestFactors:
    def test_list(self):
        r = client.get(f"{PREFIX}/factors")
        assert r.status_code == 200
        assert len(r.json()["factors"]) == 5

    def test_single_factor(self):
        r = client.get(f"{PREFIX}/factors/Momentum (12-1)?sector=Technology&lookback=252")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 6  # 6 tech tickers
        for item in data:
            assert "ticker" in item
            assert "score" in item
            assert item["signal"] in ("LONG", "SHORT", "NEUTRAL")

    def test_invalid_factor(self):
        r = client.get(f"{PREFIX}/factors/Bogus")
        assert r.status_code == 422


class TestScanner:
    def test_default(self):
        r = client.get(f"{PREFIX}/scanner?sector=Technology&lookback=252")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 6
        for item in data:
            assert "composite" in item
            assert "signal" in item
            assert "factor_scores" in item

    def test_all_sectors(self):
        r = client.get(f"{PREFIX}/scanner?sector=All&lookback=252")
        assert r.status_code == 200
        assert len(r.json()) == 30

    def test_invalid_sector(self):
        r = client.get(f"{PREFIX}/scanner?sector=Bogus")
        assert r.status_code == 422


class TestBacktest:
    def test_default(self):
        r = client.post(f"{PREFIX}/backtest", json={
            "sector": "Technology",
            "lookback": 252,
            "factor_name": "Momentum (12-1)",
        })
        assert r.status_code == 200
        data = r.json()
        assert len(data["nav"]) == 253
        assert data["nav"][0] == 100.0
        assert data["metrics"]["sharpe"] is not None

    def test_invalid_factor(self):
        r = client.post(f"{PREFIX}/backtest", json={
            "sector": "Technology",
            "factor_name": "Bogus",
        })
        assert r.status_code == 422

    def test_invalid_lookback(self):
        r = client.post(f"{PREFIX}/backtest", json={
            "sector": "Technology",
            "lookback": 5,  # below minimum
        })
        assert r.status_code == 422


class TestCorrelation:
    def test_default(self):
        r = client.get(f"{PREFIX}/correlation?sector=Technology&lookback=252")
        assert r.status_code == 200
        data = r.json()
        assert len(data["matrix"]) == 5
        assert len(data["ic"]) == 5
        assert len(data["turnover"]) == 5
        # Diagonal should be 1.0
        for i in range(5):
            assert data["matrix"][i][i] == pytest.approx(1.0)

    def test_invalid_sector(self):
        r = client.get(f"{PREFIX}/correlation?sector=Bogus")
        assert r.status_code == 422


class TestPriceSeries:
    def test_default(self):
        r = client.get(f"{PREFIX}/price-series?ticker=AAPL&days=252")
        assert r.status_code == 200
        data = r.json()
        assert data["ticker"] == "AAPL"
        assert len(data["prices"]) == 253
        assert len(data["volumes"]) == 253


class TestMarketRoutes:
    def test_market_availability(self, monkeypatch, tmp_path: Path):
        from api.routes import market as market_routes

        class FakeLoader:
            def available_range(self, ticker):
                return None, None

            def load_ticker(self, ticker):
                return []

        monkeypatch.setattr(market_routes, "MarketDataLoader", lambda: FakeLoader())
        monkeypatch.setattr(
            market_routes,
            "validation_report_path",
            lambda: tmp_path / "missing_report.json",
        )
        r = client.get(f"{PREFIX}/market/availability?sector=Technology")
        assert r.status_code == 200
        data = r.json()
        assert len(data["items"]) >= 1
        assert "ticker" in data["items"][0]

    def test_live_prices(self, monkeypatch):
        from api.routes import market as market_routes

        class FakeLoader:
            def load_latest(self, tickers, end_date=None):
                import pandas as pd
                idx = pd.Timestamp("2024-01-05")
                return {
                    "AAPL": pd.Series({"Close": 189.5, "Volume": 1_500_000.0}, name=idx),
                }

        monkeypatch.setattr(market_routes, "MarketDataLoader", lambda: FakeLoader())
        r = client.get(f"{PREFIX}/market/live-prices?sector=Technology")
        assert r.status_code == 200
        data = r.json()
        assert data["items"][0]["ticker"] == "AAPL"
        assert data["items"][0]["close"] == pytest.approx(189.5)
