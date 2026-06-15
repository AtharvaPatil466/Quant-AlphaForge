"""Run the power calibration across substrate-matched configurations and write
the MDE report.

Configs are chosen to isolate the two dimensions that drive detectability:
deflation breadth (N trials) and sample length (n_obs per OOS window).

Run:  python3.13 power/run_calibration.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from power import find_mde, load_base_returns, power_curve  # noqa: E402

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")

# (label, n_trials, n_obs_per_window, note)
CONFIGS = [
    ("generous (N=1, 10y, no deflation)", 1, 2520, "absolute statistical floor"),
    ("VIX-like (N=28, 5y windows)", 28, 1260, "substrate #7 deflation + OOS length"),
    ("VIX-long (N=28, 10y windows)", 28, 2520, "how much sample length buys"),
    ("PEAD-like (N=10, ~1.2y OOS)", 10, 300, "short-OOS penalty (substrate #5)"),
]

SHARPE_GRID = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 3.5]

# Observed OOS Sharpes from the closed substrates (per CLAUDE.md), for context.
SUBSTRATE_OBSERVED = {
    "VIX OOS (both windows)": "-0.77 .. +0.55",
    "India OOS (all trials)": "negative (-0.62 .. -4.94)",
    "PEAD OOS point (short window)": "+2.29 .. +2.87 (n_obs 80-127d)",
    "crypto carry": "IC~0.5, Sharpe failed DSR=0.624",
}


def main() -> int:
    noise, source = load_base_returns()
    n_mc = int(os.environ.get("MDE_NMC", "300"))
    boot_reps = int(os.environ.get("MDE_BOOTREPS", "250"))
    print(f"noise substrate: {source}; n_mc={n_mc}, boot_reps={boot_reps}\n")

    results = {"noise_source": source, "n_mc": n_mc, "boot_reps": boot_reps,
               "sharpe_grid": SHARPE_GRID, "configs": []}

    for label, n_trials, n_obs, note in CONFIGS:
        curve = power_curve(SHARPE_GRID, noise, n_obs, n_trials,
                            n_mc=n_mc, boot_reps=boot_reps)
        mde50 = find_mde(curve, 0.5)
        mde80 = find_mde(curve, 0.8)
        entry = {
            "label": label, "n_trials": n_trials, "n_obs_per_window": n_obs,
            "note": note, "mde_power50": mde50, "mde_power80": mde80,
            "curve": [{"sharpe": p.true_sharpe, "power": p.power,
                       "dsr": p.gate_power["dsr"],
                       "bootstrap": p.gate_power["bootstrap"],
                       "sign": p.gate_power["sign"]} for p in curve],
        }
        results["configs"].append(entry)
        print(f"{label}")
        print(f"    MDE@power0.5 = {mde50:.2f}   MDE@power0.8 = {mde80:.2f}   ({note})")

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "mde_calibration.json"), "w") as fh:
        json.dump(results, fh, indent=2)
    md = _render_md(results)
    with open(os.path.join(OUT_DIR, "mde_calibration.md"), "w") as fh:
        fh.write(md)
    print("\n" + md)
    return 0


def _render_md(results: dict) -> str:
    L = [
        "# Gauntlet Power Calibration — Minimum Detectable Effect",
        "",
        f"Noise substrate: **{results['noise_source']}**. "
        f"Monte-Carlo reps: {results['n_mc']}; bootstrap reps: {results['boot_reps']}.",
        "",
        "Each row injects a constant drift onto block-bootstrapped real return",
        "noise so the *population* annualized Sharpe equals the target, then runs",
        "the canonical detection gauntlet (DSR>0.95 + bootstrap-CI excludes zero +",
        "sign agreement, in BOTH OOS windows) and records the detection rate.",
        "",
        "## Minimum detectable true annualized Sharpe",
        "",
        "| Config | N trials | OOS len (each) | MDE@50% power | MDE@80% power |",
        "|--------|----------|----------------|---------------|---------------|",
    ]
    for c in results["configs"]:
        m50 = f"{c['mde_power50']:.2f}" if c["mde_power50"] == c["mde_power50"] else ">3.5"
        m80 = f"{c['mde_power80']:.2f}" if c["mde_power80"] == c["mde_power80"] else ">3.5"
        L.append(f"| {c['label']} | {c['n_trials']} | {c['n_obs_per_window']}d "
                 f"| **{m50}** | **{m80}** |")
    L += ["", "## Power curves (overall detection rate)", ""]
    for c in results["configs"]:
        L.append(f"### {c['label']}")
        L.append("")
        L.append("| true Sharpe | power | DSR gate | bootstrap gate | sign gate |")
        L.append("|-------------|-------|----------|----------------|-----------|")
        for p in c["curve"]:
            L.append(f"| {p['sharpe']:.2f} | {p['power']:.2f} | {p['dsr']:.2f} "
                     f"| {p['bootstrap']:.2f} | {p['sign']:.2f} |")
        L.append("")
    L += [
        "## What the substrates actually produced (context)",
        "",
        "| Substrate | observed OOS Sharpe |",
        "|-----------|---------------------|",
    ]
    for k, v in SUBSTRATE_OBSERVED.items():
        L.append(f"| {k} | {v} |")
    L += [
        "",
        "## Reading this",
        "",
        "- The **DSR gate is the binding constraint** — overall power tracks the",
        "  DSR column almost exactly; sign agreement and the bootstrap CI clear",
        "  far earlier.",
        "- Compare each config's MDE@80% to the observed-Sharpe table. If the MDE",
        "  sits far above what the substrates produced, the eight nulls are a",
        "  **real** result, not a blunt instrument — the alpha that exists at",
        "  retail grade is below the detection floor.",
        "- If the MDE looks *implausibly* high (a real fund would trade a true",
        "  Sharpe well below it with leverage + risk management), that is evidence",
        "  the DSR>0.95-deflated-against-N hurdle is **stricter than economically",
        "  necessary** — some closed substrates may have been correct-but-tradeable",
        "  rejections. Either way the number, not intuition, now settles it.",
    ]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
