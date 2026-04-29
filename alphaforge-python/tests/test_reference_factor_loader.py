"""Tests for the explicit local reference-factor contract."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from research.risk_model import REFERENCE_FACTOR_COLUMNS, load_reference_factor_table


class TestReferenceFactorLoader:
    def test_csv_normalizes_common_market_column_alias(self, tmp_path: Path):
        df = pd.DataFrame(
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
        path = tmp_path / "factors.csv"
        df.to_csv(path, index=False)
        out = load_reference_factor_table(path)
        assert list(out.columns) == list(REFERENCE_FACTOR_COLUMNS)
        assert out.index[0] == pd.Timestamp("2024-01-02")
        assert out.loc[pd.Timestamp("2024-01-02"), "MKT"] == pytest.approx(0.01)

    def test_missing_required_column_raises(self, tmp_path: Path):
        df = pd.DataFrame(
            {
                "date": ["2024-01-02"],
                "MKT": [0.01],
                "SMB": [0.001],
                "HML": [0.003],
                "RMW": [0.005],
                "CMA": [0.007],
            }
        )
        path = tmp_path / "bad.csv"
        df.to_csv(path, index=False)
        with pytest.raises(ValueError, match="missing required columns"):
            load_reference_factor_table(path)
