"""Tests for the parquet-backed local market-data layer."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from data.market.downloader import MarketDataDownloader
from data.market.loader import (
    MarketDataLoader,
    MarketDataRangeError,
    TickerQuarantinedError,
)
from data.market.paths import ticker_year_path, universe_manifest_path
from data.market.universe import write_universe_manifest
from data.market.validator import MarketDataValidator


def _sample_frame(start: str = "2024-01-02", periods: int = 8) -> pd.DataFrame:
    idx = pd.bdate_range(start, periods=periods)
    close = pd.Series(range(100, 100 + periods), index=idx, dtype=float)
    return pd.DataFrame(
        {
            "Open": close * 0.99,
            "High": close * 1.01,
            "Low": close * 0.98,
            "Close": close,
            "Adj Close": close,
            "Volume": 1_000_000.0,
            "Dividends": 0.0,
            "Stock Splits": 0.0,
        },
        index=idx,
    )


class TestMarketLoader:
    def test_write_and_load_history(self, tmp_path: Path):
        downloader = MarketDataDownloader(base_dir=tmp_path)
        downloader.write_frames({"AAPL": _sample_frame(), "MSFT": _sample_frame()})

        loader = MarketDataLoader(base_dir=tmp_path)
        history = loader.load_history(["AAPL", "MSFT"], align="inner")
        assert set(history) == {"AAPL", "MSFT"}
        assert len(history["AAPL"]) == 8
        assert list(history["AAPL"].columns) == [
            "Open",
            "High",
            "Low",
            "Close",
            "Adj Close",
            "Volume",
            "Dividends",
            "Stock Splits",
        ]

    def test_loader_latest(self, tmp_path: Path):
        downloader = MarketDataDownloader(base_dir=tmp_path)
        downloader.write_frames({"AAPL": _sample_frame()})
        loader = MarketDataLoader(base_dir=tmp_path)
        latest = loader.load_latest(["AAPL"])
        assert "AAPL" in latest
        assert float(latest["AAPL"]["Close"]) == 107.0

    def test_manifest_window_is_enforced(self, tmp_path: Path):
        market_root = tmp_path / "market"
        downloader = MarketDataDownloader(base_dir=market_root)
        downloader.write_frames({"AAPL": _sample_frame()})

        manifest_path = tmp_path / "universe" / "real_ticker_manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(
                {
                    "tickers": [
                        {
                            "ticker": "AAPL",
                            "sector": "Technology",
                            "usable_start": "2024-01-05",
                            "usable_end": None,
                            "requires_clean_years": 5,
                            "notes": "test fixture",
                        }
                    ]
                }
            )
        )

        loader = MarketDataLoader(base_dir=market_root)
        clipped = loader.load_ticker("AAPL")
        assert clipped.index[0].date().isoformat() == "2024-01-05"
        with pytest.raises(MarketDataRangeError, match="usable_start is 2024-01-05"):
            loader.load_ticker("AAPL", start_date="2024-01-04")

    def test_quarantined_years_are_excluded_when_active_years_remain(self, tmp_path: Path):
        market_root = tmp_path / "market"
        downloader = MarketDataDownloader(base_dir=market_root)
        history = pd.concat(
            [
                _sample_frame("2023-12-27", periods=3),
                _sample_frame("2024-01-02", periods=4),
            ]
        )
        downloader.write_frames({"AAPL": history})

        active_path = ticker_year_path("AAPL", 2023, market_root)
        quarantined_path = ticker_year_path(
            "AAPL",
            2023,
            market_root,
            quarantined=True,
        )
        quarantined_path.parent.mkdir(parents=True, exist_ok=True)
        active_path.rename(quarantined_path)

        loader = MarketDataLoader(base_dir=market_root)
        available_start, available_end = loader.available_range("AAPL")
        assert available_start.date().isoformat() == "2024-01-02"
        assert available_end.date().isoformat() == "2024-01-05"
        assert set(loader.load_ticker("AAPL", start_date="2023-12-27").index.year) == {2024}


class TestMarketValidator:
    def test_clean_data_survives_validation(self, tmp_path: Path):
        downloader = MarketDataDownloader(base_dir=tmp_path)
        downloader.write_frames({"AAPL": _sample_frame()})

        validator = MarketDataValidator(base_dir=tmp_path)
        summary = validator.validate_ticker("AAPL")
        assert summary.clean is True
        assert summary.clean_trading_days == 8

    def test_extreme_return_is_quarantined(self, tmp_path: Path):
        bad = _sample_frame()
        bad.loc[bad.index[4], "Close"] = bad.loc[bad.index[3], "Close"] * 2.0
        bad.loc[bad.index[4], "Adj Close"] = bad.loc[bad.index[4], "Close"]
        downloader = MarketDataDownloader(base_dir=tmp_path)
        downloader.write_frames({"AAPL": bad})

        validator = MarketDataValidator(base_dir=tmp_path)
        summary = validator.validate_ticker("AAPL")
        assert summary.clean is False
        assert any(issue.code == "extreme_return" for issue in summary.issues)

        loader = MarketDataLoader(base_dir=tmp_path)
        with pytest.raises(TickerQuarantinedError):
            loader.load_ticker("AAPL")


class TestUniverseManifest:
    def test_write_manifest(self, tmp_path: Path):
        manifest_path = write_universe_manifest(tmp_path / "universe.json")
        assert manifest_path.exists()
        payload = manifest_path.read_text()
        assert "AAPL" in payload

    def test_repo_manifest_matches_generated_defaults(self, tmp_path: Path):
        repo_manifest_payload = json.loads(universe_manifest_path().read_text())
        expected_manifest_path = write_universe_manifest(tmp_path / "expected_manifest.json")
        expected_manifest_payload = json.loads(expected_manifest_path.read_text())
        assert repo_manifest_payload == expected_manifest_payload
