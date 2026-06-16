"""Unit tests for research.run_phase1 — the Phase 1 orchestrator's decision logic.

These exercise the orchestrator end-to-end on synthetic, in-memory resolved-
contract frames (NO network, NO parquet store): the loader is monkeypatched to
return a hand-built panel so the gate stack, the power-FIRST ordering, the
IS/OOS calendar split, the deflation denominator, the MVE/non-MVE separation,
the corrected §6 cent-ceiling G4 fee, and the pre-registration refusal can all
be asserted deterministically.

Why this file exists: the orchestrator's decision logic (which cell passes, why,
and the study-level §11 classification) previously had zero dedicated coverage.
A regression here would silently corrupt a verdict — exactly the failure mode
the methodology-integrity discipline is built to prevent.

Design references: `research/PREDICTION_MARKETS_DESIGN.md` §5 (power FIRST,
gates), §6 (cost model — cent-ceiling fee), §11 (decision matrix), §14 (no
post-hoc fee reductions), §15/§16 (SHA anchor, MVE separation).
"""
from __future__ import annotations

import hashlib
import math

import numpy as np
import pandas as pd
import pytest

# Importing the orchestrator FIRST runs its module-level path bootstrap, which
# puts the sibling ``alphaforge-gauntlet/`` on sys.path so ``afgauntlet`` (and
# its ``precommit`` submodule) resolve below — matching how the orchestrator
# itself consumes the shared gauntlet package.
from research import run_phase1 as R  # noqa: E402
from afgauntlet import gate_net_of_fee_edge  # noqa: E402
from afgauntlet.precommit import PreRegistrationError  # noqa: E402
from ingest import schema as S  # noqa: E402
from signals import flb  # noqa: E402


# ---------------------------------------------------------------------------
# Synthetic resolved-contract panel builder (canonical schema, no network).
# ---------------------------------------------------------------------------

def make_panel(prices, results, *, category="Crypto",
               close_start_ns=1_000_000_000_000_000_000,
               close_step_ns=60_000_000_000) -> pd.DataFrame:
    """Build a canonical resolved-contract frame from price/result lists.

    ``close_time`` increments by ``close_step_ns`` per row so the §3 calendar
    midpoint split has spread; with a uniform step the midpoint lands at the
    middle row, so the first half is IS and the second is OOS. ``category`` may
    be a scalar (broadcast) or a per-row list.
    """
    n = len(prices)
    cats = [category] * n if isinstance(category, str) else list(category)
    rows = []
    for i in range(n):
        ct = close_start_ns + i * close_step_ns
        res = results[i]
        rows.append({
            "ticker": f"T{i}", "event_ticker": f"E{i}", "series_ticker": "S",
            "category": cats[i], "market_type": "binary",
            "open_time": ct - 10 * close_step_ns, "close_time": ct,
            "settlement_ts": ct + close_step_ns,
            "result": res, "settlement_value": 1.0 if res == "yes" else 0.0,
            "entry_price": float(prices[i]), "implied_prob": float(prices[i]),
            "entry_snapshot_ts": ct - close_step_ns,
            "yes_bid": max(prices[i] - 0.01, 0.0),
            "yes_ask": min(prices[i] + 0.01, 1.0),
            "volume_fp": 100.0,
        })
    return pd.DataFrame(rows)[list(S.COLUMNS)].astype(S.DTYPES)


def favorite_panel(n_total: int, implied: float, no_per: int,
                   *, category: str = "Politics") -> pd.DataFrame:
    """A (95,100] favorite-bucket panel with an injected positive FLB gap.

    ``implied`` (> 0.95) is the YES price on every row; a NO result is injected
    once every ``no_per`` rows, so the realized YES frequency is
    ``1 - 1/no_per`` and the calibration gap is ``realized - implied`` (positive
    → underpriced favorite, the FLB direction). The same injection cadence is
    used in both calendar halves so the gap is present IS and OOS. Pass
    ``no_per=None`` to inject NO NO results (realized YES frequency 1.0).
    """
    prices = [implied] * n_total
    results = ["yes"] * n_total
    if no_per is not None:
        for k in range(0, n_total, no_per):
            results[k] = "no"
    return make_panel(prices, results, category=category)


def evaluate_all(df: pd.DataFrame) -> tuple[list[R.CellResult], dict]:
    """Run the per-cell gate stack for every enumerated trial + the §11 verdict."""
    cells = flb.enumerate_trials(df)
    split = flb.calendar_midpoint_split(df)
    results = [R.evaluate_cell(c, df, split, len(cells)) for c in cells]
    return results, R.classify_study(results)


