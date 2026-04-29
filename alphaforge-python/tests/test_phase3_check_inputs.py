"""Tests for Phase 3 staged-input sanity checks."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from research.phase3_check_inputs import (
    summarize_characteristics_table,
    summarize_reference_factor_table,
)


class TestReferenceSummary:
    def test_flags_duplicate_dates_and_percent_like_scale(self):
        df = pd.DataFrame(
            {
                "MKT": [1.5, 0.01],
                "SMB": [0.1, 0.2],
                "HML": [0.0, 0.1],
                "RMW": [0.0, 0.1],
                "CMA": [0.0, 0.1],
                "UMD": [0.0, 0.1],
            },
            index=pd.to_datetime(["2024-01-02", "2024-01-02"]),
        )
        out = summarize_reference_factor_table(df)
        assert out["duplicate_dates"] == 1
        assert "MKT" in out["suspicious_scale_columns"]
        assert any("percent units" in warning for warning in out["warnings"] if warning)


class TestCharacteristicsSummary:
    def test_flags_duplicate_date_ticker_pairs(self):
        df = pd.DataFrame(
            {
                "date": pd.to_datetime(["2024-01-31", "2024-01-31"]),
                "ticker": ["AAPL", "AAPL"],
                "market_cap": [1.0, 1.0],
                "book_to_market": [0.5, 0.5],
                "profitability": [0.2, 0.2],
                "investment": [0.1, 0.1],
            }
        )
        out = summarize_characteristics_table(df)
        assert out["duplicate_date_ticker_pairs"] == 1
        assert any("duplicate" in warning for warning in out["warnings"] if warning)
