"""Phase 4 gate evaluator.

Reads `research/out/factor_study_results.json` and applies the three-condition
Phase 4 gate (locked in `PHASE4_DESIGN.md` §1) to every cross-sectional factor:

  1. DSR > 0.95 in BOTH OOS windows.
  2. Stationary-bootstrap 95% Sharpe CI excludes zero in BOTH windows.
  3. Sign of OOS Sharpe agrees between the two windows.

A factor passes only when all three conditions hold for both windows.

Outputs:
  research/out/phase4_gate_result.json
  research/out/phase4_gate_result.md
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

OUT_DIR = THIS_DIR / "out"
RESULTS = OUT_DIR / "factor_study_results.json"
TSMOM_RESULTS = OUT_DIR / "tsmom_results.json"
PAIRS_RESULTS = OUT_DIR / "pairs_results.json"

DSR_THRESHOLD = 0.95


def collect_candidate_sharpes(study: dict, *, use_alpha: bool = True) -> List[float]:
    """Trial set for DSR deflation: every net Sharpe computed in the study.

    When `use_alpha=True` and the per-factor block contains a populated
    `ff5_alpha.residual_sharpe`, that alpha-residual Sharpe is used as the
    trial — matching the gate's alpha evaluation. Falls back to raw
    `net.sharpe` per factor when the alpha layer wasn't computed.

    The portfolio-level TSMOM and Pairs studies are read from their own
    JSONs and use the best raw `net_sharpe` from each grid (those studies
    don't currently emit FF5 alphas).
    """
    cands: List[float] = []
    for block_key in ("factors_raw", "factors_sector_neutral"):
        block = study.get(block_key, {}) or {}
        for name, m in block.items():
            sr = None
            if use_alpha:
                ff = m.get("ff5_alpha") or {}
                sr_alpha = ff.get("residual_sharpe")
                if sr_alpha is not None and sr_alpha == sr_alpha:
                    sr = float(sr_alpha)
            if sr is None:
                raw_sr = (m.get("net") or {}).get("sharpe")
                if raw_sr is not None and raw_sr == raw_sr:
                    sr = float(raw_sr)
            if sr is not None:
                cands.append(sr)
    # PHASE4_DESIGN.md §4 also counts the portfolio-level TSMOM and Pairs
    # studies as one trial each. Use the best (max) net_sharpe from each
    # parameter grid as the realized trial Sharpe — that's what a user
    # would report after picking the best config, so it's the right hurdle
    # for the deflation against the rest of the trial set.
    for path in (TSMOM_RESULTS, PAIRS_RESULTS):
        if not path.exists():
            continue
        try:
            blob = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        grid = blob.get("grid") or []
        srs = [
            float(row.get("net_sharpe"))
            for row in grid
            if row.get("net_sharpe") is not None
            and row.get("net_sharpe") == row.get("net_sharpe")
        ]
        if srs:
            cands.append(max(srs))
    return cands


def ci_excludes_zero(lo: float, hi: float) -> bool:
    if lo is None or hi is None:
        return False
    if lo != lo or hi != hi:  # NaN
        return False
    return (lo > 0.0) or (hi < 0.0)


def evaluate_factor(name: str, per_window: Dict[str, dict],
                    candidates: List[float],
                    *,
                    use_alpha: bool = True) -> dict:
    """Per-factor gate evaluation.

    `use_alpha=True` (default): evaluate FF5+UMD alpha-residual Sharpes
    (the Phase 3 residualization layer, applied post-portfolio-formation
    via `compute_portfolio_alpha`). This is the gate the Tier 1 plan
    actually committed to.

    `use_alpha=False`: evaluate raw long-short net Sharpes. Reported as
    a sanity row to show what the gate would have said without the
    residualization layer.
    """
    window_eval: Dict[str, dict] = {}
    sharpes: Dict[str, float] = {}

    for win_name, w in per_window.items():
        if w.get("skipped"):
            window_eval[win_name] = {"skipped": w["skipped"], "passes": False}
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
        sharpes[win_name] = sr
        window_eval[win_name] = {
            "sharpe": sr,
            "n_days": n,
            "bootstrap_ci": [ci_lo, ci_hi],
            "ci_excludes_zero": ci_ok,
            "dsr": dsr,
            "dsr_threshold": DSR_THRESHOLD,
            "dsr_passes": dsr_ok,
            "passes": bool(dsr_ok and ci_ok),
        }

    finite_sharpes = [v for v in sharpes.values() if v == v]
    sign_agreement = (
        len(finite_sharpes) >= 2
        and (all(v > 0 for v in finite_sharpes) or all(v < 0 for v in finite_sharpes))
    )

    all_windows_pass = (
        len(window_eval) > 0
        and all(w.get("passes") for w in window_eval.values())
    )
    survives = bool(all_windows_pass and sign_agreement)

    return {
        "factor": name,
        "windows": window_eval,
        "sign_agreement": sign_agreement,
        "survives": survives,
    }


def write_markdown(report: dict, path: Path) -> None:
    L: List[str] = []
    A = L.append
    cfg = report["config_echo"]
    A("# Phase 4 Gate — Single-Factor Gauntlet Result")
    A("")
    A(
        f"_Universe {cfg.get('universe_size')} names · "
        f"mode={cfg.get('universe_mode')} · "
        f"returns={cfg.get('analysis_returns_mode')} · "
        f"{cfg.get('start')} → {cfg.get('end')}_"
    )
    A("")
    A(f"_Trial set for DSR deflation: **{report['n_candidate_trials']}** Sharpes "
      "(raw + sector-neutral net Sharpes from factor_study.py, plus the best "
      "net Sharpe from each of tsmom_results.json and pairs_results.json when "
      "present). PHASE4_DESIGN.md §4 contemplates 34 trials including a "
      "parallel raw-returns rerun of the panel pipeline; that variant is the "
      "remaining gap and would only widen the rejection by lowering DSRs._")
    A("")
    A("## Gate (pre-committed in PHASE4_DESIGN.md §1)")
    A("")
    A("A factor passes Phase 4 when, in **both** OOS windows:")
    A("")
    A(f"1. Deflated Sharpe Ratio > **{DSR_THRESHOLD}**.")
    A("2. Stationary-bootstrap 95% Sharpe CI excludes zero.")
    A("3. Sign of OOS Sharpe agrees between the two windows.")
    A("")
    survivors = report["survivors"]
    A(f"## Result: **{len(survivors)}** factor(s) survive.")
    A("")
    if survivors:
        A("Survivors:")
        for s in survivors:
            A(f"- `{s}`")
    else:
        A("**No factor cleared the gate.** Every cross-sectional factor failed "
          "at least one of the three conditions in at least one OOS window. "
          "Per Tier 1 plan §4 decision rule, Phase 5 (combination) must clear "
          "the gate alone, or Tier 1 fails.")
    A("")
    A("## Per-factor table")
    A("")
    win_names = report["window_order"]
    head = ["Factor"]
    for w in win_names:
        head += [f"SR ({w})", f"DSR ({w})", f"CI≠0 ({w})"]
    head += ["Sign agree", "Survives"]
    A("| " + " | ".join(head) + " |")
    A("|" + "|".join(["---"] * len(head)) + "|")
    for fac in report["factor_evaluations"]:
        row = [f"`{fac['factor']}`"]
        for w in win_names:
            cell = fac["windows"].get(w, {})
            if cell.get("skipped"):
                row += ["—", "—", "—"]
                continue
            sr = cell.get("sharpe", float("nan"))
            dsr = cell.get("dsr", float("nan"))
            ci_ok = "yes" if cell.get("ci_excludes_zero") else "no"
            row += [f"{sr:+.2f}", f"{dsr:.3f}", ci_ok]
        row += [
            "yes" if fac["sign_agreement"] else "no",
            "**YES**" if fac["survives"] else "no",
        ]
        A("| " + " | ".join(row) + " |")
    A("")
    A("## Failure-mode summary")
    A("")
    fm = report["failure_modes"]
    A(f"- Failed DSR > {DSR_THRESHOLD} in some window: **{fm['fails_dsr']}** of "
      f"{fm['total']} factors.")
    A(f"- Failed CI-excludes-zero in some window: **{fm['fails_ci']}** of "
      f"{fm['total']} factors.")
    A(f"- Failed sign agreement across windows: **{fm['fails_sign']}** of "
      f"{fm['total']} factors.")
    A("")
    A("Generated by `research/phase4_gate.py`.")
    path.write_text("\n".join(L))


def main() -> int:
    if not RESULTS.exists():
        print(f"ERROR: {RESULTS} not found. Run factor_study.py first.", file=sys.stderr)
        return 2

    study = json.loads(RESULTS.read_text())

    # Detect whether the alpha layer was actually computed downstream.
    oos = study.get("oos_windows_neutral") or {}
    has_alpha = any(
        "ff5_alpha" in w
        for per_win in oos.values()
        for w in per_win.values()
        if isinstance(w, dict)
    )
    use_alpha = has_alpha

    candidates = collect_candidate_sharpes(study, use_alpha=use_alpha)
    if len(candidates) < 2:
        print("ERROR: not enough candidate Sharpes to deflate.", file=sys.stderr)
        return 2

    if not oos:
        print("ERROR: factor_study_results.json has no `oos_windows_neutral`.",
              file=sys.stderr)
        return 2

    win_order = [w["name"] for w in study.get("phase4_oos_windows", [])]
    if not win_order:
        first_factor = next(iter(oos.values()))
        win_order = list(first_factor.keys())

    factor_evals = [evaluate_factor(name, per_window, candidates,
                                     use_alpha=use_alpha)
                    for name, per_window in oos.items()]
    survivors = [f["factor"] for f in factor_evals if f["survives"]]

    fails_dsr = sum(
        1 for f in factor_evals
        if any(not w.get("dsr_passes", False) for w in f["windows"].values()
               if not w.get("skipped"))
    )
    fails_ci = sum(
        1 for f in factor_evals
        if any(not w.get("ci_excludes_zero", False) for w in f["windows"].values()
               if not w.get("skipped"))
    )
    fails_sign = sum(1 for f in factor_evals if not f["sign_agreement"])

    report = {
        "config_echo": study.get("config", {}),
        "evaluation_basis": "ff5_alpha_residual" if use_alpha else "raw_long_short_net",
        "n_candidate_trials": len(candidates),
        "candidate_sharpes": candidates,
        "window_order": win_order,
        "dsr_threshold": DSR_THRESHOLD,
        "factor_evaluations": factor_evals,
        "survivors": survivors,
        "failure_modes": {
            "total": len(factor_evals),
            "fails_dsr": fails_dsr,
            "fails_ci": fails_ci,
            "fails_sign": fails_sign,
        },
    }

    out_json = OUT_DIR / "phase4_gate_result.json"
    out_md = OUT_DIR / "phase4_gate_result.md"
    out_json.write_text(json.dumps(report, indent=2, default=float))
    write_markdown(report, out_md)

    print(f"Wrote {out_json}")
    print(f"Wrote {out_md}")
    print(f"Survivors: {len(survivors)} / {len(factor_evals)}")
    if survivors:
        for s in survivors:
            print(f"  PASS: {s}")
    return 0 if survivors else 1


if __name__ == "__main__":
    sys.exit(main())
