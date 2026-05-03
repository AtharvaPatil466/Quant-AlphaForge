"""Tier 2 Phase 2 gate evaluator.

Reads `research/out/tier2/tier2_phase2_results.json` and applies the
3-condition Tier 2 gate (TIER2_DESIGN.md §2 conditions 1-3; condition
4 is the forward paper-trade in Phase 3) to each strategy.

Outputs:
  research/out/tier2/tier2_phase2_gate.json
  research/out/tier2/tier2_phase2_gate.md
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List

THIS_DIR = Path(__file__).resolve().parent
PROJECT_DIR = THIS_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from research.factor_study import deflated_sharpe_ratio

OUT_DIR = THIS_DIR / "out" / "tier2"
RESULTS = OUT_DIR / "tier2_phase2_results.json"

DSR_THRESHOLD = 0.95


def ci_excludes_zero(lo, hi) -> bool:
    if lo is None or hi is None:
        return False
    if lo != lo or hi != hi:
        return False
    return (lo > 0.0) or (hi < 0.0)


def main() -> int:
    if not RESULTS.exists():
        print(f"ERROR: {RESULTS} not found. Run tier2_gauntlet.py first.",
              file=sys.stderr)
        return 2

    blob = json.loads(RESULTS.read_text())
    strategies = blob.get("strategies", {})
    if not strategies:
        print("ERROR: no strategies found.", file=sys.stderr)
        return 2

    # Trial set: per-strategy alpha-residual full-period Sharpe, OR raw if
    # alpha not computed. Use unique values so duplicate strategies (volcap,
    # ext) don't inflate the trial count.
    candidates = []
    for name, s in strategies.items():
        full_sr = s.get("full_period", {}).get("sharpe")
        if full_sr is not None and full_sr == full_sr:
            candidates.append(round(float(full_sr), 6))
    candidates = sorted(set(candidates))
    print(f"Unique candidate trial Sharpes: {len(candidates)}")

    eval_basis = "ff5_alpha_residual"
    win_order = ["OOS-A", "OOS-B"]

    evaluations = []
    for name, s in strategies.items():
        win_eval: Dict[str, dict] = {}
        sharpes: Dict[str, float] = {}
        for win in win_order:
            w = s.get("oos_windows", {}).get(win, {})
            if w.get("skipped"):
                win_eval[win] = {"skipped": w["skipped"], "passes": False}
                continue
            ff = w.get("ff5_alpha", {})
            sr = float(ff.get("residual_sharpe", float("nan")))
            ci_lo = ff.get("residual_sharpe_ci_lo")
            ci_hi = ff.get("residual_sharpe_ci_hi")
            n = int(ff.get("n_obs", w.get("n_days", 0)))
            dsr_obj = deflated_sharpe_ratio(sr, n, candidates)
            dsr = float(dsr_obj.get("dsr", float("nan")))
            ci_ok = ci_excludes_zero(ci_lo, ci_hi)
            dsr_ok = dsr == dsr and dsr > DSR_THRESHOLD
            sharpes[win] = sr
            win_eval[win] = {
                "alpha_residual_sharpe": sr,
                "n_obs": n,
                "bootstrap_ci": [ci_lo, ci_hi],
                "ci_excludes_zero": ci_ok,
                "dsr": dsr,
                "dsr_passes": dsr_ok,
                "passes_conditions_1_2": bool(dsr_ok and ci_ok),
            }
        finite = [v for v in sharpes.values() if v == v]
        sign_agree = (len(finite) >= 2 and
                      (all(v > 0 for v in finite) or all(v < 0 for v in finite)))
        all_pass = (len(win_eval) > 0 and
                    all(w.get("passes_conditions_1_2") for w in win_eval.values()))
        survives_phase2 = bool(all_pass and sign_agree)
        # Near-miss criterion for §5.2 outcome 2: alpha-residual SR ≥ +1.5 in both
        near_miss = (len(finite) >= 2 and all(v >= 1.5 for v in finite))
        evaluations.append({
            "strategy": name,
            "windows": win_eval,
            "sign_agreement": sign_agree,
            "survives_phase2_gate_1_2_3": survives_phase2,
            "near_miss_alpha_above_1_5": near_miss,
        })

    survivors = [e["strategy"] for e in evaluations if e["survives_phase2_gate_1_2_3"]]
    near_misses = [e["strategy"] for e in evaluations
                   if not e["survives_phase2_gate_1_2_3"] and e["near_miss_alpha_above_1_5"]]

    # Pre-committed §5.2 outcome
    if survivors:
        outcome = "outcome_1_pass"
        outcome_text = (f"≥ 1 strategy clears conditions 1-3. Advance highest-DSR "
                        f"survivor to Phase 3 forward paper-trade.")
    elif near_misses:
        outcome = "outcome_2_near_miss"
        outcome_text = (f"0 strategies clear 1-3 but {len(near_misses)} have "
                        f"alpha-residual SR ≥ +1.5 in both windows. Activate "
                        f"the Tier 2.5 contingent (§6.3): MV-126-R1k on paid "
                        f"Russell 1000 data.")
    else:
        outcome = "outcome_3_fail"
        outcome_text = (f"0 strategies clear 1-3 and none has alpha-residual "
                        f"SR ≥ +1.5 in both windows. Tier 2 has FAILED. "
                        f"Transition to TIER2_DESIGN.md §7 reset.")

    report = {
        "config": blob.get("config", {}),
        "evaluation_basis": eval_basis,
        "n_unique_candidate_trials": len(candidates),
        "candidate_sharpes": candidates,
        "dsr_threshold": DSR_THRESHOLD,
        "strategy_evaluations": evaluations,
        "survivors_phase2": survivors,
        "near_misses": near_misses,
        "phase2_outcome": outcome,
        "phase2_outcome_text": outcome_text,
    }
    out_json = OUT_DIR / "tier2_phase2_gate.json"
    out_json.write_text(json.dumps(report, indent=2, default=float))

    # Markdown writeup
    L = []
    A = L.append
    A("# Tier 2 Phase 2 Gate Result")
    A("")
    A(f"_Evaluation basis: **{eval_basis}** · "
      f"unique trial set size: **{len(candidates)}** · "
      f"DSR threshold: **{DSR_THRESHOLD}**_")
    A("")
    A("## Per-strategy table")
    A("")
    A("| Strategy | OOS-A α-SR | DSR-A | CI≠0 | OOS-B α-SR | DSR-B | CI≠0 | "
      "Sign | Survives 1-2-3 | Near-miss |")
    A("|---|---:|---:|---|---:|---:|---|---|---|---|")
    for ev in evaluations:
        a = ev["windows"].get("OOS-A", {})
        b = ev["windows"].get("OOS-B", {})
        row = [f"`{ev['strategy']}`"]
        for w in (a, b):
            if w.get("skipped"):
                row += ["—", "—", "—"]
                continue
            row += [
                f"{w.get('alpha_residual_sharpe', float('nan')):+.2f}",
                f"{w.get('dsr', float('nan')):.3f}",
                "yes" if w.get("ci_excludes_zero") else "no",
            ]
        row += [
            "yes" if ev["sign_agreement"] else "no",
            "**YES**" if ev["survives_phase2_gate_1_2_3"] else "no",
            "yes" if ev["near_miss_alpha_above_1_5"] else "no",
        ]
        A("| " + " | ".join(row) + " |")
    A("")
    A("## Pre-committed outcome")
    A("")
    A(f"**{outcome.replace('_', ' ').upper()}** — {outcome_text}")
    A("")
    A("Generated by `research/tier2_gate.py`.")
    out_md = OUT_DIR / "tier2_phase2_gate.md"
    out_md.write_text("\n".join(L))

    print(f"Wrote {out_json}")
    print(f"Wrote {out_md}")
    print(f"Survivors (gate 1-2-3): {len(survivors)}")
    print(f"Near-misses (α ≥ +1.5 both): {len(near_misses)}")
    print(f"Phase 2 outcome: {outcome}")
    return 0 if survivors else (1 if near_misses else 2)


if __name__ == "__main__":
    sys.exit(main())
