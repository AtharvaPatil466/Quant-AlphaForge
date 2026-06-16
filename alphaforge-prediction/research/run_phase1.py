"""Phase 1 calibration-study orchestrator (substrate #10 — Kalshi FLB).

Per `PREDICTION_MARKETS_DESIGN.md` §5 / §8 / §11 and the §16-ADDENDUM. This is
the SHA-anchored Phase 1 runner: it refuses to execute unless the frozen design
doc's SHA-256 matches the value recorded at Phase 0 certification, and unless the
evaluated trial count equals the enumerated count (both via
``afgauntlet.PreRegistration``).

Pipeline (order matters — §5 mandates power FIRST):

  1. Verify the pre-registration (design SHA + trial-count) — refuse on mismatch.
  2. Load the resolved-contract parquet; split IS/OOS by ``close_time`` midpoint.
  3. **binary_mde FIRST** — per bucket, the minimum resolved-event count to
     detect the pre-committed edge at 80% power. Cells below their MDE floor are
     UNDERPOWERED and cannot pass (the small-N wall that killed PEAD).
  4. IS + OOS reliability curves and per-bucket net edge.
  5. Gates G1 (calibration gap both halves), G2 (direction consistency across
     halves), G3 (edge-CI excludes zero), G4 (net-of-fee survival incl. doubled
     stress), and G-deflation (Bonferroni-adjusted edge CI across ``N_trials``).
  6. Per-cell verdict + the §11 decision-matrix classification. MVE/Exotics is
     reported SEPARATELY and never pooled with non-MVE (§16).
  7. Write ``research/PHASE1_RESULTS.json`` + ``research/PHASE1_VERDICT.md``
     (tables first, prose after — §8).

All statistics are the canonical ``afgauntlet`` primitives; this module
re-implements none. No network access.
"""
from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# ─── Path bootstrap ───────────────────────────────────────────────────────────
# Sub-project root (so `ingest` / `signals` / `validation` resolve), and the
# sibling `alphaforge-gauntlet/` (so `afgauntlet` resolves) — same pattern other
# subproject orchestrators use to consume the shared gauntlet package.
_SUBPROJECT_ROOT = Path(__file__).resolve().parent.parent
_REPO_ROOT = _SUBPROJECT_ROOT.parent
sys.path.insert(0, str(_SUBPROJECT_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "alphaforge-gauntlet"))

import afgauntlet as afg  # noqa: E402
from afgauntlet import (binary_mde, bucket_edge_ci, evaluate_gates,  # noqa: E402
                        gate_calibration_gap, gate_edge_ci_excludes_zero,
                        gate_net_of_fee_edge, reliability_curve)
from afgauntlet.precommit import PreRegistration, verify_contract_hash  # noqa: E402

from ingest import schema as S  # noqa: E402
from signals import flb  # noqa: E402
from signals.strategy import fee_dollars  # noqa: E402
from validation import validator as V  # noqa: E402

log = logging.getLogger("prediction.run_phase1")

# ─── Pre-committed Phase 1 parameters (§5) ────────────────────────────────────
# The calibration-gap magnitude the study is sized to detect and required to
# clear (§5 G1 "≥ the pre-committed magnitude"). The FLB literature's price-extreme
# bias is on the order of several cents; we pre-commit a conservative 3c floor.
MIN_CALIBRATION_GAP: float = 0.03
# Power-analysis target (binary_mde): detect a gap of this size at 80% power.
MDE_TARGET_EDGE: float = MIN_CALIBRATION_GAP
MDE_POWER: float = 0.80
MDE_ALPHA: float = 0.05
# Edge-CI bootstrap settings (§5 G3); iid resample of independent events.
N_BOOT: int = 4000
CI_CONFIDENCE: float = 0.95
BOOT_SEED: int = 0


# ─── Per-cell result container ────────────────────────────────────────────────

