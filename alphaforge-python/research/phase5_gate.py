"""Phase 5 gate evaluator.

Reads `research/out/phase5_combination_results.json` and applies the same
three-condition gate as Phase 4 (locked in PHASE4_DESIGN.md §1 and inherited
by PHASE5_DESIGN.md §1) to every combination strategy:

  1. DSR > 0.95 in BOTH OOS windows.
  2. Stationary-bootstrap 95% Sharpe CI excludes zero in BOTH windows.
  3. Sign of OOS Sharpe agrees between the two windows.

DSR deflation runs against the UNION of all trial Sharpes:
  - every Phase 4 panel net Sharpe (raw + sector-neutral)
  - the best net Sharpe from tsmom_results.json and pairs_results.json
  - the per-strategy full-period net Sharpe of every Phase 5 combination

This prevents Phase 5 from laundering its haircut by ignoring Phase 4 trials.

Outputs:
  research/out/phase5_gate_result.json
  research/out/phase5_gate_result.md
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
from research.phase4_gate import collect_candidate_sharpes, ci_excludes_zero

OUT_DIR = THIS_DIR / "out"
PHASE4_RESULTS = OUT_DIR / "factor_study_results.json"
PHASE5_RESULTS = OUT_DIR / "phase5_combination_results.json"

DSR_THRESHOLD = 0.95


def evaluate_strategy(name: str, summary: dict, candidates: List[float],
                       *, use_alpha: bool = True) -> dict:
    win_eval: Dict[str, dict] = {}
    sharpes: Dict[str, float] = {}
    for win, w in (summary.get("oos_windows") or {}).items():
        if w.get("skipped"):
            win_eval[win] = {"skipped": w["skipped"], "passes": False}
            continue
        if use_alpha and "ff5_alpha" in w:
            ff = w["ff5_alpha"]
            sr = float(ff.get("residual_sharpe", float("nan")))
            ci_lo = ff.get("residual_sharpe_ci_lo")
            ci_hi = ff.get("residual_sharpe_ci_hi")
            n = int(ff.get("n_obs", w.get("n_days", 0)))
        else:
            sr = float(w.get("sharpe", float("nan")))
            ci_lo = w.get("bootstrap_sharpe_ci_lo")
            ci_hi = w.get("bootstrap_sharpe_ci_hi")
            n = int(w.get("n_days", 0))
        dsr_obj = deflated_sharpe_ratio(sr, n, candidates)
        dsr = float(dsr_obj.get("dsr", float("nan")))
        ci_ok = ci_excludes_zero(ci_lo, ci_hi)
        dsr_ok = dsr == dsr and dsr > DSR_THRESHOLD
        sharpes[win] = sr
        win_eval[win] = {
            "sharpe": sr,
            "n_days": n,
            "bootstrap_ci": [ci_lo, ci_hi],
            "ci_excludes_zero": ci_ok,
            "dsr": dsr,
            "dsr_threshold": DSR_THRESHOLD,
            "dsr_passes": dsr_ok,
            "passes": bool(dsr_ok and ci_ok),
        }
    finite = [v for v in sharpes.values() if v == v]
    sign_agree = (len(finite) >= 2
                  and (all(v > 0 for v in finite) or all(v < 0 for v in finite)))
    all_pass = (len(win_eval) > 0
                and all(w.get("passes") for w in win_eval.values()))
    return {
        "strategy": name,
        "windows": win_eval,
        "sign_agreement": sign_agree,
        "survives": bool(all_pass and sign_agree),
    }


def write_markdown(report: dict, path: Path) -> None:
    L: List[str] = []
    A = L.append
    A("# Phase 5 Gate — Factor-Combination Gauntlet Result")
    A("")
    A(f"_Trial set for DSR deflation: **{report['n_candidate_trials']}** Sharpes "
      "(Phase 4 panel net Sharpes + TSMOM/Pairs best + Phase 5 combination "
      "full-period Sharpes)._")
    A("")
    A("## Gate (inherited from PHASE4_DESIGN.md §1)")
    A("")
    A("A combination strategy passes Phase 5 when, in **both** OOS windows:")
    A("")
    A(f"1. Deflated Sharpe Ratio > **{DSR_THRESHOLD}**.")
    A("2. Stationary-bootstrap 95% Sharpe CI excludes zero.")
    A("3. Sign of OOS Sharpe agrees between the two windows.")
    A("")
    survivors = report["survivors"]
    A(f"## Result: **{len(survivors)}** strategy/strategies survive.")
    A("")
    if survivors:
        A("Survivors:")
        for s in survivors:
            A(f"- `{s}`")
    else:
        A("**No combination cleared the gate.** Per Tier 1 plan §5 kill "
          "criterion, the gate has FAILED. Tier 1 transitions to Phase 6 "
          "(honest failure writeup + failure-path matrix).")
    A("")
    A("## Per-strategy table")
    A("")
    A("| Strategy | SR (OOS-A) | DSR (OOS-A) | CI≠0 (OOS-A) | SR (OOS-B) | "
      "DSR (OOS-B) | CI≠0 (OOS-B) | Sign agree | Survives |")
    A("|---|---|---|---|---|---|---|---|---|")
    for ev in report["strategy_evaluations"]:
        a = ev["windows"].get("OOS-A", {})
        b = ev["windows"].get("OOS-B", {})
        row = [f"`{ev['strategy']}`"]
        for w in (a, b):
            if w.get("skipped"):
                row += ["—", "—", "—"]
            else:
                row += [
                    f"{w.get('sharpe', float('nan')):+.2f}",
                    f"{w.get('dsr', float('nan')):.3f}",
                    "yes" if w.get("ci_excludes_zero") else "no",
                ]
        row += ["yes" if ev["sign_agreement"] else "no",
                "**YES**" if ev["survives"] else "no"]
        A("| " + " | ".join(row) + " |")
    A("")
    A("Generated by `research/phase5_gate.py`.")
    path.write_text("\n".join(L))


def main() -> int:
    if not PHASE5_RESULTS.exists():
        print(f"ERROR: {PHASE5_RESULTS} not found. Run phase5_combine.py first.",
              file=sys.stderr)
        return 2
    if not PHASE4_RESULTS.exists():
        print(f"ERROR: {PHASE4_RESULTS} not found. Run factor_study.py first.",
              file=sys.stderr)
        return 2

    p4 = json.loads(PHASE4_RESULTS.read_text())
    p5 = json.loads(PHASE5_RESULTS.read_text())

    # Detect alpha layer in Phase 5 strategies
    has_alpha_p5 = any(
        "ff5_alpha" in w
        for s in (p5.get("strategies") or {}).values()
        for w in (s.get("oos_windows") or {}).values()
        if isinstance(w, dict)
    )
    use_alpha = has_alpha_p5

    # Phase 4 trial set (panel + portfolio-level studies, via phase4_gate helper)
    candidates = list(collect_candidate_sharpes(p4, use_alpha=use_alpha))
    # Add Phase 5 strategy full-period Sharpes (still raw, since per-strategy
    # full-period alpha is not currently emitted; documented limitation)
    for name, summary in (p5.get("strategies") or {}).items():
        sr = (summary.get("full_period") or {}).get("sharpe")
        if sr is not None and sr == sr:
            candidates.append(float(sr))

    evaluations = [evaluate_strategy(n, s, candidates, use_alpha=use_alpha)
                   for n, s in (p5.get("strategies") or {}).items()]
    survivors = [e["strategy"] for e in evaluations if e["survives"]]

    report = {
        "config_phase5": p5.get("config", {}),
        "evaluation_basis": "ff5_alpha_residual" if use_alpha else "raw_long_short_net",
        "n_candidate_trials": len(candidates),
        "candidate_sharpes": candidates,
        "dsr_threshold": DSR_THRESHOLD,
        "strategy_evaluations": evaluations,
        "survivors": survivors,
    }

    out_json = OUT_DIR / "phase5_gate_result.json"
    out_md   = OUT_DIR / "phase5_gate_result.md"
    out_json.write_text(json.dumps(report, indent=2, default=float))
    write_markdown(report, out_md)

    print(f"Wrote {out_json}")
    print(f"Wrote {out_md}")
    print(f"Survivors: {len(survivors)} / {len(evaluations)}")
    for s in survivors:
        print(f"  PASS: {s}")
    return 0 if survivors else 1


if __name__ == "__main__":
    sys.exit(main())
