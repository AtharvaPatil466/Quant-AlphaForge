"""Tests for Phase 3 canonical input staging."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from research.phase3_stage_inputs import (
    stage_characteristics_table,
    stage_reference_table,
)


class TestStageReferenceTable:
    def test_normalizes_aliases_and_writes_canonical_csv(self, tmp_path: Path):
        raw = pd.DataFrame(
            {
                "date": ["2024-01-02", "2024-01-03"],
                "Mkt-RF": [0.01, -0.02],
                "SMB": [0.001, 0.002],
                "HML": [0.003, 0.004],
                "RMW": [0.005, 0.006],
                "CMA": [0.007, 0.008],
                "UMD": [0.009, 0.010],
            }
        )
        src = tmp_path / "raw_reference.csv"
        raw.to_csv(src, index=False)
        out = tmp_path / "staged_reference.csv"
        stage_reference_table(src, out)

        staged = pd.read_csv(out)
        assert list(staged.columns) == ["date", "MKT", "SMB", "HML", "RMW", "CMA", "UMD"]
        assert staged.loc[0, "MKT"] == pytest.approx(0.01)

    def test_duplicate_dates_raise(self, tmp_path: Path):
        raw = pd.DataFrame(
            {
                "date": ["2024-01-02", "2024-01-02"],
                "MKT": [0.01, 0.02],
                "SMB": [0.001, 0.002],
                "HML": [0.003, 0.004],
                "RMW": [0.005, 0.006],
                "CMA": [0.007, 0.008],
                "UMD": [0.009, 0.010],
            }
        )
        src = tmp_path / "dup_reference.csv"
        raw.to_csv(src, index=False)
        with pytest.raises(ValueError, match="duplicate date rows"):
            stage_reference_table(src, tmp_path / "out.csv")


class TestStageCharacteristicsTable:
    def test_normalizes_aliases_and_writes_canonical_csv(self, tmp_path: Path):
        raw = pd.DataFrame(
            {
                "date": ["2024-01-31"],
                "ticker": ["aapl"],
                "mkt_cap": [1.0],
                "btm": [0.5],
                "operating_profitability": [0.2],
                "asset_growth": [0.1],
            }
        )
        src = tmp_path / "raw_chars.csv"
        raw.to_csv(src, index=False)
        out = tmp_path / "staged_chars.csv"
        stage_characteristics_table(src, out)

        staged = pd.read_csv(out)
        assert list(staged.columns) == [
            "date", "ticker", "market_cap", "book_to_market", "profitability", "investment"
        ]
        assert staged.loc[0, "ticker"] == "AAPL"

    def test_duplicate_date_ticker_rows_raise(self, tmp_path: Path):
        raw = pd.DataFrame(
            {
                "date": ["2024-01-31", "2024-01-31"],
                "ticker": ["AAPL", "AAPL"],
                "market_cap": [1.0, 1.1],
                "book_to_market": [0.5, 0.6],
                "profitability": [0.2, 0.3],
                "investment": [0.1, 0.2],
            }
        )
        src = tmp_path / "dup_chars.csv"
        raw.to_csv(src, index=False)
        with pytest.raises(ValueError, match="duplicate \\(date, ticker\\) rows"):
            stage_characteristics_table(src, tmp_path / "out.csv")