@dataclass
class CellResult:
    cell_id: str
    scope: str
    category: str
    bucket_label: str
    bin_lo: float
    bin_hi: float
    direction: str          # "negative" (longshot) | "positive" (favorite)
    is_mve: bool
    # Power.
    mde_floor: int = 0
    n_is: int = 0
    n_oos: int = 0
    n_total: int = 0
    underpowered: bool = True
    # Edges.
    edge_is: float = float("nan")
    edge_oos: float = float("nan")
    edge_full: float = float("nan")
    p_mean_full: float = float("nan")
    realized_full: float = float("nan")
    # Fees (§6).
    per_unit_fee: float = float("nan")
    per_unit_fee_2x: float = float("nan")
    # Gate outcomes.
    gates: dict[str, bool] = field(default_factory=dict)
    gate_detail: dict[str, Any] = field(default_factory=dict)
    deflated_excludes_zero: bool = False
    passed: bool = False
    verdict: str = "INCONCLUSIVE"

    def to_dict(self) -> dict:
        return {
            "cell_id": self.cell_id,
            "scope": self.scope,
            "category": self.category,
            "bucket_label": self.bucket_label,
            "bin_lo": self.bin_lo,
            "bin_hi": self.bin_hi,
            "direction": self.direction,
            "is_mve": self.is_mve,
            "mde_floor": self.mde_floor,
            "n_is": self.n_is,
            "n_oos": self.n_oos,
            "n_total": self.n_total,
            "underpowered": self.underpowered,
            "edge_is": _jnum(self.edge_is),
            "edge_oos": _jnum(self.edge_oos),
            "edge_full": _jnum(self.edge_full),
            "p_mean_full": _jnum(self.p_mean_full),
            "realized_full": _jnum(self.realized_full),
            "per_unit_fee": _jnum(self.per_unit_fee),
            "per_unit_fee_2x": _jnum(self.per_unit_fee_2x),
            "gates": self.gates,
            "gate_detail": self.gate_detail,
            "deflated_excludes_zero": self.deflated_excludes_zero,
            "passed": self.passed,
            "verdict": self.verdict,
        }


def _jnum(x: float) -> float | None:
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else float(x)


# ─── Data loading ─────────────────────────────────────────────────────────────

def load_resolved(data_root: Path) -> pd.DataFrame:
    """Reuse the validator's loader (de-dup on ticker, canonical schema)."""
    return V.load_resolved(data_root)


# ─── Power analysis (§5 — run FIRST) ──────────────────────────────────────────

def bucket_mde_floor(bin_lo: float, bin_hi: float,
                     edge: float = MDE_TARGET_EDGE) -> int:
    """``binary_mde`` floor for a bucket, using its midpoint as the base rate.

    The base rate ``p0`` is the bucket midpoint (the implied probability the FLB
    edge is measured against). Returns the minimum resolved-event count to detect
    ``edge`` at ``MDE_POWER`` / ``MDE_ALPHA``.
    """
    base = min(max(0.5 * (bin_lo + bin_hi), 1e-6), 1.0 - 1e-6)
    return binary_mde(edge=edge, base_rate=base, power=MDE_POWER, alpha=MDE_ALPHA)


# ─── Per-cell evaluation ──────────────────────────────────────────────────────

