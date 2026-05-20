"""Tests for research.build_factor_matrix."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from research import build_factor_matrix as BFM  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers — synthetic processed-parquet builder
# ---------------------------------------------------------------------------

def _stage_processed(tmp_path: Path, n_days: int = 60, n_symbols: int = 8,
                      seed: int = 1) -> Path:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2018-01-04", periods=n_days, freq="B")
    syms = [f"SYM{i:02d}" for i in range(n_symbols)]
    rows = []
    base_prices = 100.0 * (1 + rng.normal(0, 0.0005, size=(n_days, n_symbols))).cumprod(axis=0)
    base_volumes = rng.integers(1_000, 100_000, size=(n_days, n_symbols))
    for i, d in enumerate(dates):
        for j, s in enumerate(syms):
            price = float(base_prices[i, j])
            vol = int(base_volumes[i, j])
            rows.append({
                "date": d, "symbol": s, "series": "EQ",
                "open": price, "high": price * 1.005, "low": price * 0.995,
                "close": price, "last": price, "prev_close": price,
                "volume": vol, "value": vol * price, "num_trades": 50,
                "deliv_qty": int(vol * 0.6), "deliv_pct": 60.0,
                "source_era": "unified",
            })
    processed = tmp_path / "processed" / "bhavcopy"
    processed.mkdir(parents=True)
    pd.DataFrame(rows).to_parquet(processed / "bhavcopy_2018.parquet", index=False)
    return processed


# ---------------------------------------------------------------------------
# load_universe_from_file
# ---------------------------------------------------------------------------

def test_load_universe_returns_none_when_path_missing(tmp_path: Path):
    assert BFM.load_universe_from_file(None) is None
    assert BFM.load_universe_from_file(tmp_path / "missing.txt") is None


def test_load_universe_reads_symbols(tmp_path: Path):
    p = tmp_path / "universe.txt"
    p.write_text("RELIANCE\nTCS\n# comment ignored\n\nHDFCBANK\n")
    out = BFM.load_universe_from_file(p)
    assert out == {"RELIANCE", "TCS", "HDFCBANK"}


def test_load_universe_returns_none_when_file_empty(tmp_path: Path):
    p = tmp_path / "empty.txt"
    p.write_text("# only comments\n\n")
    assert BFM.load_universe_from_file(p) is None


# ---------------------------------------------------------------------------
# load_bhavcopy_for_factors
# ---------------------------------------------------------------------------

def test_load_bhavcopy_for_factors_pivots_close_and_volume(tmp_path: Path):
    processed = _stage_processed(tmp_path, n_days=20, n_symbols=5)
    close, volume = BFM.load_bhavcopy_for_factors(
        processed, date(2018, 1, 1), date(2018, 12, 31),
    )
    assert close.shape == volume.shape
    assert len(close.columns) == 5
    # All-aligned dates.
    assert (close.index == volume.index).all()


def test_load_bhavcopy_for_factors_filters_to_universe(tmp_path: Path):
    processed = _stage_processed(tmp_path, n_days=10, n_symbols=8)
    close, volume = BFM.load_bhavcopy_for_factors(
        processed, date(2018, 1, 1), date(2018, 12, 31),
        universe={"SYM00", "SYM01"},
    )
    assert set(close.columns) == {"SYM00", "SYM01"}


def test_load_bhavcopy_for_factors_raises_on_empty_window(tmp_path: Path):
    processed = _stage_processed(tmp_path, n_days=10, n_symbols=3)
    with pytest.raises(ValueError, match="no rows"):
        BFM.load_bhavcopy_for_factors(
            processed, date(2030, 1, 1), date(2030, 12, 31),
        )


def test_load_bhavcopy_for_factors_raises_on_no_files(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        BFM.load_bhavcopy_for_factors(
            tmp_path / "nowhere", date(2018, 1, 1), date(2018, 12, 31),
        )


# ---------------------------------------------------------------------------
# build_risk_free_series
# ---------------------------------------------------------------------------

def test_build_risk_free_series_constant_default():
    idx = pd.date_range("2024-01-01", periods=10, freq="B")
    rf = BFM.build_risk_free_series(idx)
    # 7%/yr daily-compounded ≈ 0.000268 per day
    assert (rf > 0).all()
    assert rf.iloc[0] == pytest.approx((1.07 ** (1/252)) - 1.0, rel=1e-9)
    assert len(rf) == len(idx)


def test_build_risk_free_series_from_csv(tmp_path: Path):
    csv = tmp_path / "rf.csv"
    csv.write_text("date,rate\n2024-01-01,0.06\n2024-06-01,0.08\n")
    idx = pd.date_range("2024-01-01", "2024-07-31", freq="B")
    rf = BFM.build_risk_free_series(idx, csv_path=csv)
    # Before Jun 1: ~6%/yr daily. After: ~8%/yr daily.
    early = rf.loc[rf.index < pd.Timestamp("2024-06-01")]
    late = rf.loc[rf.index >= pd.Timestamp("2024-06-01")]
    assert (early < late.mean()).all()


def test_build_risk_free_series_csv_missing_fallback(tmp_path: Path):
    idx = pd.date_range("2024-01-01", periods=5, freq="B")
    rf = BFM.build_risk_free_series(idx, csv_path=tmp_path / "missing.csv",
                                       constant_annual=0.10)
    expected = (1.10 ** (1/252)) - 1.0
    assert rf.iloc[0] == pytest.approx(expected, rel=1e-9)


# ---------------------------------------------------------------------------
# build_matrix
# ---------------------------------------------------------------------------

def test_build_matrix_returns_three_factor_columns(tmp_path: Path):
    processed = _stage_processed(tmp_path, n_days=60, n_symbols=10)
    close, volume = BFM.load_bhavcopy_for_factors(
        processed, date(2018, 1, 1), date(2018, 12, 31),
    )
    rf = BFM.build_risk_free_series(close.index)
    matrix = BFM.build_matrix(close, volume, risk_free_daily=rf)
    assert set(matrix.columns) == {"MKT", "SMB", "LIQ"}
    assert len(matrix) == len(close)
    # No 'const' column — that's added by residualize() downstream.
    assert "const" not in matrix.columns


def test_build_matrix_without_risk_free_uses_raw_market(tmp_path: Path):
    processed = _stage_processed(tmp_path, n_days=40, n_symbols=6)
    close, volume = BFM.load_bhavcopy_for_factors(
        processed, date(2018, 1, 1), date(2018, 12, 31),
    )
    matrix_no_rf = BFM.build_matrix(close, volume, risk_free_daily=None)
    rf = BFM.build_risk_free_series(close.index, constant_annual=0.10)
    matrix_with_rf = BFM.build_matrix(close, volume, risk_free_daily=rf)
    # Market column with high rf should be lower than no-rf market.
    assert (matrix_with_rf["MKT"].mean()
            < matrix_no_rf["MKT"].mean())


# ---------------------------------------------------------------------------
# main — CLI integration
# ---------------------------------------------------------------------------

def test_main_writes_csv(tmp_path: Path):
    processed = _stage_processed(tmp_path, n_days=40, n_symbols=6)
    out = tmp_path / "factors.csv"
    rc = BFM.main([
        "--processed-dir", str(processed),
        "--start", "2018-01-01",
        "--end", "2018-12-31",
        "--out", str(out),
    ])
    assert rc == 0
    assert out.exists()
    df = pd.read_csv(out, index_col=0, parse_dates=True)
    assert {"MKT", "SMB", "LIQ"}.issubset(df.columns)
    assert len(df) > 0


def test_main_round_trip_consumable_by_run_phase3(tmp_path: Path):
    """The CSV produced by build_factor_matrix must be loadable by
    run_phase3.py's factor_matrix loading code (pd.read_csv with index_col=0,
    parse_dates=True). This is the integration contract."""
    processed = _stage_processed(tmp_path, n_days=40, n_symbols=6)
    out = tmp_path / "factors.csv"
    BFM.main([
        "--processed-dir", str(processed),
        "--start", "2018-01-01",
        "--end", "2018-12-31",
        "--out", str(out),
    ])
    # Load using the same call signature as run_phase3.main.
    factor_matrix = pd.read_csv(out, index_col=0, parse_dates=True)
    assert factor_matrix.index.dtype.kind == "M"  # datetime
    assert len(factor_matrix.columns) == 3