def cell_named(results, *, bucket_label, scope):
    """Pick the one evaluated cell with a given bucket + scope."""
    hits = [r for r in results
            if r.bucket_label == bucket_label and r.scope == scope]
    assert len(hits) == 1, f"expected 1 {scope}:{bucket_label}, got {len(hits)}"
    return hits[0]


# ---------------------------------------------------------------------------
# 1. Power runs FIRST — an underpowered cell cannot pass even with a huge edge.
# ---------------------------------------------------------------------------

def test_underpowered_cell_cannot_pass_even_with_great_edge():
    # 20 events total (10/half) << the (95,100] MDE floor (105); realized is a
    # perfect 0.955→1.0 sweep so the raw gap (+0.045) looks great. binary_mde
    # runs FIRST (§5), so the cell is UNDERPOWERED and CANNOT pass.
    df = favorite_panel(20, implied=0.955, no_per=None)  # no NO injected → realized 1.0
    results, study = evaluate_all(df)
    fav = cell_named(results, bucket_label="(95,100)", scope="per-category")

    assert fav.underpowered is True
    assert fav.n_is < fav.mde_floor and fav.n_oos < fav.mde_floor
    assert fav.edge_full > 0.03            # raw edge would clear the gate magnitude
    assert fav.passed is False             # but power blocks it
    assert fav.verdict == "INCONCLUSIVE"   # §11 row 3 — small-N wall
    assert study["headline_verdict"] == "INCONCLUSIVE"
    assert study["n_passed"] == 0


# ---------------------------------------------------------------------------
# 2. A powered, injected-FLB panel → cells PASS and route PROCEED (§11).
# ---------------------------------------------------------------------------

def test_powered_injected_flb_panel_proceeds():
    # 400 events (200/half) >> floor 105; implied 0.955, realized 0.99
    # (1 NO per 100) → gap +0.035 (> the 0.03 magnitude) in both halves. The
    # cent-ceiling fee at p≈0.955 is 0.01 (« the gap), so G4 survives.
    df = favorite_panel(400, implied=0.955, no_per=100)
    results, study = evaluate_all(df)

    fav = cell_named(results, bucket_label="(95,100)", scope="per-category")
    assert fav.underpowered is False
    assert all(fav.gates.values()), fav.gates
    assert fav.passed is True
    assert fav.verdict == "PROCEED"

    assert study["headline_verdict"] == "PROCEED"   # §11 row 1
    assert study["n_passed"] >= 1


# ---------------------------------------------------------------------------
# 3. A powered, perfectly-calibrated null panel → does NOT pass (FP control).
# ---------------------------------------------------------------------------

def test_powered_null_panel_does_not_pass():
    # Powered (400 events) but realized frequency == implied price → zero gap.
    # implied 0.96, 1 NO per 25 rows → realized 0.96 exactly. No FLB-direction
    # gap, so G1 fails; the cell must NOT pass (false-positive control).
    df = favorite_panel(400, implied=0.96, no_per=25)
    results, study = evaluate_all(df)
    fav = cell_named(results, bucket_label="(95,100)", scope="per-category")

    assert fav.underpowered is False
    assert abs(fav.edge_full) < 0.01
    assert fav.gates["G1_calibration_gap"] is False
    assert fav.passed is False
    assert study["n_passed"] == 0
    assert study["headline_verdict"] != "PROCEED"


# ---------------------------------------------------------------------------
# 4. IS/OOS split is by close_time calendar midpoint; a gate failing in EITHER
#    half fails (G1/G2).
# ---------------------------------------------------------------------------

def test_split_is_calendar_midpoint():
    # Uniform 60s step → the calendar midpoint lands at the middle row, so the
    # first half (rows 0..199) is IS and the second (200..399) is OOS.
    df = favorite_panel(400, implied=0.955, no_per=100)
    split = flb.calendar_midpoint_split(df)
    close = df["close_time"].astype("int64").to_numpy()
    expected_mid = (int(close.min()) + int(close.max())) // 2
    assert split.midpoint_ns == expected_mid
    assert split.n_is == 200 and split.n_oos == 200
    assert bool(split.is_mask[0]) is True
    assert bool(split.oos_mask[-1]) is True