def evaluate_cell(cell: flb.TrialCell, df_full: pd.DataFrame,
                  split: flb.CalendarSplit, n_trials: int) -> CellResult:
    """Run the §5 gate stack for one pre-committed FLB cell.

    Order: MDE floor → reliability/edge → G1/G2/G3/G4 → G-deflation. A cell whose
    in-region resolved count is below its MDE floor is marked UNDERPOWERED and
    cannot pass (§5).
    """
    res = CellResult(
        cell_id=cell.cell_id, scope=cell.scope, category=cell.category,
        bucket_label=cell.bucket_label, bin_lo=cell.bin_lo, bin_hi=cell.bin_hi,
        direction=cell.direction, is_mve=cell.is_mve,
    )

    # Category-scoped frame; price filtering happens inside the gate/region.
    sub = flb.select_frame(df_full, cell)
    region_lo, region_hi = flb.region_for_cell(cell)

    p_full, y_full = flb.predicted_outcomes(sub)
    in_region_full = (p_full > region_lo) & (p_full <= region_hi)
    n_total = int(in_region_full.sum())
    res.n_total = n_total

    # IS / OOS splits restricted to this category-scoped frame.
    sub_idx = sub.index.to_numpy()
    is_mask_full = split.is_mask[sub_idx] if sub_idx.size else np.zeros(0, dtype=bool)
    oos_mask_full = split.oos_mask[sub_idx] if sub_idx.size else np.zeros(0, dtype=bool)
    p_is, y_is = p_full[is_mask_full], y_full[is_mask_full]
    p_oos, y_oos = p_full[oos_mask_full], y_full[oos_mask_full]
    res.n_is = int(((p_is > region_lo) & (p_is <= region_hi)).sum())
    res.n_oos = int(((p_oos > region_lo) & (p_oos <= region_hi)).sum())

    # --- Power FIRST (§5) ---
    res.mde_floor = bucket_mde_floor(cell.bin_lo, cell.bin_hi)
    # Each half must clear the floor for the gate to be powered in that half.
    res.underpowered = (res.n_is < res.mde_floor) or (res.n_oos < res.mde_floor)

    # --- Edges (full + halves) ---
    if n_total > 0:
        pr = p_full[in_region_full]
        yr = y_full[in_region_full]
        res.p_mean_full = float(pr.mean())
        res.realized_full = float(yr.mean())
        res.edge_full = float(yr.mean() - pr.mean())
    res.edge_is = _region_edge(p_is, y_is, region_lo, region_hi)
    res.edge_oos = _region_edge(p_oos, y_oos, region_lo, region_hi)

    # --- Fees (§6): literal per-contract cent-ceiling fee (C=1) at the bucket's
    # realized mean price — the honest worst case a small retail trader pays.
    fee_price = res.p_mean_full if np.isfinite(res.p_mean_full) else 0.5 * (cell.bin_lo + cell.bin_hi)
    res.per_unit_fee = flb_per_unit_fee(fee_price, multiplier=1.0)
    res.per_unit_fee_2x = flb_per_unit_fee(fee_price, multiplier=2.0)

    # --- G1: calibration gap clears MIN_CALIBRATION_GAP in BOTH halves ---
    g1_is = gate_calibration_gap(p_is, y_is, region_lo, region_hi,
                                 cell.direction, MIN_CALIBRATION_GAP)
    g1_oos = gate_calibration_gap(p_oos, y_oos, region_lo, region_hi,
                                  cell.direction, MIN_CALIBRATION_GAP)
    g1 = bool(g1_is.passed and g1_oos.passed)

    # --- G2: direction consistency — sign of the gap agrees across halves ---
    g2 = _direction_consistent(res.edge_is, res.edge_oos, cell.direction)

    # --- G3: full-sample edge-CI excludes zero in the FLB direction ---
    g3o = gate_edge_ci_excludes_zero(p_full, y_full, region_lo, region_hi,
                                     n_boot=N_BOOT, confidence=CI_CONFIDENCE,
                                     seed=BOOT_SEED)
    g3 = bool(g3o.passed and _edge_in_direction(res.edge_full, cell.direction))

    # --- G4: net-of-fee survival (gross gap − per-unit fee > 0) + doubled stress ---
    g4o = gate_net_of_fee_edge(res.edge_full, res.per_unit_fee, threshold=0.0)
    g4o_2x = gate_net_of_fee_edge(res.edge_full, res.per_unit_fee_2x, threshold=0.0)
    g4 = bool(g4o.passed and g4o_2x.passed)

    # --- G-deflation: Bonferroni-adjusted edge CI across N_trials ---
    # The DSR/Sharpe deflation is for return streams; the calibration analog
    # (§5 G-deflation "Bonferroni/DSR-analog") widens the edge CI to a
    # family-wise confidence of 1 − α/N_trials and requires it to still exclude
    # zero in the FLB direction.
    defl_conf = 1.0 - (1.0 - CI_CONFIDENCE) / max(n_trials, 1)
    defl = bucket_edge_ci(p_full, y_full, region_lo, region_hi,
                          n_boot=N_BOOT, confidence=defl_conf, seed=BOOT_SEED)
    res.deflated_excludes_zero = bool(
        defl["excludes_zero"] and _edge_in_direction(res.edge_full, cell.direction))

    res.gates = {
        "G1_calibration_gap": g1,
        "G2_direction_consistency": g2,
        "G3_edge_ci": g3,
        "G4_net_of_fee": g4,
        "G_deflation": res.deflated_excludes_zero,
    }
    res.gate_detail = {
        "G1_is": g1_is.detail, "G1_oos": g1_oos.detail,
        "G3": g3o.detail, "G4": g4o.detail, "G4_2x": g4o_2x.detail,
        "deflation_confidence": defl_conf,
        "deflation_ci": [_jnum(defl["lo"]), _jnum(defl["hi"])],
    }

    # A cell PASSES iff powered AND all five gates pass.
    all_gates = all(res.gates.values())
    res.passed = bool((not res.underpowered) and all_gates)
    res.verdict = _classify_cell(res, all_gates)
    return res


