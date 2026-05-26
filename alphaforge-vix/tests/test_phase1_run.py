"""Integration tests for research/phase1_run.py — focus on the SHA anchor
and the orchestrator's plumbing on minimal real inputs."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from research import phase1_run


# ---------------------------------------------------------------------------
# SHA anchor verification
# ---------------------------------------------------------------------------

def test_verify_sha_anchor_succeeds_on_current_design_doc():
    """The Phase 0 cert anchor must match the current VIX_DESIGN.md SHA."""
    sha = phase1_run.verify_sha_anchor()
    assert isinstance(sha, str)
    assert len(sha) == 64


def test_verify_sha_anchor_raises_on_mismatch(tmp_path, monkeypatch):
    """If the cert anchor and the design doc diverge, the orchestrator
    must refuse to run."""
    # Point cert path at a tmp file with a known-wrong SHA.
    bogus_cert = tmp_path / "fake_cert.json"
    bogus_cert.write_text(json.dumps({
        "design_doc_sha": "0" * 64,
        "certified": True,
        "results": {},
    }))
    monkeypatch.setattr(phase1_run, "CERT_JSON", bogus_cert)
    with pytest.raises(phase1_run.SHAAnchorError):
        phase1_run.verify_sha_anchor()


def test_verify_sha_anchor_raises_when_cert_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(phase1_run, "CERT_JSON", tmp_path / "missing.json")
    with pytest.raises(phase1_run.SHAAnchorError):
        phase1_run.verify_sha_anchor()


# ---------------------------------------------------------------------------
# Inputs loader — exercises real Phase 0 data
# ---------------------------------------------------------------------------

def test_load_phase1_inputs_with_real_phase0_data():
    """Loads the actual Phase 0 products. Will SKIP if data not on disk."""
    data_root = Path(__file__).resolve().parents[1] / "data"
    if not (data_root / "vix_indices" / "VIX.csv").exists():
        pytest.skip("Phase 0 CBOE data not on disk")
    if not (data_root / "etps" / "spy.parquet").exists():
        pytest.skip("Phase 0 SPY parquet not on disk")
    inputs = phase1_run.load_phase1_inputs(data_root)
    assert len(inputs.vix_spot) > 5000  # Should be ~9000 rows.
    assert "VIX" in inputs.term_panel.columns
    assert "realized_vol_21" in inputs.spy_panel.columns


def test_run_phase1_end_to_end_on_real_data(tmp_path):
    data_root = Path(__file__).resolve().parents[1] / "data"
    if not (data_root / "vix_indices" / "VIX.csv").exists():
        pytest.skip("Phase 0 CBOE data not on disk")
    if not (data_root / "etps" / "spy.parquet").exists():
        pytest.skip("Phase 0 SPY parquet not on disk")
    results = phase1_run.run_phase1(data_root)
    # 18 + 6 trials.
    assert len(results.vrp_results) == 18
    assert len(results.slope_results) == 6
    # Regime report covers all four buckets.
    assert len(results.regime_report.buckets) == 4

    # JSON-round-trip the whole thing.
    out = results.to_dict()
    s = json.dumps(out, default=phase1_run._json_default)
    parsed = json.loads(s)
    assert parsed["phase_1a_vrp"]["n_trials"] == 18
    assert parsed["phase_1b_slope"]["n_trials"] == 6
    assert parsed["summary"]["n_total_trials"] == 24


def test_write_verdict_md_creates_file(tmp_path):
    data_root = Path(__file__).resolve().parents[1] / "data"
    if not (data_root / "vix_indices" / "VIX.csv").exists():
        pytest.skip("Phase 0 CBOE data not on disk")
    if not (data_root / "etps" / "spy.parquet").exists():
        pytest.skip("Phase 0 SPY parquet not on disk")
    results = phase1_run.run_phase1(data_root)
    verdict_path = tmp_path / "PHASE1_VERDICT.md"
    phase1_run.write_verdict_md(results, verdict_path)
    body = verdict_path.read_text()
    assert "# VIX — Phase 1 Verdict" in body
    assert "Phase 1A — VRP carry" in body
    assert "Phase 1B — Term-structure slope" in body
    assert "Phase 1C — VIX regime characterization" in body
    assert results.design_doc_sha in body
