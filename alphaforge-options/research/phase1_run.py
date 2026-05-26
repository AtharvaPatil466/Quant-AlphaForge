"""Phase 1 orchestrator for Substrate #9 (VRP Iron Condor).

Per SUBSTRATE9_DESIGN.md §9. Runs T1 (base trial: 16Δ/5Δ, VRP>0, no
VIX filter) on in-sample monthly cycles (2004-01-02 → 2014-12-31).

Pass criterion (§9.1):
    1. Pearson correlation(VRP_at_entry, cycle_pnl) > 0
    2. Positive sign in ≥ 7 of 11 IS calendar years
    3. Positive in ≥ 5 of 9 IS years excluding 2008 and 2009

Writes:
    research/PHASE1_RESULTS.json   — machine output
    research/PHASE1_VERDICT.md     — human verdict

SHA-guard: refuses to run if SUBSTRATE9_DESIGN.md hash ≠ anchor in
SUBSTRATE9_PHASE0_CERTIFIED.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from ingest.bs_pricer import open_condor, cycle_pnl as condor_pnl
from signals.vrp_filter import build_vrp_panel, entry_signal, monthly_cycle_dates

log = logging.getLogger("options.phase1")


class PhaseLockError(RuntimeError):
    """Raised when the SHA guard detects design-doc tampering after Phase 0 cert."""

RESEARCH_DIR = Path(__file__).parent
DESIGN_DOC = RESEARCH_DIR / "SUBSTRATE9_DESIGN.md"
CERT_DOC = RESEARCH_DIR / "SUBSTRATE9_PHASE0_CERTIFIED.md"
RESULTS_JSON = RESEARCH_DIR / "PHASE1_RESULTS.json"
VERDICT_MD = RESEARCH_DIR / "PHASE1_VERDICT.md"

IS_START = "2004-01-02"
IS_END = "2014-12-31"

# T1 parameters (base trial)
SHORT_DELTA = 0.16
LONG_DELTA = 0.05
VRP_THRESHOLD = 0.0      # VRP > 0
VIX_FILTER = None        # no VIX level filter

# Risk-free rate fallback (annualized decimal) — §2.3 / §14.7
RFREE_FALLBACK: dict[int, float] = {
    2004: 0.035, 2005: 0.035, 2006: 0.035, 2007: 0.035, 2008: 0.035,
    2009: 0.001, 2010: 0.001, 2011: 0.001, 2012: 0.001, 2013: 0.001,
    2014: 0.001,
}

# Baseline transaction cost per share (close side only) — §7.1
# Open costs are implicitly deducted from premium at entry in this model.
TX_COST_CLOSE_PER_SHARE = 0.07   # ~$0.07/share for 4 legs × 1 transaction


# ---------------------------------------------------------------------------
# SHA guard
# ---------------------------------------------------------------------------

def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _extract_anchor(cert_path: Path) -> str:
    """Pull the SHA anchor line from the cert markdown."""
    for line in cert_path.read_text(encoding="utf-8").splitlines():
        if "SUBSTRATE9_DESIGN.md` SHA-256:" in line:
            # format: `...SHA-256: \`<hash>\``
            return line.split("`")[-2].strip()
    raise ValueError(f"SHA anchor not found in {cert_path}")


def sha_guard() -> None:
    if not DESIGN_DOC.exists():
        raise PhaseLockError(f"ABORT: {DESIGN_DOC} not found.")
    if not CERT_DOC.exists():
        raise PhaseLockError(f"ABORT: {CERT_DOC} not found — run phase0_certify first.")

    actual = _sha256(DESIGN_DOC)
    expected = _extract_anchor(CERT_DOC)

    if actual != expected:
        raise PhaseLockError(
            f"ABORT: SUBSTRATE9_DESIGN.md SHA mismatch.\n"
            f"  expected: {expected}\n"
            f"  actual:   {actual}\n"
            "The design doc was edited after Phase 0 certification. "
            "This constitutes peeking — Phase 1 cannot run."
        )
    log.info("SHA guard PASS: %s", actual[:16])


# ---------------------------------------------------------------------------
# Risk-free rate helper
# ---------------------------------------------------------------------------

def rfree_for_date(dt: pd.Timestamp) -> float:
    return RFREE_FALLBACK.get(dt.year, 0.045)


# ---------------------------------------------------------------------------
# IS cycle P&L computation
# ---------------------------------------------------------------------------

def run_is_cycles(panel: pd.DataFrame, verbose: bool = False) -> pd.DataFrame:
    """Run T1 iron condor on all IS monthly cycles. Returns cycle-level DataFrame."""
    cycles = monthly_cycle_dates(panel, IS_START, IS_END)
    records = []

    for cyc in cycles:
        entry_dt = cyc["entry_date"]
        roll_dt = cyc["roll_date"]
        T_entry = cyc["T_entry"]
        T_roll = cyc["T_roll"]

        row_entry = panel.loc[entry_dt]
        row_roll = panel.loc[roll_dt]

        vrp_val = float(row_entry["vrp"])
        vix_entry = float(row_entry["vix"])
        spy_entry = float(row_entry["spy_close"])
        sigma_entry = vix_entry / 100.0
        r_entry = rfree_for_date(entry_dt)

        # VRP entry filter (T1: VRP > 0, no VIX filter)
        if vrp_val <= VRP_THRESHOLD:
            records.append(
                {
                    "entry_date": entry_dt,
                    "roll_date": roll_dt,
                    "vrp": vrp_val,
                    "entered": False,
                    "pnl_per_share": np.nan,
                    "premium": np.nan,
                }
            )
            continue

        sigma_roll = float(row_roll["vix"]) / 100.0
        spy_roll = float(row_roll["spy_close"])
        r_roll = rfree_for_date(roll_dt)

        try:
            cyc_obj = open_condor(spy_entry, T_entry, r_entry, sigma_entry, SHORT_DELTA, LONG_DELTA)
            pnl = condor_pnl(
                cyc_obj,
                S_close=spy_roll,
                T_remaining=T_roll,
                r_close=r_roll,
                sigma_close=sigma_roll,
                tx_cost_per_share=TX_COST_CLOSE_PER_SHARE,
                hold_to_expiry=False,
            )
        except Exception as exc:
            log.warning("Cycle %s failed: %s", entry_dt.date(), exc)
            pnl = np.nan
            cyc_obj = None

        records.append(
            {
                "entry_date": entry_dt,
                "roll_date": roll_dt,
                "vrp": vrp_val,
                "entered": True,
                "pnl_per_share": pnl,
                "premium": cyc_obj.premium if cyc_obj else np.nan,
            }
        )

        if verbose:
            log.info(
                "%s  VRP=%.2f  pnl=%.4f  premium=%.4f",
                entry_dt.date(),
                vrp_val,
                pnl,
                cyc_obj.premium if cyc_obj else float("nan"),
            )

    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# Phase 1 pass criterion
# ---------------------------------------------------------------------------

def evaluate_pass_criterion(cycles_df: pd.DataFrame) -> dict:
    """Apply §9.1 three-test pass criterion. Returns result dict."""
    traded = cycles_df[cycles_df["entered"] & cycles_df["pnl_per_share"].notna()].copy()
    traded["year"] = pd.DatetimeIndex(traded["entry_date"]).year

    if len(traded) < 5:
        return {
            "passed": False,
            "reason": f"Too few traded cycles ({len(traded)}) to evaluate.",
            "n_cycles": len(traded),
        }

    vrp_arr = traded["vrp"].values
    pnl_arr = traded["pnl_per_share"].values

    # Test 1: overall Pearson correlation > 0
    if pnl_arr.std() == 0.0 or vrp_arr.std() == 0.0:
        corr = float("nan")
    else:
        corr = float(np.corrcoef(vrp_arr, pnl_arr)[0, 1])
    test1 = corr > 0.0

    # Test 2: positive-year count ≥ 7 of 11 IS years (2004-2014)
    yearly_sign = {}
    for yr, grp in traded.groupby("year"):
        yearly_sign[int(yr)] = float(grp["pnl_per_share"].mean())

    is_years = list(range(2004, 2015))  # 11 years
    positive_years = sum(1 for y in is_years if yearly_sign.get(y, 0.0) > 0)
    test2 = positive_years >= 7

    # Test 3: ≥ 5 of 9 years excluding 2008 and 2009
    ex_years = [y for y in is_years if y not in (2008, 2009)]
    pos_ex = sum(1 for y in ex_years if yearly_sign.get(y, 0.0) > 0)
    test3 = pos_ex >= 5

    passed = test1 and test2 and test3

    return {
        "passed": passed,
        "test1_correlation": corr,
        "test1_pass": test1,
        "test2_positive_years": positive_years,
        "test2_total_years": len(is_years),
        "test2_pass": test2,
        "test3_positive_ex_crisis": pos_ex,
        "test3_total_ex_crisis": len(ex_years),
        "test3_pass": test3,
        "yearly_mean_pnl": yearly_sign,
        "n_cycles_traded": len(traded),
        "n_cycles_total": len(cycles_df),
        "mean_pnl": float(pnl_arr.mean()),
        "std_pnl": float(pnl_arr.std()),
        "mean_vrp": float(vrp_arr.mean()),
    }


# ---------------------------------------------------------------------------
# Report writers
# ---------------------------------------------------------------------------

def write_results_json(result: dict, cycles_df: pd.DataFrame) -> None:
    payload = {
        "phase": "1",
        "substrate": "9",
        "trial": "T1",
        "short_delta": SHORT_DELTA,
        "long_delta": LONG_DELTA,
        "vrp_threshold": VRP_THRESHOLD,
        "is_window": [IS_START, IS_END],
        **result,
        "cycles": [
            {
                "entry_date": str(r["entry_date"].date()),
                "roll_date": str(r["roll_date"].date()),
                "vrp": float(r["vrp"]) if not np.isnan(r["vrp"]) else None,
                "entered": bool(r["entered"]),
                "pnl_per_share": float(r["pnl_per_share"]) if not np.isnan(r["pnl_per_share"]) else None,
            }
            for _, r in cycles_df.iterrows()
        ],
    }
    RESULTS_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    log.info("Wrote %s", RESULTS_JSON)


def write_verdict_md(result: dict) -> None:
    passed = result["passed"]
    verdict_str = "**PHASE 1 PASS — Phase 3 UNBLOCKED**" if passed else "**PHASE 1 FAIL — CLOSED FAILED at Phase 1**"

    lines = [
        "# Substrate #9 — Phase 1 Verdict (VRP Iron Condor T1)",
        "",
        f"_Generated by `research/phase1_run.py`_",
        f"_In-sample window: {IS_START} → {IS_END}_",
        f"_Trial: T1 — 16Δ/5Δ iron condor, VRP > 0, no VIX filter_",
        "",
        f"## Outcome: {verdict_str}",
        "",
        "## Pass Criterion Results (§9.1)",
        "",
        f"| Test | Required | Actual | Pass |",
        f"|------|----------|--------|------|",
        f"| T1: Correlation(VRP, P&L) > 0 | > 0 | {result['test1_correlation']:.4f} | {'✓' if result['test1_pass'] else '·'} |",
        f"| T2: Positive-sign years | ≥ 7 of 11 | {result['test2_positive_years']} of {result['test2_total_years']} | {'✓' if result['test2_pass'] else '·'} |",
        f"| T3: Positive-sign ex-2008/09 | ≥ 5 of 9 | {result['test3_positive_ex_crisis']} of {result['test3_total_ex_crisis']} | {'✓' if result['test3_pass'] else '·'} |",
        "",
        "## Cycle Statistics",
        "",
        f"- Total IS cycles: {result['n_cycles_total']}",
        f"- Cycles traded (VRP > 0): {result['n_cycles_traded']}",
        f"- Mean P&L per share: ${result['mean_pnl']:.4f}",
        f"- Std P&L per share:  ${result['std_pnl']:.4f}",
        f"- Mean VRP at entry:  {result['mean_vrp']:.2f} vol pts",
        "",
        "## Yearly Mean P&L per Share",
        "",
        "| Year | Mean P&L | Sign |",
        "|------|----------|------|",
    ]

    for yr in range(2004, 2015):
        pnl = result["yearly_mean_pnl"].get(yr)
        if pnl is not None:
            sign = "+" if pnl > 0 else "-"
            note = " ← crisis" if yr in (2008, 2009) else ""
            lines.append(f"| {yr} | ${pnl:.4f} | {sign}{note} |")
        else:
            lines.append(f"| {yr} | n/a | — |")

    lines += [
        "",
        "## What Happens Next",
        "",
    ]
    if passed:
        lines += [
            "T1 passes all three §9.1 criteria. All 6 pre-committed trials (T1-T6) proceed to Phase 3.",
            "Phase 3 builds the full monthly cycle backtest across OOS-A (2015-2019) and OOS-B (2020-present)",
            "and evaluates all six gates (DSR, bootstrap CI, sign agreement, cost survival, max drawdown, CF-Sharpe).",
            "",
            "**Phase 3 is now unblocked.**",
        ]
    else:
        lines += [
            "T1 fails one or more §9.1 criteria. Per §9.2, all 6 trials CLOSED FAILED at Phase 1.",
            "No further research runs are permitted on Substrate #9.",
            "",
            "**Substrate #9: CLOSED FAILED at Phase 1.**",
        ]

    VERDICT_MD.write_text("\n".join(lines), encoding="utf-8")
    log.info("Wrote %s", VERDICT_MD)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(verbose: bool = False) -> int:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s  %(name)s  %(message)s",
    )

    log.info("=== Substrate #9 Phase 1 ===")
    sha_guard()

    log.info("Loading VRP panel …")
    panel = build_vrp_panel()
    log.info(
        "Panel: %d rows  %s → %s",
        len(panel),
        panel.index[0].date(),
        panel.index[-1].date(),
    )

    log.info("Running IS cycles (T1) …")
    cycles_df = run_is_cycles(panel, verbose=verbose)
    log.info(
        "Cycles: %d total, %d entered",
        len(cycles_df),
        cycles_df["entered"].sum(),
    )

    result = evaluate_pass_criterion(cycles_df)

    status = "PASS" if result["passed"] else "FAIL"
    log.info(
        "Phase 1 T1: %s  corr=%.4f  pos_yrs=%d/11  pos_ex_crisis=%d/9",
        status,
        result["test1_correlation"],
        result["test2_positive_years"],
        result["test3_positive_ex_crisis"],
    )

    write_results_json(result, cycles_df)
    write_verdict_md(result)

    return 0 if result["passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Substrate #9 Phase 1 orchestrator")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    try:
        sys.exit(main(verbose=args.verbose))
    except PhaseLockError as exc:
        sys.exit(str(exc))
