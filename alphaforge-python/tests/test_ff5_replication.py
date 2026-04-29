"""Tests for FF5+UMD replication helpers."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from research.ff5_replication import (
    build_ff5_umd_replica,
    load_characteristics_table,
)


def _toy_close_panel() -> pd.DataFrame:
    idx = pd.bdate_range("2020-01-01", periods=420)
    tickers = [f"T{i:02d}" for i in range(30)]
    data = {}
    for i, tk in enumerate(tickers):
        drift = 0.00005 + i * 0.00002
        seasonal = 0.0004 * np.sin(np.arange(len(idx)) / 21.0 + i * 0.3)
        px = 100 * np.exp(np.cumsum(np.full(len(idx), drift) + seasonal))
        data[tk] = px
    return pd.DataFrame(data, index=idx)


def _toy_characteristics(close: pd.DataFrame) -> pd.DataFrame:
    rebals = close.index.to_series().groupby(close.index.to_period("M")).max()
    rows = []
    for dt in rebals.iloc[:-1]:
        for i, tk in enumerate(close.columns):
            rows.append(
                {
                    "date": dt,
                    "ticker": tk,
                    "market_cap": 1e9 + i * 1e8,
                    "book_to_market": 0.2 + i * 0.05,
                    "profitability": 0.05 + i * 0.01,
                    "investment": 0.01 + i * 0.02,
                }
            )
    return pd.DataFrame(rows)


class TestCharacteristicsLoader:
    def test_aliases_are_normalized(self, tmp_path: Path):
        df = pd.DataFrame(
            {
                "date": ["2024-01-31"],
                "ticker": ["AAPL"],
                "mkt_cap": [1.0],
                "btm": [0.5],
                "operating_profitability": [0.2],
                "asset_growth": [0.1],
            }
        )
        path = tmp_path / "chars.csv"
        df.to_csv(path, index=False)
        out = load_characteristics_table(path)
        assert list(out.columns) == ["date", "ticker", "market_cap", "book_to_market", "profitability", "investment"]


class TestFF5Replica:
    def test_replica_builder_returns_expected_columns(self):
        close = _toy_close_panel()
        chars = _toy_characteristics(close)
        out = build_ff5_umd_replica(close, chars)
        assert list(out.columns) == ["MKT", "SMB", "HML", "RMW", "CMA", "UMD"]
        assert len(out) > 0
        assert out.notna().all().all()

    def test_replica_builder_returns_empty_on_too_small_universe(self):
        close = _toy_close_panel().iloc[:, :8]
        chars = _toy_characteristics(close)
        out = build_ff5_umd_replica(close, chars)
        assert out.empty

    def test_replica_builder_tolerates_missing_characteristics_tickers(self):
        close = _toy_close_panel()
        chars = _toy_characteristics(close)
        keep = close.columns[:24]
        chars = chars[chars["ticker"].isin(keep)]
        out = build_ff5_umd_replica(close, chars)
        assert list(out.columns) == ["MKT", "SMB", "HML", "RMW", "CMA", "UMD"]