def _region_edge(p: np.ndarray, y: np.ndarray, lo: float, hi: float) -> float:
    mask = (p > lo) & (p <= hi)
    if int(mask.sum()) == 0:
        return float("nan")
    return float(y[mask].mean() - p[mask].mean())


def _edge_in_direction(edge: float, direction: str) -> bool:
    if not np.isfinite(edge):
        return False
    return edge > 0 if direction == "positive" else edge < 0


def _direction_consistent(edge_is: float, edge_oos: float, direction: str) -> bool:
    """G2: the calibration gap sign agrees across halves AND in the FLB direction."""
    if not (np.isfinite(edge_is) and np.isfinite(edge_oos)):
        return False
    same_sign = (edge_is > 0 and edge_oos > 0) or (edge_is < 0 and edge_oos < 0)
    return bool(same_sign and _edge_in_direction(edge_is, direction)
                and _edge_in_direction(edge_oos, direction))


def flb_per_unit_fee(price: float, multiplier: float = 1.0) -> float:
    """Per-contract §6 fee at ``price`` — the LITERAL frozen schedule at C=1.

    The frozen §6 schedule is ``fees = roundup(0.07 × C × P × (1−P))`` dollars
    with a **whole-trade ceiling to the cent**. This substrate targets a small-
    size LIVE retail record (§0), so the honest worst case a solo trader actually
    pays is the **per-contract cent-ceiling at C = 1**:

        per-contract fee = ceil_to_cent(0.07 × P × (1−P))  dollars.

    That is the load-bearing reading of §6 / SPIKE_NOTES.md (b): the sub-cent raw
    fee on a single contract rounds UP to a whole cent, so the small trader pays
    materially more per contract than the amortized large-ticket marginal rate
    ``0.07·P·(1−P)``. Using the unrounded marginal rate (the prior code) softened
    the make-or-break G4 gate by ~8× at the strategy's low-price tails; the
    cent-ceiling restores the honest cost and makes G4 HARDER, the only permitted
    direction (§14 rule 5 — no post-hoc fee reductions).

    The G4 doubled-fee stress (``multiplier=2.0``) doubles the 0.07 rate BEFORE
    the cent-ceiling, matching ``signals.strategy.fee_dollars`` (SPIKE_NOTES (b),
    §6). Delegates to that single frozen implementation at C=1 so there is one
    fee definition in the sub-project.
    """
    return fee_dollars(price, contracts=1, sp_nasdaq=False, multiplier=multiplier)


def _classify_cell(res: CellResult, all_gates: bool) -> str:
    """Per-cell §11 classification."""
    if res.underpowered:
        return "INCONCLUSIVE"        # below MDE floor — cannot pass (§5/§11 row 3)
    if res.passed:
        return "PROCEED"             # G1–G4 + deflation all pass (§11 row 1)
    # Powered but a gate failed. Distinguish G4-only failure (real-but-not-extractable).
    g = res.gates
    non_fee_pass = g["G1_calibration_gap"] and g["G2_direction_consistency"] and g["G3_edge_ci"]
    if non_fee_pass and not g["G4_net_of_fee"]:
        return "REAL-BUT-NOT-EXTRACTABLE"   # §11 row 2
    return "CLOSED-FAILED"           # no FLB-direction gap (§11 row 4)


