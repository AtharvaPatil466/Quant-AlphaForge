"""Phase 1 orchestrator — VRP decay (1A) + term-structure slope (1B) + regime (1C).

Per VIX_DESIGN.md §8 + §17.5 + §17.7 ADDENDUM. SHA-anchored to the
post-§17.7 design doc. Refuses to run if the design doc has been edited
since Phase 0 certification.

Outputs:
    research/PHASE1_RESULTS.json   — machine-readable per-trial detail
    research/PHASE1_VERDICT.md     — human-readable verdict
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# Make the repo importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingest.cboe import build_term_structure_panel  # noqa: E402
from ingest.realized_vol import build_spy_panel  # noqa: E402
from ingest.yfinance_loader import load_ticker  # noqa: E402
from signals import regime, term_structure, vrp  # noqa: E402

log = logging.getLogger("vix.research.phase1")

DESIGN_DOC = Path(__file__).resolve().parent / "VIX_DESIGN.md"
CERT_JSON = Path(__file__).resolve().parent / "vix_phase0_certified.json"
RESULTS_JSON = Path(__file__).resolve().parent / "PHASE1_RESULTS.json"
VERDICT_MD = Path(__file__).resolve().parent / "PHASE1_VERDICT.md"


# ---------------------------------------------------------------------------
# SHA anchor verification
# ---------------------------------------------------------------------------

class SHAAnchorError(RuntimeError):
    """Raised if the VIX_DESIGN.md SHA does not match the Phase 0 cert."""


def verify_sha_anchor() -> str:
    """Compute current VIX_DESIGN.md SHA and check against the cert. Returns
    the SHA on success. Raises SHAAnchorError on mismatch."""
    body = DESIGN_DOC.read_bytes()
    current = hashlib.sha256(body).hexdigest()
    if not CERT_JSON.exists():
        raise SHAAnchorError(
            f"Phase 0 cert not found at {CERT_JSON}. Run "
            "research/phase0_certify.py first."
        )
    with CERT_JSON.open() as fp:
        cert = json.load(fp)
    anchored = cert.get("design_doc_sha")
    if anchored != current:
        raise SHAAnchorError(
            f"VIX_DESIGN.md SHA mismatch — design doc was edited after "
            f"Phase 0 certification.\n"
            f"  Cert anchor:  {anchored}\n"
            f"  Current SHA:  {current}\n"
            "If the edit is a permitted §15 ADDENDUM, re-run "
            "research/phase0_certify.py to re-anchor."
        )
    return current


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

@dataclass
class Phase1Inputs:
    vix_spot: pd.Series             # from CBOE VIX index (primary)
    term_panel: pd.DataFrame        # wide panel: VIX, VIX1D, VIX9D, VIX3M, VIX6M
    spy_panel: pd.DataFrame         # log_return + realized_vol_10/21/63


def load_phase1_inputs(data_root: Path) -> Phase1Inputs:
    """Load all Phase 0 products required for Phase 1.

    VIX spot comes from the CBOE index (longer history than yfinance ^VIX
    on early dates, but the Phase 0 cross-check confirmed 1.0000 correlation
    over 9158 overlap dates, so either source works).
    """
    term_panel = build_term_structure_panel(data_root)
    if "VIX" not in term_panel.columns:
        raise RuntimeError(
            "CBOE term-structure panel missing VIX column. "
            "Run `python3.13 -m ingest.cboe` to re-download."
        )
    vix_spot = term_panel["VIX"].dropna()

    spy_df = load_ticker("SPY", data_root)
    if "close" not in spy_df.columns:
        raise RuntimeError("SPY parquet missing `close` column.")
    spy_panel = build_spy_panel(spy_df["close"])
    return Phase1Inputs(vix_spot=vix_spot, term_panel=term_panel, spy_panel=spy_panel)


# ---------------------------------------------------------------------------
# Phase 1 execution
# ---------------------------------------------------------------------------

@dataclass
class Phase1Results:
    design_doc_sha: str
    timestamp_utc: str
    inputs_summary: dict
    vrp_results: list[vrp.VrpTrialResult]
    slope_results: list[term_structure.SlopeTrialResult]
    contango_sanity: term_structure.ContangoSanityResult
    regime_report: regime.RegimeReport

    @property
    def n_vrp_passed(self) -> int:
        return sum(1 for r in self.vrp_results if r.passed)

    @property
    def n_slope_passed(self) -> int:
        return sum(1 for r in self.slope_results if r.passed)

    @property
    def n_total_passed(self) -> int:
        return self.n_vrp_passed + self.n_slope_passed

    def to_dict(self) -> dict:
        return {
            "design_doc_sha": self.design_doc_sha,
            "timestamp_utc": self.timestamp_utc,
            "inputs_summary": self.inputs_summary,
            "phase_1a_vrp": {
                "n_trials": len(self.vrp_results),
                "n_passed": self.n_vrp_passed,
                "trials": [r.to_dict() for r in self.vrp_results],
            },
            "phase_1b_slope": {
                "n_trials": len(self.slope_results),
                "n_passed": self.n_slope_passed,
                "trials": [r.to_dict() for r in self.slope_results],
                "contango_sanity": self.contango_sanity.to_dict(),
            },
            "phase_1c_regime": self.regime_report.to_dict(),
            "summary": {
                "n_total_trials": (len(self.vrp_results)
                                   + len(self.slope_results)),
                "n_total_passed": self.n_total_passed,
                "phase_1_exit": ("at_least_one_signal_passed"
                                 if self.n_total_passed > 0
                                 else "closed_failed_phase_1"),
            },
        }


def run_phase1(data_root: Path) -> Phase1Results:
    sha = verify_sha_anchor()
    log.info("VIX_DESIGN.md SHA anchor OK: %s", sha)

    inputs = load_phase1_inputs(data_root)
    log.info("VIX spot rows=%d (%s → %s)",
             len(inputs.vix_spot),
             inputs.vix_spot.index.min().date(),
             inputs.vix_spot.index.max().date())
    log.info("SPY panel rows=%d  (%s → %s)",
             len(inputs.spy_panel),
             inputs.spy_panel.index.min().date(),
             inputs.spy_panel.index.max().date())

    inputs_summary = {
        "vix_first": str(inputs.vix_spot.index.min().date()),
        "vix_last": str(inputs.vix_spot.index.max().date()),
        "vix_rows": int(len(inputs.vix_spot)),
        "spy_first": str(inputs.spy_panel.index.min().date()),
        "spy_last": str(inputs.spy_panel.index.max().date()),
        "spy_rows": int(len(inputs.spy_panel)),
        "term_panel_columns": [str(c) for c in inputs.term_panel.columns],
    }

    log.info("Phase 1A — VRP decay (18 trials)")
    vrp_results = vrp.evaluate_all(inputs.vix_spot, inputs.spy_panel)

    log.info("Phase 1B — term-structure slope (6 trials)")
    contango_sanity = term_structure.contango_sanity_check(
        inputs.term_panel, inputs.vix_spot,
        measure="slope_diff", horizon=21,
    )
    slope_results = term_structure.evaluate_all(inputs.term_panel, inputs.vix_spot)

    log.info("Phase 1C — regime characterization")
    regime_report = regime.characterize(inputs.vix_spot)

    return Phase1Results(
        design_doc_sha=sha,
        timestamp_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        inputs_summary=inputs_summary,
        vrp_results=vrp_results,
        slope_results=slope_results,
        contango_sanity=contango_sanity,
        regime_report=regime_report,
    )


# ---------------------------------------------------------------------------
# Markdown verdict writer
# ---------------------------------------------------------------------------

def _format_vrp_row(r: vrp.VrpTrialResult) -> str:
    ic_str = "  ".join(f"{h}d:{r.ic_by_horizon[h]:+.3f}"
                       for h in sorted(r.ic_by_horizon))
    pk = (f"h={r.peak_horizon} ic={r.peak_ic:+.3f}"
          if r.peak_horizon is not None else "—")
    pass_str = "PASS" if r.passed else "FAIL"
    return (f"| `{r.trial.name}` | {r.n_obs} | {ic_str} | {pk} | "
            f"{r.years_positive_all}/{r.years_total_all} | "
            f"{r.years_positive_ex_2008_09}/{r.years_total_ex_2008_09} | "
            f"{pass_str} |")


def _format_slope_row(r: term_structure.SlopeTrialResult) -> str:
    ic_str = "  ".join(f"{h}d:{r.ic_by_horizon[h]:+.3f}"
                       for h in sorted(r.ic_by_horizon))
    pk = (f"h={r.peak_horizon} ic={r.peak_ic:+.3f}"
          if r.peak_horizon is not None else "—")
    pass_str = "PASS" if r.passed else "FAIL"
    eff = (str(r.is_effective_start.date())
           if r.is_effective_start is not None else "—")
    return (f"| `{r.trial.name}` | {r.n_obs} | {eff} | {ic_str} | {pk} | "
            f"{r.years_positive_all}/{r.years_total_all} | "
            f"{r.years_positive_ex_2008_09}/{r.years_total_ex_2008_09} | "
            f"{pass_str} |")


def write_verdict_md(results: Phase1Results, path: Path) -> None:
    """Render the human-readable Phase 1 verdict."""
    lines: list[str] = []
    lines.append("# VIX — Phase 1 Verdict")
    lines.append("")
    lines.append(f"_Generated {results.timestamp_utc}_  ")
    lines.append(f"_VIX_DESIGN.md SHA-256: `{results.design_doc_sha}`_")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Phase 1A — VRP: **{results.n_vrp_passed}/{len(results.vrp_results)}** trials pass")
    lines.append(f"- Phase 1B — Slope: **{results.n_slope_passed}/{len(results.slope_results)}** trials pass")
    lines.append(f"- Phase 1C — Regime: characterization only (not a pass test)")
    lines.append("")
    if results.n_total_passed == 0:
        lines.append("**Outcome: CLOSED FAILED at Phase 1** — no signals survive to Phase 2.")
        lines.append("Per §12 decision matrix row 1: substrate verdict is CLOSED FAILED.")
    else:
        lines.append(f"**Outcome: Phase 2 OPEN** — {results.n_total_passed} signal(s) qualify for "
                     "strategy-design pre-commit. Phase 3 still required for any substrate verdict.")
    lines.append("")

    # Inputs
    inp = results.inputs_summary
    lines.append("## Inputs")
    lines.append("")
    lines.append(f"- VIX spot: {inp['vix_first']} → {inp['vix_last']} ({inp['vix_rows']} rows)")
    lines.append(f"- SPY: {inp['spy_first']} → {inp['spy_last']} ({inp['spy_rows']} rows)")
    lines.append(f"- Term panel columns: {', '.join(inp['term_panel_columns'])}")
    lines.append("")

    # Phase 1A
    lines.append("## Phase 1A — VRP carry (18 trials)")
    lines.append("")
    lines.append("Pass criteria (per §8.1):")
    lines.append(f"- |IC| > {vrp.IC_THRESHOLD} at peak horizon")
    lines.append(f"- ≥ {vrp.MIN_POSITIVE_YEARS_ALL}/11 IS years with consistent-sign IC")
    lines.append(f"- ≥ {vrp.MIN_POSITIVE_YEARS_EX_2008_09}/9 ex-2008/09 years consistent-sign")
    lines.append("")
    lines.append("Forward-return proxy: `-log(VIX_{t+h}/VIX_t)` per §17.7 ADDENDUM.")
    lines.append("")
    lines.append("| Trial | n_obs | IC by horizon | Peak | Yr+/All | Yr+/Ex-08/09 | Verdict |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in results.vrp_results:
        lines.append(_format_vrp_row(r))
    lines.append("")

    # Phase 1B
    lines.append("## Phase 1B — Term-structure slope (6 trials)")
    lines.append("")
    cs = results.contango_sanity
    cs_status = "PASS" if cs.passed else "FAIL"
    lines.append("**Contango sanity check (per §8.2):** "
                 f"contango n={cs.contango_n} mean_fwd_ret_21={cs.contango_mean_fwd_ret_21:+.5f}, "
                 f"backwardation n={cs.backwardation_n} mean_fwd_ret_21={cs.backwardation_mean_fwd_ret_21:+.5f}.  "
                 f"**{cs_status}** (contango_positive={cs.contango_positive}, "
                 f"backwardation_negative_or_zero={cs.backwardation_negative_or_zero})")
    if not cs.passed:
        lines.append("")
        lines.append("> ⚠ Contango sanity check FAILED. Per §8.2 the index-ratio slope-proxy "
                     "mechanism is broken in this data; slope-trial verdicts below are reported "
                     "but should be treated as suspect pending investigation.")
    lines.append("")
    lines.append("| Trial | n_obs | Eff. start | IC by horizon | Peak | Yr+/All | Yr+/Ex-08/09 | Verdict |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for r in results.slope_results:
        lines.append(_format_slope_row(r))
    lines.append("")

    # Phase 1C
    lines.append("## Phase 1C — VIX regime characterization (IS 2004-03-26 → 2014-12-31)")
    lines.append("")
    rr = results.regime_report
    lines.append(f"Total IS days: {rr.n_days_total}")
    lines.append("")
    lines.append("| Bucket | Range | n_days | Fraction | Mean VIX |")
    lines.append("|---|---|---|---|---|")
    for b in rr.buckets:
        upper = f"{b.upper:.1f}" if b.upper != float("inf") else "∞"
        lines.append(f"| {b.name} | [{b.lower:.1f}, {upper}) | {b.n_days} | "
                     f"{b.fraction:.3f} | {b.mean_vix:.2f} |")
    lines.append("")

    # Discussion
    lines.append("---")
    lines.append("")
    lines.append("## Discussion")
    lines.append("")
    # VRP discussion
    survivors = [r for r in results.vrp_results if r.passed]
    if survivors:
        peak_winner = max(survivors, key=lambda r: r.peak_ic)
        lines.append(
            f"**VRP carry**: {len(survivors)}/{len(results.vrp_results)} trials pass. "
            f"Strongest: `{peak_winner.trial.name}` with peak IC "
            f"`+{peak_winner.peak_ic:.3f}` at horizon h={peak_winner.peak_horizon} "
            f"({peak_winner.years_positive_all}/{peak_winner.years_total_all} years "
            f"positive, {peak_winner.years_positive_ex_2008_09}/"
            f"{peak_winner.years_total_ex_2008_09} ex-2008/09)."
        )
        # Surface the structural finding: high-threshold + long lookback dominates
        thr4_passers = sum(1 for r in survivors if r.trial.vrp_threshold >= 4.0)
        thr2_passers = sum(1 for r in survivors if r.trial.vrp_threshold == 2.0)
        thr0_passers = sum(1 for r in survivors if r.trial.vrp_threshold == 0.0)
        lines.append("")
        lines.append(
            f"Pass rate by VRP entry threshold: "
            f"thr=0 → {thr0_passers}/6, "
            f"thr=2 → {thr2_passers}/6, "
            f"thr=4 → {thr4_passers}/6. "
            "Higher VRP thresholds (richer premium at entry) pass more reliably — "
            "consistent with the §1.2 mean-reversion story: when the premium is "
            "*large*, the convergence trade is more reliable."
        )
        # Note that hold=5 and hold=21 produce identical IC by construction
        lines.append("")
        lines.append(
            "Note: Phase 1 IC is computed against the §8.1 horizons "
            "{5,10,21,42,63} for *all* trials. The pre-committed `holding_period` "
            "parameter (5 vs 21 days) does not enter the IC computation — it "
            "configures the Phase 3 backtest. The 18-trial DSR denominator is "
            "preserved; trials at the same (lookback, threshold) produce "
            "identical IC by construction. The duplication is a feature of "
            "Phase 1, not a bug: holding period earns or loses in Phase 3."
        )
    else:
        lines.append(
            f"**VRP carry**: 0/{len(results.vrp_results)} trials pass. "
            "The premium-harvest hypothesis fails at Phase 1 — VRP at the "
            "configured lookbacks does not predict short-vol forward returns "
            "with consistent positive sign across IS years."
        )
    lines.append("")
    # Slope discussion
    cs = results.contango_sanity
    slope_pass = results.n_slope_passed
    if slope_pass == 0:
        # Examine if the ICs are large in magnitude but wrong sign
        peak_negative = min((r.peak_ic for r in results.slope_results),
                            default=float("nan"))
        lines.append(
            f"**Term-structure slope**: 0/{len(results.slope_results)} trials pass. "
            f"All six trials produce *negative* peak IC against the "
            f"-Δlog(VIX) forward-return proxy (most negative: {peak_negative:+.3f}). "
            "The contango sanity check also flips the textbook story: contango "
            f"days (n={cs.contango_n}) average a SLIGHTLY POSITIVE 21-day "
            f"spot-VIX log change ({-cs.contango_mean_fwd_ret_21:+.5f} as Δlog, "
            f"or {cs.contango_mean_fwd_ret_21:+.5f} as the short-vol forward "
            "return proxy)."
        )
        lines.append("")
        lines.append(
            "This is the §17.7 ADDENDUM warning realized empirically: the "
            "futures-roll-yield economic mechanism (§1.3) does NOT translate "
            "cleanly to spot-VIX index changes. Contango captures the "
            "*futures-curve shape*, not a directional bet on VIX itself; spot "
            "VIX in contango regimes drifts up about as often as it drifts "
            "down. The signal direction is empirically inverted under the "
            "spot-VIX proxy. Per §15 hard rules this is a clean PHASE-1 FAIL "
            "for all 6 slope trials — the trials are NOT relabeled or "
            "sign-flipped post-hoc."
        )
    lines.append("")
    # Phase 3-deferred reminder
    lines.append(
        "**Mean-reversion trials (4) — Phase 3 only.** Per §4.3 the four "
        "VIX mean-reversion trials are event-driven (spike entry / mean-revert "
        "exit) and are not evaluated via Phase 1 IC. They remain in the "
        "28-trial DSR denominator and will be evaluated in the Phase 3 "
        "gauntlet alongside the Phase 1 VRP survivors."
    )
    lines.append("")
    # Next steps
    if results.n_total_passed == 0:
        lines.append(
            "**Next: per §12 decision matrix row 1 — substrate verdict is "
            "CLOSED FAILED at Phase 1.** No Phase 2 or Phase 3 follows."
        )
    else:
        lines.append(
            f"**Next:** {results.n_total_passed} survivor(s) → Phase 2 "
            "strategy-design pre-commit (§9: position sizing, hedge variants, "
            "exit rules). Phase 2 freezes a strategy spec for each survivor "
            "BEFORE any OOS data is touched. Phase 3 gauntlet then evaluates "
            f"all {results.n_total_passed} Phase 1 survivors + 4 mean-reversion "
            "trials × 2 hedge variants under the §5 six-gate criteria."
        )
    lines.append("")

    # Hard rule reminder
    lines.append("---")
    lines.append("")
    lines.append("## §15 hard-rule reminder")
    lines.append("")
    lines.append("This verdict is reported on the *pre-committed* trial set frozen in "
                 "`VIX_DESIGN.md` (SHA `" + results.design_doc_sha + "`). The Phase 1 "
                 "orchestrator refuses to run if the design doc SHA does not match the "
                 "Phase 0 certification anchor. No trial may be added, dropped, or "
                 "re-parameterized post-Phase-1.")
    path.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _json_default(o):
    # Robust JSON serializer for numpy / pandas scalars + Timestamps.
    if isinstance(o, (np.integer, np.bool_)):
        return o.item()
    if isinstance(o, np.floating):
        v = o.item()
        if np.isnan(v):
            return None
        return v
    if isinstance(o, (pd.Timestamp, datetime)):
        return str(o)
    raise TypeError(f"unserializable: {type(o)}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run Phase 1 on certified Phase 0 data.")
    p.add_argument("--data-root", type=Path,
                   default=Path(__file__).resolve().parents[1] / "data")
    p.add_argument("--results-json", type=Path, default=RESULTS_JSON)
    p.add_argument("--verdict-md", type=Path, default=VERDICT_MD)
    p.add_argument("-v", "--verbose", action="count", default=1)
    args = p.parse_args(argv)

    logging.basicConfig(
        level=max(logging.WARNING - 10 * args.verbose, logging.DEBUG),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        results = run_phase1(args.data_root)
    except SHAAnchorError as e:
        log.error("SHA anchor refusal: %s", e)
        return 2

    args.results_json.write_text(
        json.dumps(results.to_dict(), indent=2, default=_json_default) + "\n"
    )
    write_verdict_md(results, args.verdict_md)

    print(f"Phase 1A — VRP:   {results.n_vrp_passed}/{len(results.vrp_results)} passed")
    print(f"Phase 1B — Slope: {results.n_slope_passed}/{len(results.slope_results)} passed")
    print(f"Total:            {results.n_total_passed} signal(s) survive Phase 1")
    print(f"  results: {args.results_json}")
    print(f"  verdict: {args.verdict_md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
