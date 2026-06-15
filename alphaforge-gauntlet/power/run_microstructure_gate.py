"""Characterize the microstructure Phase 1 gate and write the report.

Tests two claims in PHASE1_DESIGN.md before Phase 1 runs:
  §4.4 — "power at |IC|=0.03 is overwhelming; the risk is regime specificity,
          not power."
  §4.5 — deflation is left to G1∧G2∧G3 jointly (the 0.03 threshold is NOT
          raised for the 56 trials).

Run:  python3.13 power/run_microstructure_gate.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from power import microstructure_gate as mg  # noqa: E402

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")

# Per-HALF observation counts.
#  - design: §4.4's assumed ~2.6e7 per half (continuous 100ms over ~30 days/2).
#  - actual: the broken collection captured ~4.5e6 book rows total → ~2.25e6/half.
SCENARIOS = {
    "design_assumed (§4.4)": 2.6e7,
    "actual_collected (broken)": 2.25e6,
}


def main() -> int:
    n_mc = int(os.environ.get("MG_NMC", "40000"))
    out = {"n_mc": n_mc, "horizons_seconds": list(mg.HORIZONS_SECONDS),
           "ic_threshold": mg.IC_THRESHOLD, "n_configs": mg.N_CONFIGS_1A,
           "scenarios": {}}

    for sc_name, obs in SCENARIOS.items():
        null_res = mg.simulate_config(mg.null_ic_vector(), obs, n_mc=n_mc, seed=1)
        fwer = mg.family_wise_fp(null_res.pass_rate)
        # Power: a true IC bump of 0.03 (threshold) and 0.05, peaked at each horizon.
        power = {}
        for peak_ic in (0.03, 0.05):
            by_h = {}
            for k in mg.HORIZONS_SECONDS:
                alt = mg.alternative_ic_vector(k, peak_ic)
                r = mg.simulate_config(alt, obs, n_mc=n_mc, seed=2)
                by_h[k] = r.pass_rate
            power[peak_ic] = by_h
        out["scenarios"][sc_name] = {
            "obs_per_half": obs,
            "n_eff_by_horizon": dict(zip(mg.HORIZONS_SECONDS, null_res.n_eff_by_horizon)),
            "null_per_config_pass_rate": null_res.pass_rate,
            "null_g1_rate": null_res.g1_rate,
            "null_family_wise_fp_8cfg": fwer,
            "power": power,
        }

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "microstructure_gate.json"), "w") as fh:
        json.dump(out, fh, indent=2)
    md = _render(out)
    with open(os.path.join(OUT_DIR, "microstructure_gate.md"), "w") as fh:
        fh.write(md)
    print(md)
    return 0


def _render(out: dict) -> str:
    L = [
        "# Microstructure Phase 1 Gate — Operating Characteristics",
        "",
        "Freeze-safe pre-characterization (synthetic null + injected IC; no real",
        "ICs, no book data, contract untouched). Gate = G1(|IC|≥0.03 at peak, both",
        "halves) ∧ G2(sign agree) ∧ G3(peak within ±1). Configs in 1a = 8.",
        f"Monte-Carlo reps per cell: {out['n_mc']}.",
        "",
        "## 1. Effective sample size collapses with horizon",
        "",
        "§4.4 reasons from the raw observation count. But K-horizon returns at",
        "100 ms overlap, so n_eff ≈ N / (K × 10). The IC null SE = 1/√(n_eff−1):",
        "",
        "| horizon | " + " | ".join(f"{k}s" for k in out["horizons_seconds"]) + " |",
        "|---|" + "---|" * len(out["horizons_seconds"]),
    ]
    for sc, d in out["scenarios"].items():
        neff = d["n_eff_by_horizon"]
        L.append(f"| n_eff ({sc}) | " +
                 " | ".join(f"{neff[str(k)] if str(k) in neff else neff[k]:,.0f}"
                           for k in out["horizons_seconds"]) + " |")
    # SE row for the design scenario
    import math
    dd = out["scenarios"]["design_assumed (§4.4)"]["n_eff_by_horizon"]
    L.append("| IC null SE (design) | " +
             " | ".join(f"{1/math.sqrt(max((dd[str(k)] if str(k) in dd else dd[k])-1,1)):.3f}"
                        for k in out["horizons_seconds"]) + " |")
    L += [
        "",
        "At the 1 h horizon the *design's own* data assumption yields only a few",
        "hundred effective observations — so |IC|≥0.03 is **not** a rare event",
        "under the null there, even though it is ~20σ at the 1 s horizon.",
        "",
        "## 2. False-positive rate under the null",
        "",
        "| scenario | per-config pass rate | family-wise P(≥1 false survivor / 8 cfg) |",
        "|---|---|---|",
    ]
    for sc, d in out["scenarios"].items():
        L.append(f"| {sc} | {d['null_per_config_pass_rate']:.4f} "
                 f"| {d['null_family_wise_fp_8cfg']:.4f} |")
    L += [
        "",
        "## 3. Detection power (true IC peaked at each horizon)",
        "",
    ]
    for sc, d in out["scenarios"].items():
        L.append(f"### {sc}")
        L.append("")
        L.append("| true peak IC | " +
                 " | ".join(f"{k}s" for k in out["horizons_seconds"]) + " |")
        L.append("|---|" + "---|" * len(out["horizons_seconds"]))
        for peak_ic, by_h in d["power"].items():
            L.append(f"| {peak_ic} | " +
                     " | ".join(f"{by_h[str(k)] if str(k) in by_h else by_h[k]:.2f}"
                               for k in out["horizons_seconds"]) + " |")
        L.append("")
    L += [
        "## 4. How to read the eventual Phase 1 verdict",
        "",
        "- §4.4's 'power is overwhelming' is **true at short horizons** (≤30 s)",
        "  and **false at long horizons** (≥300 s), where n_eff is tiny because",
        "  of return overlap — this holds even under the design's own data count.",
        "- Because G1 selects the **peak across all 7 horizons**, the long-horizon",
        "  noise inflates the peak: under the null the gate preferentially mints",
        "  spurious **long-horizon** survivors. G2+G3 (the two-half checks) deflate",
        "  this but do not eliminate it — quantified in §2 above.",
        "- Practical rule for the verdict: a survivor at K ≥ 300 s deserves far",
        "  more skepticism than one at K ≤ 30 s, and ALL survivors should be",
        "  reported with stationary-bootstrap IC CIs (afgauntlet), not the raw",
        "  1/√N intuition. A K ≤ 1 s survivor is already flagged non-exploitable",
        "  at L4 latency by the design's own §7.",
        "- This does not change the frozen gates; it tells you which survivors are",
        "  real and which are autocorrelation artifacts.",
        "",
        "## 5. A design observation (for Phase 1.x, not this frozen contract)",
        "",
        "G1 selects the peak by **raw |IC|** across 7 horizons whose null SEs differ",
        "~30× (0.001 at 1 s vs 0.037 at 1 h). Picking the argmax of raw |IC| over",
        "heteroskedastic estimates biases the peak toward the noisiest horizon — so",
        "even a genuine short-horizon signal often loses the peak to long-horizon",
        "noise, which both lowers power AND concentrates false positives at long K.",
        "A z-scored peak (|IC| / SE_horizon) would compare like-for-like. This is a",
        "note for any future Phase 1.x contract; it does not alter the current one.",
        "",
        "## 6. Modeling caveats (do not over-read the exact percentages)",
        "",
        "- n_eff uses the overlap approximation n_eff ≈ N/(K×10); the true IC",
        "  effective-N also depends on the signal's own autocorrelation (set to 1 s",
        "  here) and is approximate. The **direction and order of magnitude are",
        "  robust** (long-horizon SE near/above 0.03 even under the design's data),",
        "  but the exact FWER moves with `horizon_corr_rho` and `signal_autocorr`.",
        "- Halving the deflation (n_eff×2 at 1 h) still leaves SE≈0.026 ≈ the 0.03",
        "  threshold — the leak does not disappear under generous assumptions.",
        "- The broken-collection power table is non-monotone in true IC because at",
        "  n_eff≈62 (1 h) the empirical peak is noise-dominated: pass rate ≈ null",
        "  size regardless of the true signal, i.e. the gate is **non-informative**",
        "  on that data. This is the strongest argument for the recollection the",
        "  Phase 0 recovery already requires.",
    ]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