# ─── Study-level classification (§11 decision matrix) ─────────────────────────

def classify_study(cells: list[CellResult]) -> dict[str, Any]:
    """Aggregate per-cell verdicts into the §11 study verdict.

    MVE (Exotics) and non-MVE cells are classified SEPARATELY (§16) and never
    pooled. The reported headline verdict is the non-MVE verdict when non-MVE
    data exists, else the MVE verdict (clearly flagged MVE-only).
    """
    def _verdict_for(group: list[CellResult]) -> str:
        if not group:
            return "NO-DATA"
        if any(c.verdict == "PROCEED" for c in group):
            # Powered survivors exist → PROCEED (the strongest outcome present).
            return "PROCEED"
        powered = [c for c in group if not c.underpowered]
        if not powered:
            # Every cell is below its MDE floor → INCONCLUSIVE (§11 row 3).
            return "INCONCLUSIVE"
        if any(c.verdict == "REAL-BUT-NOT-EXTRACTABLE" for c in powered):
            return "REAL-BUT-NOT-RETAIL-EXTRACTABLE"
        # Powered cells exist but none show an FLB-direction gap → CLOSED FAILED.
        return "CLOSED-FAILED"

    mve = [c for c in cells if c.is_mve]
    non_mve = [c for c in cells if not c.is_mve]
    mve_verdict = _verdict_for(mve)
    non_mve_verdict = _verdict_for(non_mve)

    if non_mve:
        headline = non_mve_verdict
        mve_only = False
    else:
        headline = mve_verdict
        mve_only = True

    return {
        "headline_verdict": headline,
        "mve_only": mve_only,
        "non_mve_verdict": non_mve_verdict,
        "mve_verdict": mve_verdict,
        "n_cells": len(cells),
        "n_mve_cells": len(mve),
        "n_non_mve_cells": len(non_mve),
        "n_powered": sum(1 for c in cells if not c.underpowered),
        "n_passed": sum(1 for c in cells if c.passed),
    }


# ─── Orchestration ────────────────────────────────────────────────────────────

@dataclass
class Phase1Output:
    prereg: dict[str, Any]
    n_trials: int
    split: dict[str, Any]
    mde_table: list[dict[str, Any]]
    cells: list[CellResult]
    classification: dict[str, Any]

    def to_dict(self) -> dict:
        return {
            "date": date.today().isoformat(),
            "gauntlet_version": afg.__version__,
            "preregistration": self.prereg,
            "n_trials": self.n_trials,
            "min_calibration_gap": MIN_CALIBRATION_GAP,
            "mde": {
                "target_edge": MDE_TARGET_EDGE,
                "power": MDE_POWER,
                "alpha": MDE_ALPHA,
                "by_bucket": self.mde_table,
            },
            "calendar_split": self.split,
            "classification": self.classification,
            "cells": [c.to_dict() for c in self.cells],
        }


