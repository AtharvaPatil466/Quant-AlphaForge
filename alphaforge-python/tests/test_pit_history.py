"""Tests for PIT membership-aware history utilities."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from data.market.pit.history import (
    load_pit_field_panel,
    load_quarantine_ticker,
    membership_mask_for_dates,
)


def _sample_frame(start: str = "2020-01-02", periods: int = 4, base: float = 100.0) -> pd.DataFrame:
    idx = pd.bdate_range(start, periods=periods)
    close = pd.Series([base + i for i in range(periods)], index=idx, dtype=float)
    return pd.DataFrame(
        {
            "Open": close * 0.99,
            "High": close * 1.01,
            "Low": close * 0.98,
            "Close": close,
            "Adj Close": close,
            "Volume": 1_000_000.0,
        },
        index=idx,
    )


@pytest.fixture
def toy_membership():
    events = pd.DataFrame(
        [
            {
                "event_id": "evt_add_msft",
                "effective_date": "2020-01-03",
                "ticker": "MSFT",
                "action": "ADD",
                "counterparty_ticker": None,
            },
            {
                "event_id": "evt_remove_aapl",
                "effective_date": "2020-01-06",
                "ticker": "AAPL",
                "action": "REMOVE",
                "counterparty_ticker": None,
            },
        ]
    )
    events["effective_date"] = pd.to_datetime(events["effective_date"]).dt.normalize()
    baseline = {"AAPL"}
    return events, baseline


class TestMembershipMask:
    def test_replay_applies_adds_and_removes(self, toy_membership):
        events, baseline = toy_membership
        idx = pd.bdate_range("2020-01-02", periods=4)
        mask = membership_mask_for_dates(events, baseline, idx, ["AAPL", "MSFT"])
        assert bool(mask.loc[pd.Timestamp("2020-01-02"), "AAPL"]) is True
        assert bool(mask.loc[pd.Timestamp("2020-01-02"), "MSFT"]) is False
        assert bool(mask.loc[pd.Timestamp("2020-01-03"), "MSFT"]) is True
        assert bool(mask.loc[pd.Timestamp("2020-01-06"), "AAPL"]) is False
        assert bool(mask.loc[pd.Timestamp("2020-01-06"), "MSFT"]) is True


class TestQuarantineLoader:
    def test_load_quarantine_ticker_slices_requested_range(self, tmp_path: Path):
        root = tmp_path / "quarantine" / "market"
        ticker_dir = root / "AAPL"
        ticker_dir.mkdir(parents=True, exist_ok=True)
        _sample_frame(periods=4).to_parquet(ticker_dir / "2020.parquet")

        df = load_quarantine_ticker(
            "AAPL",
            root=root,
            start_date="2020-01-03",
            end_date="2020-01-06",
        )
        assert list(df.index.strftime("%Y-%m-%d")) == ["2020-01-03", "2020-01-06"]


class TestPitFieldPanel:
    def test_panel_masks_non_members_to_nan(self, tmp_path: Path, toy_membership):
        events, baseline = toy_membership
        root = tmp_path / "quarantine" / "market"
        for ticker, base in [("AAPL", 100.0), ("MSFT", 200.0)]:
            ticker_dir = root / ticker
            ticker_dir.mkdir(parents=True, exist_ok=True)
            _sample_frame(periods=4, base=base).to_parquet(ticker_dir / "2020.parquet")

        pit = load_pit_field_panel(
            field="Adj Close",
            start_date="2020-01-02",
            end_date="2020-01-07",
            root=root,
            events=events,
            baseline=baseline,
            tickers=["AAPL", "MSFT"],
        )

        assert pd.isna(pit.panel.loc[pd.Timestamp("2020-01-02"), "MSFT"])
        assert pit.panel.loc[pd.Timestamp("2020-01-03"), "MSFT"] == pytest.approx(201.0)
        assert pd.isna(pit.panel.loc[pd.Timestamp("2020-01-06"), "AAPL"])
        assert pit.raw_panel.loc[pd.Timestamp("2020-01-06"), "AAPL"] == pytest.approx(102.0)
