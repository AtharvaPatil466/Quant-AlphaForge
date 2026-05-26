"""Tests for research.cs_calibration."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from research import cs_calibration as CS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stage_processed(
    tmp_path: Path,
    start_date: str = "2004-01-05",
    n_days: int = 60,
    n_symbols: int = 8,
    high_low_spread_pct: float = 0.02,   # 2% intraday H-L range → CS ~ 200bp halfspread
    seed: int = 1,
) -> Path:
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start_date, periods=n_days, freq="B")
    syms = [f"SYM{i:02d}" for i in range(n_symbols)]
    close_path = 100.0 * (1 + rng.normal(0, 0.0005, (n_days, n_symbols))).cumprod(axis=0)
    rows = []
    for i, d in enumerate(dates):
        for j, s in enumerate(syms):
            c = float(close_path[i, j])
            h = c * (1 + high_low_spread_pct / 2)
            l = c * (1 - high_low_spread_pct / 2)
            rows.append({
                "date": d, "symbol": s, "series": "EQ",
                "open": c, "high": h, "low": l, "close": c, "last": c,
                "prev_close": c, "volume": 10_000, "value": c * 10_000,
                "num_trades": 50, "deliv_qty": 6_000, "deliv_pct": 60.0,
                "source_era": "unified",
            })
    processed = tmp_path / "processed" / "bhavcopy"
    processed.mkdir(parents=True)
    pd.DataFrame(rows).to_parquet(
        processed / f"bhavcopy_{start_date[:4]}.parquet", index=False
    )
    return processed


# ---------------------------------------------------------------------------
# load_universe
# ---------------------------------------------------------------------------

def test_load_universe_none_when_path_missing(tmp_path: Path):
    assert CS.load_universe(None) is None
    assert CS.load_universe(tmp_path / "nope.txt") is None


def test_load_universe_reads_lines(tmp_path: Path):
    p = tmp_path / "u.txt"
    p.write_text("ALPHA\n# comment\nBETA\n\n")
    assert CS.load_universe(p) == {"ALPHA", "BETA"}


# ---------------------------------------------------------------------------
# sample_symbols
# ---------------------------------------------------------------------------

def test_sample_symbols_is_deterministic_with_seed():
    pool = [f"S{i}" for i in range(100)]
    a = CS.sample_symbols(pool, None, 10, seed=42)
    b = CS.sample_symbols(pool, None, 10, seed=42)
    assert a == b


def test_sample_symbols_changes_with_different_seed():
    pool = [f"S{i}" for i in range(100)]
    a = CS.sample_symbols(pool, None, 10, seed=1)
    b = CS.sample_symbols(pool, None, 10, seed=2)
    assert a != b


def test_sample_symbols_intersects_universe():
    pool = [f"S{i}" for i in range(20)]
    universe = {"S0", "S1", "S2", "S3"}
    out = CS.sample_symbols(pool, universe, 3, seed=42)
    assert set(out).issubset(universe)


def test_sample_symbols_caps_at_pool_size():
    pool = ["A", "B", "C"]
    out = CS.sample_symbols(pool, None, 10, seed=42)
    assert set(out) == {"A", "B", "C"}


def test_sample_symbols_raises_when_pool_empty():
    with pytest.raises(ValueError):
        CS.sample_symbols([], None, 5, seed=1)


# ---------------------------------------------------------------------------
# load_ohl_panel
# ---------------------------------------------------------------------------

def test_load_ohl_panel_pivots_high_low_close(tmp_path: Path):
    processed = _stage_processed(tmp_path, n_days=20, n_symbols=5)
    high, low, close = CS.load_ohl_panel(processed,
                                            date(2004, 1, 1), date(2014, 12, 31))
    assert high.shape == low.shape == close.shape
    assert (high.values > low.values).all()


def test_load_ohl_panel_filters_by_date_range(tmp_path: Path):
    processed = _stage_processed(tmp_path, start_date="2010-01-04", n_days=10)
    # Window strictly after the data.
    with pytest.raises(ValueError):
        CS.load_ohl_panel(processed, date(2020, 1, 1), date(2020, 12, 31))


def test_load_ohl_panel_raises_on_no_parquets(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        CS.load_ohl_panel(tmp_path / "nope", date(2004, 1, 1), date(2014, 12, 31))


# ---------------------------------------------------------------------------
# calibrate_window
# ---------------------------------------------------------------------------

def test_calibrate_window_reports_per_stock_count(tmp_path: Path):
    processed = _stage_processed(tmp_path, start_date="2010-01-04",
                                    n_days=60, n_symbols=10,
                                    high_low_spread_pct=0.02)
    sample = [f"SYM{i:02d}" for i in range(5)]
    w = CS.calibrate_window(
        "IS", date(2010, 1, 1), date(2010, 12, 31), processed, sample,
        cs_window=21,
    )
    assert w.n_stocks_sampled == 5
    assert w.n_stocks_with_data > 0
    assert w.median_half_spread_bps is not None


def test_calibrate_window_flags_above_threshold(tmp_path: Path):
    """Synthetic data with 2% intraday H-L produces ~200bp+ CS half-spread,
    well above the 10bp documentation threshold."""
    processed = _stage_processed(tmp_path, start_date="2010-01-04",
                                    n_days=60, n_symbols=5,
                                    high_low_spread_pct=0.02)
    sample = [f"SYM{i:02d}" for i in range(5)]
    w = CS.calibrate_window(
        "IS", date(2010, 1, 1), date(2010, 12, 31), processed, sample,
    )
    assert w.above_threshold is True
    assert w.above_parametric is True


def test_calibrate_window_below_threshold_for_tight_spreads(tmp_path: Path):
    """0.05% intraday H-L → CS half-spread should be near or below 5bp."""
    processed = _stage_processed(tmp_path, start_date="2010-01-04",
                                    n_days=80, n_symbols=5,
                                    high_low_spread_pct=0.0005)
    sample = [f"SYM{i:02d}" for i in range(5)]
    w = CS.calibrate_window(
        "IS", date(2010, 1, 1), date(2010, 12, 31), processed, sample,
    )
    assert not w.above_threshold


def test_calibrate_window_handles_missing_sample_in_data(tmp_path: Path):
    processed = _stage_processed(tmp_path, start_date="2010-01-04",
                                    n_days=20, n_symbols=3)
    sample = ["NOSUCH1", "NOSUCH2"]  # not in data
    w = CS.calibrate_window(
        "IS", date(2010, 1, 1), date(2010, 12, 31), processed, sample,
    )
    assert w.n_stocks_with_data == 0
    assert w.median_half_spread_bps is None


# ---------------------------------------------------------------------------
# render_markdown
# ---------------------------------------------------------------------------

def _make_window(name: str, median: float | None = 7.0,
                 flagged_above_10: bool = False) -> CS.WindowCalibration:
    return CS.WindowCalibration(
        name=name, start="2010-01-01", end="2014-12-31",
        n_stocks_sampled=50, n_stocks_with_data=45,
        median_half_spread_bps=median,
        p25_half_spread_bps=(median * 0.7 if median is not None else None),
        p75_half_spread_bps=(median * 1.3 if median is not None else None),
        mean_half_spread_bps=(median * 1.05 if median is not None else None),
        above_threshold=flagged_above_10,
        above_parametric=(median is not None and median > 5.0),
    )


def test_render_markdown_no_divergence():
    r = CS.CalibrationReport(
        sample_size_requested=50, seed=1, sample_symbols=["A"],
        parametric_half_spread_bps=5.0, documentation_threshold_bps=10.0,
        windows=[_make_window("IS", median=6.0),
                 _make_window("OOS_A", median=7.5),
                 _make_window("OOS_B", median=4.5)],
        generated_at="2026-05-20T00:00:00Z",
    )
    md = CS.render_markdown(r)
    assert "Within Documentation Threshold" in md
    assert "§6 Compliance" in md
    assert "DIVERGENCE FLAGGED" not in md


def test_render_markdown_flags_divergence():
    r = CS.CalibrationReport(
        sample_size_requested=50, seed=1, sample_symbols=["A"],
        parametric_half_spread_bps=5.0, documentation_threshold_bps=10.0,
        windows=[_make_window("IS", median=20.0, flagged_above_10=True)],
        generated_at="2026-05-20T00:00:00Z",
    )
    md = CS.render_markdown(r)
    assert "DIVERGENCE FLAGGED" in md
    assert "§6 Documentation Discipline" in md
    assert "Do not recalibrate" in md
    assert "20.00" in md or "20.0" in md
    assert "4.0×" in md or "4.0x" in md


def test_render_markdown_handles_window_with_no_data():
    r = CS.CalibrationReport(
        sample_size_requested=50, seed=1, sample_symbols=["A"],
        parametric_half_spread_bps=5.0, documentation_threshold_bps=10.0,
        windows=[_make_window("IS", median=None)],
        generated_at="t",
    )
    md = CS.render_markdown(r)
    # No crash. The empty-window row uses em-dashes.
    assert "IS" in md
    assert "—" in md


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_main_writes_report_and_json(tmp_path: Path):
    processed = _stage_processed(tmp_path, start_date="2010-01-04",
                                    n_days=80, n_symbols=10,
                                    high_low_spread_pct=0.0005)
    report_md = tmp_path / "report.md"
    report_json = tmp_path / "report.json"
    rc = CS.main([
        "--processed-dir", str(processed),
        "--sample-size", "5",
        "--seed", "1",
        "--report-md", str(report_md),
        "--results-json", str(report_json),
    ])
    # Tight spreads → no divergence → rc 0.
    assert rc == 0
    assert report_md.exists()
    assert report_json.exists()
    data = json.loads(report_json.read_text())
    assert data["sample_size_requested"] == 5
    assert data["seed"] == 1
    assert len(data["windows"]) == 3   # IS, OOS_A, OOS_B


def test_main_returns_nonzero_when_divergence_flagged(tmp_path: Path):
    # Stage data with WIDE intraday H-L spread → CS will be far above 10bp.
    processed = _stage_processed(tmp_path, start_date="2010-01-04",
                                    n_days=80, n_symbols=10,
                                    high_low_spread_pct=0.05)  # 5%
    rc = CS.main([
        "--processed-dir", str(processed),
        "--sample-size", "5", "--seed", "1",
        "--report-md", str(tmp_path / "r.md"),
        "--results-json", str(tmp_path / "r.json"),
    ])
    assert rc == 1
