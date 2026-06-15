"""Quantify how much the project's four historical DSR implementations disagree.

Across the substrates the Deflated Sharpe Ratio was implemented four different
ways (VIX, crypto, India analytic-σ̂ variants; PEAD empirical-σ̂ variant) and
applied against one shared 0.95 hurdle. This script measures the disagreement
on a realistic grid and writes a machine + human report. The headline question:
*could the choice of DSR estimator have flipped any verdict near the hurdle?*

Run:  python3.13 reports/dsr_variant_divergence.py
"""
from __future__ import annotations

import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import afgauntlet as g  # noqa: E402
from reports import _upstreams as up  # noqa: E402

ANN = 252.0
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")


def main() -> int:
    vix = up.vix_dsr()
    crypto = up.crypto_dsr()
    india = up.india_dsr()
    pead = up.pead_dsr()

    # Realistic grid: the substrates lived at modest Sharpe over ~1-10y OOS,
    # deflated against 10-56 trials.
    sr_grid = [0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0]
    n_grid = [10, 28, 56]
    obs_grid = [252, 504, 1260, 2520]

    rows = []
    max_div = {"vix-canon": 0.0, "crypto-canon": 0.0, "india-canon": 0.0}
    for sr in sr_grid:
        sr_pp = sr / math.sqrt(ANN)
        for N in n_grid:
            for nobs in obs_grid:
                canon = g.deflated_sharpe_ratio(sr, N, nobs)           # Family A (exact, analytic-σ̂)
                d_vix = vix(sr, N, nobs)                               # annualized input
                d_cry = crypto(sr_pp, n_trials=N, skewness=0.0,
                               kurtosis=3.0, n_observations=nobs)      # per-period input
                d_ind = india(sr_pp, n_trials=N, n_obs=nobs,
                              skew=0.0, kurt_excess=0.0)               # per-period input
                rows.append({
                    "sr_ann": sr, "n_trials": N, "n_obs": nobs,
                    "canonical_A": canon, "vix": d_vix,
                    "crypto": d_cry, "india": d_ind,
                })
                max_div["vix-canon"] = max(max_div["vix-canon"], abs(d_vix - canon))
                max_div["crypto-canon"] = max(max_div["crypto-canon"], abs(d_cry - canon))
                max_div["india-canon"] = max(max_div["india-canon"], abs(d_ind - canon))

    # Family C (empirical cross-trial σ̂): PEAD vs canonical from_trials.
    cands = [0.2, 0.4, 0.55, 0.7, 0.9, 1.1, 1.4, 0.3, 0.6, 0.85]
    fam_c = []
    for sr in [0.5, 1.0, 2.0, 2.5]:
        for nobs in [252, 1260]:
            canon_c = g.deflated_sharpe_ratio_from_trials(sr, nobs, cands)
            d_pead = pead(sr, nobs, cands)
            fam_c.append({"sr_ann": sr, "n_obs": nobs,
                          "canonical_C": canon_c, "pead": d_pead,
                          "abs_diff": abs(canon_c - d_pead)})
    max_c = max(r["abs_diff"] for r in fam_c)

    # Could any disagreement flip a verdict? A flip needs one variant > 0.95
    # while another <= 0.95 at the same point.
    flips = [r for r in rows
             if max(r["canonical_A"], r["vix"], r["crypto"], r["india"]) > 0.95
             and min(r["canonical_A"], r["vix"], r["crypto"], r["india"]) <= 0.95]

    os.makedirs(OUT_DIR, exist_ok=True)
    result = {
        "max_abs_divergence_vs_canonical_A": max_div,
        "max_abs_divergence_family_C_pead": max_c,
        "n_grid_points": len(rows),
        "n_verdict_flips_across_variants": len(flips),
        "flip_points": flips[:20],
        "family_C_reconciliation": fam_c,
    }
    with open(os.path.join(OUT_DIR, "dsr_variant_divergence.json"), "w") as fh:
        json.dump(result, fh, indent=2)

    md = _render_md(max_div, max_c, rows, flips, sr_grid)
    with open(os.path.join(OUT_DIR, "dsr_variant_divergence.md"), "w") as fh:
        fh.write(md)

    print(md)
    return 0


def _render_md(max_div, max_c, rows, flips, sr_grid) -> str:
    lines = [
        "# DSR Variant Divergence Report",
        "",
        "Four historical DSR implementations vs the canonical Family-A estimator,",
        "measured across sr∈{0..3} × N∈{10,28,56} × n_obs∈{252..2520}.",
        "",
        "## Max |ΔDSR| vs canonical (Family A: exact E[max], analytic Lo σ̂)",
        "",
        f"- VIX (analytic, exact E[max], no ÷√var):    **{max_div['vix-canon']:.2e}**",
        f"- crypto (analytic, exact E[max], ÷√var):    **{max_div['crypto-canon']:.4f}**",
        f"- India (analytic, *asymptotic* E[max], ÷√var): **{max_div['india-canon']:.4f}**",
        f"- PEAD (empirical cross-trial σ̂) vs canonical Family C: **{max_c:.2e}**",
        "",
        f"## Verdict flips across variants near the 0.95 hurdle: **{len(flips)}** "
        f"of {len(rows)} grid points",
        "",
        "A flip = one variant clears 0.95 while another does not, at the same",
        "(sr, N, n_obs). Zero flips means the estimator choice never changed a",
        "pass/fail decision on this grid.",
        "",
        "## Illustrative slice (N=28, n_obs=1260)",
        "",
        "| sr_ann | canonical_A | vix | crypto | india |",
        "|--------|-------------|-----|--------|-------|",
    ]
    for r in rows:
        if r["n_trials"] == 28 and r["n_obs"] == 1260:
            lines.append(
                f"| {r['sr_ann']:.2f} | {r['canonical_A']:.4f} | {r['vix']:.4f} "
                f"| {r['crypto']:.4f} | {r['india']:.4f} |")
    lines += [
        "",
        "## Interpretation",
        "",
        "- VIX reconciles to canonical to machine precision (same code lineage).",
        "- crypto/India diverge only by the ÷√var placement on the E[max] term",
        "  (and, for India, the asymptotic vs exact E[max] form). The divergence",
        "  is largest at high sr where var_factor departs from 1.",
        "- PEAD's empirical-σ̂ form reconciles to the canonical `from_trials`",
        "  variant to machine precision.",
        "- The flip count is the bottom line: if 0, the historical verdicts are",
        "  robust to the estimator inconsistency.",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