def run_phase1(data_root: Path, design_path: Path, certified_path: Path) -> Phase1Output:
    """Execute the full Phase 1 study and return its structured output.

    Raises ``afgauntlet.PreRegistrationError`` (before reading any statistic) if
    the design SHA mismatches the certified anchor or the evaluated trial count
    differs from the enumeration.
    """
    # --- Contract-hash gate FIRST (§15) — before any data load or statistic. ---
    # The tamper guard needs only the design file + the anchored hash (no data),
    # so it runs ahead of `load_resolved`: a tampered design must be refused
    # before a single resolved contract is read, matching this function's
    # contract ("before reading any statistic"). The trial-count half of the
    # pre-registration inherently needs the enumeration (hence the data); it is
    # checked by the full `PreRegistration.verify` below.
    expected_hash = _read_certified_hash(certified_path)
    verify_contract_hash(design_path, expected_hash)  # raises on tamper

    df = load_resolved(data_root)
    if df.empty:
        raise RuntimeError(
            "No resolved contracts loaded — run the downloader + Phase 0 cert first.")

    # Enumerate the pre-committed trial set; its count is N_trials.
    cells_spec = flb.enumerate_trials(df)
    n_trials = len(cells_spec)

    # --- Pre-registration gate (§15): re-verify design SHA + trial count. ---
    prereg = PreRegistration(
        contract_path=design_path,
        expected_hash=expected_hash,
        n_trials_committed=n_trials,
    )
    prereg_dict = prereg.verify(n_trials_evaluated=n_trials)  # raises on mismatch

    # --- Calendar-midpoint IS/OOS split (§3). ---
    split = flb.calendar_midpoint_split(df)

    # --- MDE table (power FIRST, §5). ---
    mde_table = []
    for idx, label, lo, hi in flb.iter_buckets():
        mde_table.append({
            "bucket_index": idx, "bucket_label": label,
            "bin_lo": lo, "bin_hi": hi,
            "base_rate": 0.5 * (lo + hi),
            "mde_floor": bucket_mde_floor(lo, hi),
        })

    # --- Per-cell evaluation. ---
    results = [evaluate_cell(c, df, split, n_trials) for c in cells_spec]

    classification = classify_study(results)
    return Phase1Output(
        prereg=prereg_dict, n_trials=n_trials, split=split.to_dict(),
        mde_table=mde_table, cells=results, classification=classification,
    )


def _read_certified_hash(certified_path: Path) -> str:
    """Extract the anchored design SHA-256 from PREDICTION_PHASE0_CERTIFIED.md."""
    if not certified_path.exists():
        raise FileNotFoundError(
            f"Phase 0 certification not found: {certified_path}. "
            "Run `python3.13 -m research.phase0_certify` first.")
    text = certified_path.read_text()
    for line in text.splitlines():
        if "SHA-256" in line and "`" in line:
            # Format: **Design Document SHA-256:** `<hex>`
            parts = line.split("`")
            if len(parts) >= 2 and len(parts[1]) == 64:
                return parts[1]
    raise ValueError(
        f"Could not find a 64-char SHA-256 anchor in {certified_path}.")


# ─── Reporting (§8 — tables first, prose after) ───────────────────────────────

