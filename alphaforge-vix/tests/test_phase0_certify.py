"""Tests for research.phase0_certify."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from research import phase0_certify as P0
from ingest import validator as V


def _stage_cboe_panel(data_root: Path):
    """Drop a synthetic CBOE panel into data/vix_indices/."""
    indices_dir = data_root / "vix_indices"
    indices_dir.mkdir(parents=True, exist_ok=True)
    # Build per-symbol CSVs in CBOE's MM/DD/YYYY format. Each symbol gets
    # ≥100 rows so the post-download body-size check would have passed.
    starts = {
        "VIX": "01/02/1990",
        "VIX6M": "01/02/2008",
        "VIX3M": "09/18/2009",
        "VIX9D": "01/04/2011",
        "VIX1D": "05/13/2022",
    }
    for sym, start_str in starts.items():
        start = pd.to_datetime(start_str, format="%m/%d/%Y")
        dates = pd.date_range(start, periods=200, freq="B")
        rows = ["DATE,OPEN,HIGH,LOW,CLOSE"]
        for i, d in enumerate(dates):
            v = 15 + i * 0.05
            rows.append(f"{d.strftime('%m/%d/%Y')},{v},{v+0.5},{v-0.5},{v}")
        (indices_dir / f"{sym}.csv").write_text("\n".join(rows) + "\n")


def _stage_spy_parquet(data_root: Path):
    etps = data_root / "etps"
    etps.mkdir(parents=True, exist_ok=True)
    full_idx = pd.date_range("2008-01-01", "2024-12-31", freq="B")
    df = pd.DataFrame({
        "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0,
        "adj_close": 100.0, "volume": 1_000_000,
        "dividends": 0.0, "stock_splits": 0.0,
    }, index=full_idx)
    df.index.name = "date"
    # Inject the 5 known spikes so spike_events validator passes.
    df.loc[pd.Timestamp("2008-10-15"), "close"] = 80.0     # → 21d vol spike
    df.loc[pd.Timestamp("2010-05-06"), "close"] = 95.0     # log_return spike
    df.loc[pd.Timestamp("2015-08-26"), "close"] = 85.0
    df.loc[pd.Timestamp("2018-02-08"), "close"] = 75.0
    df.loc[pd.Timestamp("2020-03-16"), "close"] = 60.0     # COVID Monday
    df.to_parquet(etps / "spy.parquet")


def _stage_svxy_parquet(data_root: Path):
    etps = data_root / "etps"
    etps.mkdir(parents=True, exist_ok=True)
    idx = pd.date_range("2011-10-04", "2025-12-31", freq="B")
    df = pd.DataFrame({"close": 100.0, "volume": 1e6}, index=idx)
    df.index.name = "date"
    boundary = pd.Timestamp("2018-02-27")
    df["regime"] = "pre_restructuring"
    df.loc[df.index >= boundary, "regime"] = "post_restructuring"
    df.to_parquet(etps / "svxy.parquet")


def _stage_vxx_parquet(data_root: Path):
    etps = data_root / "etps"
    etps.mkdir(parents=True, exist_ok=True)
    idx = pd.date_range("2018-01-25", "2025-12-31", freq="B")
    df = pd.DataFrame({"close": 40.0, "volume": 1e6}, index=idx)
    df.index.name = "date"
    df.to_parquet(etps / "vxx.parquet")


def _stage_yf_vix(data_root: Path, cboe_root: Path | None = None):
    """Stage yfinance ^VIX so the cross-check has data."""
    etps = data_root / "etps"
    etps.mkdir(parents=True, exist_ok=True)
    idx = pd.date_range("1990-01-02", "2025-12-31", freq="B")
    df = pd.DataFrame({"close": 18.0, "volume": 0,
                       "open": 18.0, "high": 18.0, "low": 18.0,
                       "adj_close": 18.0, "dividends": 0.0,
                       "stock_splits": 0.0}, index=idx)
    df.index.name = "date"
    df.to_parquet(etps / "vix_yf.parquet")


# ---------------------------------------------------------------------------
# compute_design_hash
# ---------------------------------------------------------------------------

def test_compute_design_hash_missing_doc(tmp_path):
    h = P0.compute_design_hash(tmp_path / "nope.md")
    assert h == "ERROR_DESIGN_DOC_MISSING"


def test_compute_design_hash_deterministic(tmp_path):
    p = tmp_path / "doc.md"
    p.write_text("hello world\n")
    h1 = P0.compute_design_hash(p)
    h2 = P0.compute_design_hash(p)
    assert h1 == h2
    assert len(h1) == 64


# ---------------------------------------------------------------------------
# load_all_inputs — graceful missing handling
# ---------------------------------------------------------------------------

def test_load_all_inputs_returns_none_for_missing_products(tmp_path):
    """All products missing → all fields None, no exception."""
    inputs = P0.load_all_inputs(tmp_path)
    assert inputs.cboe_panel is None
    assert inputs.spy_panel is None
    assert inputs.svxy_df is None
    assert inputs.vxx_df is None
    assert inputs.yf_vix_close is None


def test_load_all_inputs_populates_present_products(tmp_path):
    _stage_cboe_panel(tmp_path)
    _stage_spy_parquet(tmp_path)
    _stage_svxy_parquet(tmp_path)
    _stage_vxx_parquet(tmp_path)
    _stage_yf_vix(tmp_path)
    inputs = P0.load_all_inputs(tmp_path)
    assert inputs.cboe_panel is not None
    assert inputs.spy_panel is not None
    assert inputs.svxy_df is not None
    assert inputs.vxx_df is not None
    assert inputs.yf_vix_close is not None


# ---------------------------------------------------------------------------
# certify — end-to-end with synthetic data
# ---------------------------------------------------------------------------

def test_certify_writes_markdown_and_json(tmp_path):
    _stage_cboe_panel(tmp_path)
    _stage_spy_parquet(tmp_path)
    _stage_svxy_parquet(tmp_path)
    _stage_vxx_parquet(tmp_path)
    _stage_yf_vix(tmp_path)

    design = tmp_path / "VIX_DESIGN.md"
    design.write_text("# placeholder design doc\n")
    out_md = tmp_path / "cert.md"
    out_json = tmp_path / "cert.json"

    certified, results = P0.certify(tmp_path, design, out_md, out_json)
    assert out_md.exists()
    assert out_json.exists()
    body = json.loads(out_json.read_text())
    assert "design_doc_sha" in body
    assert "results" in body
    # Synthetic stage isn't designed to produce a perfect cert — but it must
    # at least populate all check results.
    assert set(body["results"].keys()) >= {
        "term_structure", "spy_spike_events", "etp_availability",
        "vix_cross_consistency", "contango_bias",
    }


def test_certify_returns_certified_when_no_fail(tmp_path):
    """All inputs missing → most checks SKIP, some FAIL. Not certified."""
    design = tmp_path / "VIX_DESIGN.md"
    design.write_text("# doc\n")
    out_md = tmp_path / "cert.md"
    certified, results = P0.certify(tmp_path, design, out_md)
    assert not certified  # term_structure FAILs when panel missing
    assert any(r.status == V.Status.FAIL.value for r in results.values())


# ---------------------------------------------------------------------------
# main (CLI)
# ---------------------------------------------------------------------------

def test_main_returns_nonzero_on_missing_data(tmp_path):
    design = tmp_path / "VIX_DESIGN.md"
    design.write_text("# doc\n")
    rc = P0.main([
        "--data-root", str(tmp_path),
        "--design-doc", str(design),
        "--out", str(tmp_path / "out.md"),
        "--out-json", str(tmp_path / "out.json"),
    ])
    assert rc == 1