def test_gate_failing_in_either_half_fails_the_cell():
    # IS half carries the +0.035 gap; OOS half is ~perfectly calibrated (gap
    # ≈ +0.005, below the 0.03 magnitude). G1 requires the magnitude in BOTH
    # halves → it fails, so the cell cannot pass even though IS looks great and
    # the cell is fully powered.
    n = 400
    prices = [0.955] * n
    results = ["yes"] * n
    for k in range(0, n // 2, 100):        # IS half: 1 NO per 100 → gap +0.035
        results[k] = "no"
    for k in range(n // 2, n, 25):         # OOS half: 1 NO per 25 → realized ≈ implied
        results[k] = "no"
    df = make_panel(prices, results, category="Politics")
    results_cells, _ = evaluate_all(df)
    fav = cell_named(results_cells, bucket_label="(95,100)", scope="per-category")

    assert fav.underpowered is False
    assert fav.edge_is > 0.03               # IS clears the magnitude
    assert fav.edge_oos < 0.03              # OOS does not
    assert fav.gates["G1_calibration_gap"] is False  # both-halves requirement
    assert fav.passed is False


def test_g2_direction_inconsistent_across_halves_fails():
    # IS half shows a positive (favorite) gap; OOS half shows a NEGATIVE gap.
    # G2 (direction consistency across halves, in the FLB direction) must fail.
    n = 400
    prices = [0.955] * n
    results = ["yes"] * n
    for k in range(0, n // 2, 100):        # IS: realized 0.99 → gap +0.035
        results[k] = "no"
    for k in range(n // 2, n, 5):          # OOS: realized 0.80 → gap −0.155
        results[k] = "no"
    df = make_panel(prices, results, category="Politics")
    results_cells, _ = evaluate_all(df)
    fav = cell_named(results_cells, bucket_label="(95,100)", scope="per-category")

    assert fav.edge_is > 0 and fav.edge_oos < 0     # opposite signs across halves
    assert fav.gates["G2_direction_consistency"] is False
    assert fav.passed is False


# ---------------------------------------------------------------------------
# 5. Deflation: N_trials == enumerated count; deflated CI uses 1 − α/N_trials.
# ---------------------------------------------------------------------------

def test_deflation_denominator_and_confidence():
    df = favorite_panel(400, implied=0.955, no_per=100)
    cells = flb.enumerate_trials(df)
    n_trials = len(cells)
    # One non-MVE category present → 4 pooled extreme cells + 4 per-category.
    assert n_trials == 8

    split = flb.calendar_midpoint_split(df)
    r = R.evaluate_cell(cells[0], df, split, n_trials)
    expected_conf = 1.0 - (1.0 - R.CI_CONFIDENCE) / n_trials
    assert r.gate_detail["deflation_confidence"] == pytest.approx(expected_conf)
    # The deflation CI is recorded and is at least as wide a confidence as G3's.
    assert expected_conf > R.CI_CONFIDENCE


# ---------------------------------------------------------------------------
# 6. MVE cells are never pooled with non-MVE (§16).
# ---------------------------------------------------------------------------

def test_mve_cells_never_pooled_with_non_mve():
    # A frame mixing a non-MVE category (Politics) and an MVE category (Exotics).
    # Pooled cells must exist (≥1 non-MVE present) and select ONLY non-MVE rows;
    # the MVE category appears only as its own stand-alone per-category cells.
    n = 200
    cats = (["Politics"] * (n // 2)) + (["Exotics"] * (n // 2))
    df = favorite_panel(n, implied=0.955, no_per=100).assign(category=cats)
    df["category"] = df["category"].astype(S.DTYPES["category"])

    cells = flb.enumerate_trials(df)
    pooled = [c for c in cells if c.scope == "pooled"]
    assert pooled and all(not c.is_mve for c in pooled)

    # A pooled cell's selected frame must contain zero MVE rows.
    pooled_frame = flb.select_frame(df, pooled[0])
    mapped = pooled_frame["category"].astype("object").map(flb.map_category)
    assert not mapped.isin(list(flb.MVE_GROUPS)).any()

    # Study verdicts are computed separately for MVE vs non-MVE.
    study = R.classify_study([R.evaluate_cell(c, df, flb.calendar_midpoint_split(df),
                                              len(cells)) for c in cells])
    assert "mve_verdict" in study and "non_mve_verdict" in study
    assert study["n_mve_cells"] > 0 and study["n_non_mve_cells"] > 0


# ---------------------------------------------------------------------------
# 7. G4 uses the corrected §6 cent-ceiling fee.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("p", [0.1, 0.5, 0.9])
def test_per_contract_fee_is_cent_ceiling_at_c1(p):
    # The corrected per-contract fee is the literal §6 schedule at C=1:
    #   ceil_to_cent(0.07 · P · (1−P)).
    expected = math.ceil(0.07 * p * (1.0 - p) * 100.0 - 1e-9) / 100.0
    assert R.flb_per_unit_fee(p) == pytest.approx(expected)
    # The doubled-fee G4 stress doubles the 0.07 rate BEFORE the cent-ceiling.
    expected_2x = math.ceil(2.0 * 0.07 * p * (1.0 - p) * 100.0 - 1e-9) / 100.0
    assert R.flb_per_unit_fee(p, multiplier=2.0) == pytest.approx(expected_2x)
    # The corrected fee is at least as large as the old unrounded marginal rate
    # (cent-ceiling can only round up) → G4 is HARDER, the only permitted
    # direction (§14 rule 5).
    old_marginal = 0.07 * p * (1.0 - p)
    assert R.flb_per_unit_fee(p) >= old_marginal


def test_thin_edge_cell_fails_g4_under_cent_ceiling_but_passed_old_rate():
    # At P=0.5 the old unrounded marginal fee is 0.0175; the corrected
    # cent-ceiling fee is 0.02. A gross edge of 0.018 PASSES the old gate
    # (0.018 − 0.0175 > 0) but FAILS the corrected gate (0.018 − 0.02 < 0).
    p = 0.5
    gross = 0.018
    old_marginal = 0.07 * p * (1.0 - p)
    new_fee = R.flb_per_unit_fee(p)
    assert old_marginal == pytest.approx(0.0175)
    assert new_fee == pytest.approx(0.02)

    assert gate_net_of_fee_edge(gross, old_marginal).passed is True
    assert gate_net_of_fee_edge(gross, new_fee).passed is False


# ---------------------------------------------------------------------------
# 8. Pre-registration: a tampered design / wrong trial count makes run_phase1
#    refuse BEFORE reading statistics.
# ---------------------------------------------------------------------------

def _write_contract_and_cert(tmp_path):
    """Write a frozen design file + a cert anchoring its current SHA-256."""
    design = tmp_path / "DESIGN.md"
    design.write_text("frozen contract body\n")
    digest = hashlib.sha256(design.read_bytes()).hexdigest()
    cert = tmp_path / "CERTIFIED.md"
    cert.write_text(f"**Design Document SHA-256:** `{digest}`\n")
    return design, cert


def test_run_phase1_succeeds_when_pre_registration_matches(tmp_path, monkeypatch):
    design, cert = _write_contract_and_cert(tmp_path)
    df = favorite_panel(400, implied=0.955, no_per=100)
    monkeypatch.setattr(R, "load_resolved", lambda data_root: df)

    out = R.run_phase1(tmp_path, design, cert)
    assert out.prereg["preregistration_ok"] is True
    assert out.n_trials == out.prereg["n_trials_evaluated"]
    assert out.classification["headline_verdict"] == "PROCEED"


def test_run_phase1_refuses_on_tampered_design(tmp_path, monkeypatch):
    design, cert = _write_contract_and_cert(tmp_path)
    df = favorite_panel(400, implied=0.955, no_per=100)

    # Sentinel: if the orchestrator reads statistics before the integrity gate,
    # this loader would be hit. It must NOT be — the refusal precedes any stat.
    def _exploding_loader(_data_root):
        raise AssertionError("load_resolved must not run on a broken pre-registration")

    # Tamper the design AFTER the cert anchored its hash.
    design.write_text("frozen contract body — TAMPERED after freeze\n")
    monkeypatch.setattr(R, "load_resolved", _exploding_loader)

    with pytest.raises(PreRegistrationError):
        R.run_phase1(tmp_path, design, cert)


def test_run_phase1_refuses_on_trial_count_mismatch(tmp_path, monkeypatch):
    design, cert = _write_contract_and_cert(tmp_path)
    df = favorite_panel(400, implied=0.955, no_per=100)
    monkeypatch.setattr(R, "load_resolved", lambda data_root: df)

    # Force the committed count to disagree with the enumerated count: patch
    # PreRegistration so n_trials_committed is wrong. The verify() call must
    # raise on the count mismatch before a verdict is emitted.
    real_prereg_cls = R.PreRegistration

    def _wrong_count_prereg(*, contract_path, expected_hash, n_trials_committed):
        return real_prereg_cls(contract_path=contract_path,
                               expected_hash=expected_hash,
                               n_trials_committed=n_trials_committed + 1)

    monkeypatch.setattr(R, "PreRegistration", _wrong_count_prereg)
    with pytest.raises(PreRegistrationError):
        R.run_phase1(tmp_path, design, cert)