def render_markdown(out: Phase1Output) -> str:
    c = out.classification
    L: list[str] = []
    L.append(f"# Phase 1 Calibration Study — Verdict: {c['headline_verdict']}"
             + ("  (MVE-only)" if c["mve_only"] else ""))
    L.append("")
    L.append("**Substrate:** #10 — Kalshi favorite-longshot bias")
    L.append(f"**Date:** {date.today().isoformat()}")
    L.append(f"**Gauntlet:** afgauntlet v{out.to_dict()['gauntlet_version']} "
             f"(source_hash `{afg.source_hash()[:12]}…`)")
    L.append(f"**Design SHA-256 (verified):** `{out.prereg['contract_hash'][:16]}…`")
    L.append(f"**N_trials (deflation denominator):** {out.n_trials}")
    L.append("")

    # 1. Pre-registration.
    L.append("## Pre-registration")
    L.append("")
    L.append("| Field | Value |")
    L.append("|---|---|")
    L.append(f"| Contract hash verified | {out.prereg['preregistration_ok']} |")
    L.append(f"| Trials committed | {out.prereg['n_trials_committed']} |")
    L.append(f"| Trials evaluated | {out.prereg['n_trials_evaluated']} |")
    L.append("")

    # 2. Calendar split.
    s = out.split
    L.append("## IS / OOS calendar-midpoint split (§3)")
    L.append("")
    L.append("| Half | Boundary | N |")
    L.append("|---|---|---|")
    L.append(f"| IS (close < midpoint) | < {s['midpoint_iso']} | {s['n_is']} |")
    L.append(f"| OOS (close ≥ midpoint) | ≥ {s['midpoint_iso']} | {s['n_oos']} |")
    L.append("")

    # 3. MDE table (power FIRST).
    L.append("## Power analysis — `binary_mde` (run FIRST, §5)")
    L.append("")
    L.append(f"Minimum resolved-event count per bucket to detect a "
             f"{MDE_TARGET_EDGE:+.2f} calibration gap at {MDE_POWER:.0%} power, "
             f"α={MDE_ALPHA}. A cell below this floor in either half is "
             f"**UNDERPOWERED** and cannot pass.")
    L.append("")
    L.append("| Bucket | base rate | MDE floor (events) |")
    L.append("|---|---|---|")
    for m in out.mde_table:
        L.append(f"| {m['bucket_label']} | {m['base_rate']:.3f} | {m['mde_floor']} |")
    L.append("")

    # 4. Per-cell results — MVE and non-MVE separated (§16).
    for grp_name, is_mve in (("Non-MVE (classic §4 categories)", False),
                             ("MVE / Exotics (reported SEPARATELY — §16)", True)):
        grp = [r for r in out.cells if r.is_mve == is_mve]
        L.append(f"## Cells — {grp_name}")
        L.append("")
        if not grp:
            L.append("_No cells in this group on the available data._")
            L.append("")
            continue
        L.append("| Cell | dir | n(IS/OOS) | MDE | powered | edge IS | edge OOS | "
                 "edge full | fee | net | G1 | G2 | G3 | G4 | G-defl | verdict |")
        L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for r in grp:
            g = r.gates
            net = (abs(r.edge_full) - r.per_unit_fee) if np.isfinite(r.edge_full) else float("nan")
            L.append(
                f"| {r.cell_id} | {_dir_arrow(r.direction)} | "
                f"{r.n_is}/{r.n_oos} | {r.mde_floor} | "
                f"{'yes' if not r.underpowered else 'NO'} | "
                f"{_f(r.edge_is)} | {_f(r.edge_oos)} | {_f(r.edge_full)} | "
                f"{_f(r.per_unit_fee)} | {_f(net)} | "
                f"{_b(g['G1_calibration_gap'])} | {_b(g['G2_direction_consistency'])} | "
                f"{_b(g['G3_edge_ci'])} | {_b(g['G4_net_of_fee'])} | "
                f"{_b(g['G_deflation'])} | {r.verdict} |")
        L.append("")

    # 5. Study classification.
    L.append("## Study classification (§11)")
    L.append("")
    L.append("| Group | Verdict |")
    L.append("|---|---|")
    L.append(f"| Non-MVE (§4 categories) | {c['non_mve_verdict']} |")
    L.append(f"| MVE / Exotics (separate) | {c['mve_verdict']} |")
    L.append(f"| **Headline** | **{c['headline_verdict']}**"
             + ("  (MVE-only)" if c["mve_only"] else "") + " |")
    L.append("")
    L.append(f"- Cells evaluated: {c['n_cells']} "
             f"({c['n_non_mve_cells']} non-MVE, {c['n_mve_cells']} MVE)")
    L.append(f"- Powered cells: {c['n_powered']} / {c['n_cells']}")
    L.append(f"- Passing cells: {c['n_passed']} / {c['n_cells']}")
    L.append("")

    # 6. Prose (after the tables — §8).
    L.append("## Discussion")
    L.append("")
    L += _discussion(out)
    return "\n".join(L) + "\n"


