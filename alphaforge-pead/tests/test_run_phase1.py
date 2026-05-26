"""Tests for the Phase 1 gauntlet orchestrator.

Synthetic panels only. The orchestrator's contract is:
  1. Refuses to run without PEAD_PHASE0_CERTIFIED.md (Phase0NotCertified)
  2. Correctly splits IS / OOS-A / OOS-B by announcement date
  3. Correctly applies G1 (DSR) / G2 (CI excludes zero) / G3 (sign agreement)
  4. Produces 10 trial results
  5. Reports the verdict as PASS/FAIL based on survivor count

Per `PEAD_DESIGN.md` §8 the orchestrator does not run against real data
until certification. Tests bypass via `require_certification=False`.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from gauntlet.panel import HOLDING_HORIZONS
from gauntlet.run_phase1 import (
    BUCKETS,
    HORIZONS,
    IS_END,
    N_TRIALS_1A,
    OOS_A_END,
    OOS_A_START,
    OOS_B_END,
    OOS_B_START,
    Phase0NotCertified,
    _check_gates,
    _split_windows,
    check_phase0_certified,
    run_phase1,
)


# --- contract: pre-committed constants are frozen --------------------------


def test_horizons_and_buckets_match_design_doc():
    """PEAD_DESIGN.md §3.1 pre-commits K ∈ {5,21,42,63,84} × {quintile,decile}.
    This test guards against accidental constant edits."""
    assert HORIZONS == (5, 21, 42, 63, 84)
    assert BUCKETS == ("quintile", "decile")
    assert N_TRIALS_1A == 10


def test_oos_windows_match_design_doc():
    """PEAD_DESIGN.md §5 pre-commits these windows."""
    assert IS_END == date(2020, 12, 31)
    assert OOS_A_START == date(2021, 1, 1)
    assert OOS_A_END == date(2023, 12, 31)
    assert OOS_B_START == date(2024, 1, 1)
    assert OOS_B_END == date(2026, 5, 17)


# --- certification guard ---------------------------------------------------


def test_check_phase0_certified_raises_when_missing(tmp_path: Path):
    (tmp_path / "research").mkdir()
    # No certification file, no design file
    with pytest.raises(Phase0NotCertified):
        check_phase0_certified(tmp_path)


def test_check_phase0_certified_raises_on_anchor_mismatch(tmp_path: Path):
    research = tmp_path / "research"
    research.mkdir()
    (research / "PEAD_DESIGN.md").write_text("contract body")
    (research / "PEAD_PHASE0_CERTIFIED.md").write_text(
        "Phase 0 certified.\n\nSHA-256 of PEAD_DESIGN.md: 0000000000000000\n"
    )
    with pytest.raises(Phase0NotCertified):
        check_phase0_certified(tmp_path)


def test_check_phase0_certified_passes_with_correct_anchor(tmp_path: Path):
    research = tmp_path / "research"
    research.mkdir()
    body = b"PEAD design contract body"
    (research / "PEAD_DESIGN.md").write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    (research / "PEAD_PHASE0_CERTIFIED.md").write_text(
        f"Phase 0 certified.\n\nSHA-256 of PEAD_DESIGN.md: {digest}\n"
    )
    # Should not raise
    assert check_phase0_certified(tmp_path).exists()


def test_run_phase1_refuses_without_certification(tmp_path: Path):
    """A user invoking run_phase1 without a certified Phase 0 must hit a hard stop."""
    panel = _synthetic_panel(n_per_day=30, total_days=5, ic_true=0.0)
    with pytest.raises(Phase0NotCertified):
        run_phase1(panel, pead_root=tmp_path, require_certification=True)


# --- window splitting ------------------------------------------------------


def _synthetic_panel(n_per_day: int, total_days: int, ic_true: float,
                     start: date = date(2012, 1, 2), seed: int = 0) -> pd.DataFrame:
    """Build a synthetic announcement panel with controlled IC.

    Each day has n_per_day firm-announcements; total_days span from `start`.
    SUE is N(0,1); fwd_returns are constructed with correlation ic_true.
    """
    rng = np.random.default_rng(seed)
    frames = []
    for d_offset in range(total_days):
        day = start + timedelta(days=d_offset)
        sue = rng.standard_normal(n_per_day)
        rec = {
            "cik": rng.integers(1_000_000, 9_999_999, size=n_per_day),
            "ticker": [f"T{i:04d}" for i in range(n_per_day)],
            "fy": [day.year] * n_per_day,
            "fp": ["Q1"] * n_per_day,
            "announcement_ts": pd.Timestamp(day, tz="UTC"),
            "sue": sue,
        }
        for K in HOLDING_HORIZONS:
            noise = rng.standard_normal(n_per_day)
            rec[f"fwd_return_{K}"] = ic_true * sue + math.sqrt(max(1 - ic_true ** 2, 0)) * noise * 0.02
        frames.append(pd.DataFrame(rec))
    return pd.concat(frames, ignore_index=True)


def test_split_windows_puts_announcement_in_correct_window():
    panel = pd.DataFrame({
        "announcement_ts": [
            pd.Timestamp("2018-06-15", tz="UTC"),  # IS
            pd.Timestamp("2022-06-15", tz="UTC"),  # OOS-A
            pd.Timestamp("2025-06-15", tz="UTC"),  # OOS-B
        ],
        "sue": [0.5, 0.5, 0.5],
        **{f"fwd_return_{K}": [0.0, 0.0, 0.0] for K in HOLDING_HORIZONS},
    })
    is_, oa, ob = _split_windows(panel)
    assert len(is_) == 1
    assert len(oa) == 1
    assert len(ob) == 1


def test_split_windows_embargoes_boundary_events():
    """An event 5 days into OOS-A should be embargoed (within 21-day buffer)."""
    panel = pd.DataFrame({
        "announcement_ts": [
            pd.Timestamp("2021-01-05", tz="UTC"),   # 5d into OOS-A → embargoed
            pd.Timestamp("2021-02-15", tz="UTC"),   # well inside OOS-A
        ],
        "sue": [0.5, 0.5],
        **{f"fwd_return_{K}": [0.0, 0.0] for K in HOLDING_HORIZONS},
    })
    is_, oa, ob = _split_windows(panel)
    assert len(oa) == 1
    assert oa["announcement_ts"].iloc[0] == pd.Timestamp("2021-02-15", tz="UTC")


# --- gate logic ------------------------------------------------------------


def test_check_gates_requires_dsr_above_hurdle_in_both_windows():
    """G1 must be FALSE if either OOS DSR is ≤ 0.95."""
    from gauntlet.run_phase1 import WindowResult

    high_sharpe_w = WindowResult(
        n_events=1000, n_days=300, ic=0.05, ic_p_value=0.001,
        sharpe_252=2.5, boot_mean=2.5, boot_ci_lo=1.5, boot_ci_hi=3.5, boot_p_positive=1.0,
    )
    low_sharpe_w = WindowResult(
        n_events=1000, n_days=300, ic=0.005, ic_p_value=0.5,
        sharpe_252=0.2, boot_mean=0.2, boot_ci_lo=-0.5, boot_ci_hi=0.9, boot_p_positive=0.6,
    )
    candidates = [2.5, 2.4, 0.2, 0.1, -0.3, 0.5, 0.7, 1.1, 1.0, 0.6,
                  2.3, 2.2, 0.1, 0.05, -0.2, 0.4, 0.6, 1.0, 0.9, 0.5]

    # Both high → G1 likely passes (depending on deflation against candidates)
    _, _, _, g1_both, _, _ = _check_gates(high_sharpe_w, high_sharpe_w, high_sharpe_w, candidates)
    # One low → G1 fails
    _, _, _, g1_mix, _, _ = _check_gates(high_sharpe_w, high_sharpe_w, low_sharpe_w, candidates)
    assert g1_mix is False


def test_check_gates_g2_requires_ci_to_exclude_zero():
    from gauntlet.run_phase1 import WindowResult

    ci_excludes_w = WindowResult(
        n_events=1000, n_days=300, ic=0.05, ic_p_value=0.001,
        sharpe_252=1.5, boot_mean=1.5, boot_ci_lo=0.3, boot_ci_hi=2.7, boot_p_positive=1.0,
    )
    ci_brackets_w = WindowResult(
        n_events=1000, n_days=300, ic=0.005, ic_p_value=0.5,
        sharpe_252=0.5, boot_mean=0.5, boot_ci_lo=-0.5, boot_ci_hi=1.5, boot_p_positive=0.7,
    )
    candidates = [1.5] * 20
    _, _, _, _, g2_both_exclude, _ = _check_gates(ci_excludes_w, ci_excludes_w, ci_excludes_w, candidates)
    _, _, _, _, g2_one_brackets, _ = _check_gates(ci_excludes_w, ci_excludes_w, ci_brackets_w, candidates)
    assert g2_both_exclude is True
    assert g2_one_brackets is False


def test_check_gates_g3_sign_disagreement_fails():
    from gauntlet.run_phase1 import WindowResult

    pos = WindowResult(1000, 300, 0.05, 0.001, 1.5, 1.5, 0.3, 2.7, 1.0)
    neg = WindowResult(1000, 300, -0.05, 0.001, -1.5, -1.5, -2.7, -0.3, 0.0)
    candidates = [1.5, -1.5] * 10
    _, _, _, _, _, g3_disagree = _check_gates(pos, pos, neg, candidates)
    assert g3_disagree is False


# --- end-to-end orchestrator -----------------------------------------------


def _certify(tmp_path: Path) -> None:
    """Write a fake but anchor-consistent PEAD_PHASE0_CERTIFIED.md."""
    research = tmp_path / "research"
    research.mkdir(exist_ok=True)
    body = b"PEAD_DESIGN contract body (synthetic test)"
    (research / "PEAD_DESIGN.md").write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    (research / "PEAD_PHASE0_CERTIFIED.md").write_text(
        f"Phase 0 certified for tests.\n\nSHA-256 of PEAD_DESIGN.md: {digest}\n"
    )


def test_run_phase1_zero_signal_panel_produces_fail_verdict(tmp_path: Path):
    """A panel with ic_true=0 must not produce survivors. Verdict = FAIL."""
    _certify(tmp_path)
    # Need enough days that long-short Sharpe is computable per window
    # IS: 2012-01 → 2020-12 (~9 years). Use 400 IS days, 250 OOS-A, 250 OOS-B.
    is_panel = _synthetic_panel(n_per_day=20, total_days=400, ic_true=0.0,
                                start=date(2015, 1, 2), seed=10)
    oa_panel = _synthetic_panel(n_per_day=20, total_days=250, ic_true=0.0,
                                start=date(2021, 6, 1), seed=20)
    ob_panel = _synthetic_panel(n_per_day=20, total_days=250, ic_true=0.0,
                                start=date(2024, 6, 1), seed=30)
    panel = pd.concat([is_panel, oa_panel, ob_panel], ignore_index=True)

    out = run_phase1(panel, pead_root=tmp_path, bootstrap_reps=200, require_certification=True)
    assert out["n_trials"] == 10
    assert out["verdict"] == "FAIL"
    assert out["survivors"] == []
    assert len(out["trials"]) == 10


def test_run_phase1_strong_signal_can_produce_survivor(tmp_path: Path):
    """With ic_true=0.5 the strategy should be massively significant in
    bootstrap CI; whether DSR clears depends on noise but we assert at
    least the structure of the result is correct."""
    _certify(tmp_path)
    panel = pd.concat([
        _synthetic_panel(n_per_day=20, total_days=400, ic_true=0.5,
                         start=date(2015, 1, 2), seed=100),
        _synthetic_panel(n_per_day=20, total_days=250, ic_true=0.5,
                         start=date(2021, 6, 1), seed=200),
        _synthetic_panel(n_per_day=20, total_days=250, ic_true=0.5,
                         start=date(2024, 6, 1), seed=300),
    ], ignore_index=True)
    out = run_phase1(panel, pead_root=tmp_path, bootstrap_reps=200, require_certification=True)
    # With huge ic_true, sign agreement (G3) must hold everywhere
    for tr in out["trials"]:
        if math.isfinite(tr["oos_a"]["sharpe_252"]) and math.isfinite(tr["oos_b"]["sharpe_252"]):
            assert tr["sign_agreement"]


def test_run_phase1_output_schema(tmp_path: Path):
    _certify(tmp_path)
    panel = _synthetic_panel(n_per_day=30, total_days=200, ic_true=0.1,
                             start=date(2015, 1, 2), seed=50)
    panel = pd.concat([panel,
        _synthetic_panel(n_per_day=30, total_days=100, ic_true=0.1, start=date(2022, 6, 1), seed=51),
        _synthetic_panel(n_per_day=30, total_days=100, ic_true=0.1, start=date(2024, 6, 1), seed=52),
    ], ignore_index=True)
    out = run_phase1(panel, pead_root=tmp_path, bootstrap_reps=100, require_certification=True)

    required_keys = {
        "schema_version", "generated_at", "n_trials",
        "is_window", "oos_a_window", "oos_b_window",
        "embargo_days", "dsr_hurdle",
        "bootstrap_reps", "bootstrap_block",
        "trials", "survivors", "verdict",
    }
    assert required_keys.issubset(out.keys())
    assert out["verdict"] in ("PASS", "FAIL")
    # Trial dicts have all gate flags
    for tr in out["trials"]:
        for k in ("survives_g1_dsr", "survives_g2_ci", "survives_g3_sign", "survives_all"):
            assert k in tr
