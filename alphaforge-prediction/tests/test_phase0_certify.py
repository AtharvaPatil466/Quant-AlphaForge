"""Unit tests for research.phase0_certify — SHA computation + cert verdict."""
from __future__ import annotations

import hashlib

import pandas as pd
import pytest

from ingest import schema as S
from ingest.downloader import write_rows_parquet
from validation import validator as V
from research import phase0_certify as C


def _row(ticker="A", category="Crypto", result="yes", settlement_value=1.0,
         close_time=200, entry_snapshot_ts=100, volume_fp=10.0):
    return {
        "ticker": ticker, "event_ticker": "E", "series_ticker": "S",
        "category": category, "market_type": "binary",
        "open_time": 1, "close_time": close_time, "settlement_ts": close_time + 10,
        "result": result, "settlement_value": settlement_value,
        "entry_price": 0.5, "implied_prob": 0.5, "entry_snapshot_ts": entry_snapshot_ts,
        "yes_bid": 0.49, "yes_ask": 0.51, "volume_fp": volume_fp,
    }


# ---------------------------------------------------------------------------
# SHA computation
# ---------------------------------------------------------------------------

def test_compute_design_hash_matches_hashlib(tmp_path):
    p = tmp_path / "design.md"
    content = b"# contract\nsome text\n"
    p.write_bytes(content)
    assert C.compute_design_hash(p) == hashlib.sha256(content).hexdigest()


def test_compute_design_hash_missing_doc(tmp_path):
    assert C.compute_design_hash(tmp_path / "nope.md") == "ERROR_DESIGN_DOC_MISSING"


def test_compute_design_hash_on_real_design_doc():
    from pathlib import Path
    design = Path(__file__).resolve().parent.parent / "research" / "PREDICTION_MARKETS_DESIGN.md"
    h = C.compute_design_hash(design)
    assert len(h) == 64 and h != "ERROR_DESIGN_DOC_MISSING"


# ---------------------------------------------------------------------------
# certify_status
# ---------------------------------------------------------------------------

def test_certify_status_certified_when_all_pass():
    rows = ([_row(f"C{i}", category="Crypto") for i in range(150)]
            + [_row(f"S{i}", category="Sports") for i in range(60)])
    df = pd.DataFrame(rows)[list(S.COLUMNS)].astype(S.DTYPES)
    results = V.run_all_checks(df)
    assert C.certify_status(results) == "CERTIFIED"


def test_certify_status_incomplete_on_empty():
    results = V.run_all_checks(S.empty_frame())  # all SKIP
    assert C.certify_status(results) == "INCOMPLETE"


def test_certify_status_failed_on_violation():
    # 1 row -> coverage FAIL.
    df = pd.DataFrame([_row("A")])[list(S.COLUMNS)].astype(S.DTYPES)
    results = V.run_all_checks(df)
    assert C.certify_status(results) == "FAILED"


# ---------------------------------------------------------------------------
# generate_report end-to-end
# ---------------------------------------------------------------------------

def test_generate_report_certified(tmp_path):
    rdir = tmp_path / "data" / "processed" / "resolved"
    rows = ([_row(f"C{i}", category="Crypto") for i in range(150)]
            + [_row(f"S{i}", category="Sports") for i in range(60)])
    write_rows_parquet(rows, rdir / "part-00000.parquet")

    design = tmp_path / "design.md"
    design.write_bytes(b"contract body")
    out = tmp_path / "CERT.md"

    status = C.generate_report(tmp_path / "data", design, out)
    assert status == "CERTIFIED"
    text = out.read_text()
    assert "Phase 0 Certification: CERTIFIED" in text
    assert hashlib.sha256(b"contract body").hexdigest() in text
    assert "Crypto" in text and "Sports" in text


def test_generate_report_incomplete_when_no_data(tmp_path):
    design = tmp_path / "design.md"
    design.write_bytes(b"x")
    out = tmp_path / "CERT.md"
    status = C.generate_report(tmp_path / "data", design, out)
    assert status == "INCOMPLETE"
    assert "INCOMPLETE" in out.read_text()