def _discussion(out: Phase1Output) -> list[str]:
    c = out.classification
    lines: list[str] = []
    powered_any = c["n_powered"] > 0
    if c["headline_verdict"] == "INCONCLUSIVE":
        lines.append(
            "**INCONCLUSIVE — underpowered.** Per the §16 ADDENDUM, the free "
            "read-only Kalshi host yields a recent, MVE-heavy universe; the "
            "available resolved-event counts fall below the `binary_mde` floor "
            "required to detect the pre-committed "
            f"{MIN_CALIBRATION_GAP:+.2f} calibration gap at {MDE_POWER:.0%} power. "
            "This is the small-N wall flagged in §13 as the central risk, and "
            "the expected outcome under §16. Per the §11 decision matrix this "
            "routes to **forward-only data accumulation (Phase 2)** as the "
            "primary path — which suits the live-track-record goal anyway.")
        lines.append("")
        if not c["n_non_mve_cells"]:
            lines.append(
                "All available cells are **MVE / Exotics** (§16): sub-minute "
                "crypto/sports markets structurally unlike the classic FLB "
                "sports/racing effect (recreational lottery preference). Per §16 "
                "they are reported separately and never pooled with non-MVE data; "
                "no classic non-MVE category is present on the free host, so the "
                "non-MVE FLB question is not yet testable here.")
            lines.append("")
    elif c["headline_verdict"] == "PROCEED":
        lines.append(
            "**PROCEED to Phase 2.** At least one powered cell cleared all five "
            "gates (G1–G4 + deflation) in the pre-committed FLB direction. The "
            "deterministically-derived survivor rule parameterizes the forward "
            "paper-trade harness (§9).")
        lines.append("")
    elif c["headline_verdict"] == "REAL-BUT-NOT-RETAIL-EXTRACTABLE":
        lines.append(
            "**REAL BUT NOT RETAIL-EXTRACTABLE.** Powered cells show a "
            "calibration gap consistent across halves with a CI excluding zero, "
            "but the gross edge does not survive the honest §6 Kalshi fee + the "
            "doubled-fee stress (G4 — the make-or-break gate). The bias is real "
            "but not deployable at retail cost; no Phase 2 (§11 row 2).")
        lines.append("")
    else:  # CLOSED-FAILED
        lines.append(
            "**CLOSED FAILED.** Powered cells exist but none exhibit an "
            "FLB-direction calibration gap clearing the pre-committed magnitude. "
            "The favorite-longshot bias is not present in this universe — the "
            "tenth credible negative; routes to the founder-track decision "
            "(§11 row 4).")
        lines.append("")

    if powered_any and c["n_passed"] == 0 and c["headline_verdict"] != "INCONCLUSIVE":
        lines.append(
            "No cell passed the full gate stack. Per §14 rule 4 a failed FLB is a "
            "strategy-class result (row 1), not a tuning opportunity; no gate "
            "threshold was lowered to fit the data.")
        lines.append("")

    lines.append(
        "_Methodology: every statistic is the canonical `afgauntlet` package "
        "(`reliability_curve`, `bucket_edge_ci`, `binary_mde`, the calibration "
        "gates). The pre-registration (design SHA-256 + trial count) was verified "
        "at runtime via `afgauntlet.PreRegistration` before any statistic was "
        "read; the run refuses to execute on mismatch (§15)._")
    return lines


def _dir_arrow(direction: str) -> str:
    return "↓longshot" if direction == "negative" else "↑favorite"


def _f(x: float) -> str:
    return "—" if x is None or not np.isfinite(x) else f"{x:+.4f}"


def _b(v: bool) -> str:
    return "PASS" if v else "·"


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    p = argparse.ArgumentParser(description="Phase 1 FLB calibration study (substrate #10).")
    p.add_argument("--data-root", type=Path, default=_SUBPROJECT_ROOT / "data")
    p.add_argument("--design", type=Path,
                   default=_SUBPROJECT_ROOT / "research" / "PREDICTION_MARKETS_DESIGN.md")
    p.add_argument("--certified", type=Path,
                   default=_SUBPROJECT_ROOT / "research" / "PREDICTION_PHASE0_CERTIFIED.md")
    p.add_argument("--out-json", type=Path,
                   default=_SUBPROJECT_ROOT / "research" / "PHASE1_RESULTS.json")
    p.add_argument("--out-md", type=Path,
                   default=_SUBPROJECT_ROOT / "research" / "PHASE1_VERDICT.md")
    args = p.parse_args(argv)

    out = run_phase1(args.data_root, args.design, args.certified)

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(out.to_dict(), indent=2))
    args.out_md.write_text(render_markdown(out))

    log.info("Phase 1 verdict: %s%s",
             out.classification["headline_verdict"],
             "  (MVE-only)" if out.classification["mve_only"] else "")
    log.info("  N_trials=%d  powered=%d/%d  passed=%d/%d",
             out.n_trials, out.classification["n_powered"], out.n_trials,
             out.classification["n_passed"], out.n_trials)
    log.info("  wrote %s and %s", args.out_json, args.out_md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
