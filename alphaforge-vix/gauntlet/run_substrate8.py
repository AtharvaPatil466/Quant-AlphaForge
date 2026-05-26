"""Substrate #8 master runner — same gauntlet as #7 but with VIX-baseline sizing.

Per `research/SUBSTRATE8_DESIGN.md` (SHA-anchored to its own pin in
`research/substrate8_spec.json`) which inherits everything from
`research/VIX_DESIGN.md` (SHA `54e53be9...` post-§17.8) EXCEPT §9.1 sizing.

Anchors verified at start:
  • VIX_DESIGN.md SHA matches Phase 0 cert (substrate-#7 contract).
  • SUBSTRATE8_DESIGN.md SHA matches substrate8_spec.json.

Output:
  research/SUBSTRATE8_RESULTS.json   — machine, per (trial × variant) × gate
  research/SUBSTRATE8_VERDICT.md     — human verdict with Discussion section
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gauntlet import backtest as bt  # noqa: E402
from gauntlet import costs as costs_mod  # noqa: E402
from gauntlet import strategy as strat  # noqa: E402
from gauntlet import run_gauntlet as gnt  # noqa: E402

log = logging.getLogger("vix.substrate8")

ROOT = Path(__file__).resolve().parents[1]
DESIGN_DOC = ROOT / "research" / "VIX_DESIGN.md"
SUBSTRATE8_DESIGN = ROOT / "research" / "SUBSTRATE8_DESIGN.md"
SUBSTRATE8_PIN = ROOT / "research" / "substrate8_spec.json"
CERT_JSON = ROOT / "research" / "vix_phase0_certified.json"

RESULTS_JSON = ROOT / "research" / "SUBSTRATE8_RESULTS.json"
VERDICT_MD = ROOT / "research" / "SUBSTRATE8_VERDICT.md"


class AnchorError(RuntimeError):
    pass


def verify_substrate8_anchors() -> tuple[str, str]:
    """Verify (1) VIX_DESIGN.md SHA matches Phase 0 cert and (2)
    SUBSTRATE8_DESIGN.md SHA matches substrate8_spec.json. Returns both SHAs."""
    design_sha = hashlib.sha256(DESIGN_DOC.read_bytes()).hexdigest()
    with CERT_JSON.open() as f:
        cert = json.load(f)
    if cert.get("design_doc_sha") != design_sha:
        raise AnchorError(
            f"VIX_DESIGN.md SHA mismatch.\n"
            f"  Cert anchor:  {cert.get('design_doc_sha')}\n"
            f"  Current SHA:  {design_sha}"
        )
    s8_sha = hashlib.sha256(SUBSTRATE8_DESIGN.read_bytes()).hexdigest()
    with SUBSTRATE8_PIN.open() as f:
        pin = json.load(f)
    if pin.get("substrate8_design_sha") != s8_sha:
        raise AnchorError(
            f"SUBSTRATE8_DESIGN.md SHA mismatch.\n"
            f"  Pinned SHA:   {pin.get('substrate8_design_sha')}\n"
            f"  Current SHA:  {s8_sha}"
        )
    return design_sha, s8_sha


# ---------------------------------------------------------------------------
# Substrate-#8 evaluate_trial — overrides sizing function only
# ---------------------------------------------------------------------------

def _evaluate_trial_s8(trial, market, factor_panel, boot_seed):
    """Adapter that monkey-patches the sizing into both gauntlet backtests
    via the new `sizing_fn` Backtest parameter (NOT a global override)."""
    # We re-implement evaluate_trial in a slightly different shape: replace
    # the gauntlet's hard-coded Backtest construction with one that passes
    # `sizing_fn=size_position_baseline_vix`. The simplest implementation
    # is to temporarily monkey-patch bt.Backtest's __init__ for the call,
    # but cleaner is to call run_gauntlet.evaluate_trial after temporarily
    # subclassing — but that re-implements the gates inside evaluate_trial.
    # We instead call evaluate_trial with a small Backtest-wrapping shim.
    original_init = bt.Backtest.__init__

    def patched_init(self, *args, **kwargs):
        kwargs.setdefault("sizing_fn", strat.size_position_baseline_vix)
        original_init(self, *args, **kwargs)

    bt.Backtest.__init__ = patched_init
    try:
        return gnt.evaluate_trial(trial, market, factor_panel, boot_seed)
    finally:
        bt.Backtest.__init__ = original_init


def run_substrate8(data_root: Path, boot_seed: int = 42) -> gnt.GauntletResults:
    """Run the substrate-#8 gauntlet — same as substrate #7 with the new
    VIX-baseline-anchored §9.1 sizing rule wired in. Returns a
    `GauntletResults` with substrate-8 anchors."""
    design_sha, s8_sha = verify_substrate8_anchors()
    log.info("Anchors OK. design=%s substrate8_design=%s",
             design_sha[:8], s8_sha[:8])

    frame = gnt.load_market_frame(data_root)
    market = bt.MarketData(df=frame)
    log.info("Market frame: %d rows %s → %s",
             len(frame), frame.index.min().date(), frame.index.max().date())

    factor_panel = gnt.resid_mod.build_factor_panel(
        spy_returns=frame["spy_log_return"],
        delta_vix=frame["delta_vix_log"],
    )

    trials = gnt.enumerate_trial_variants()
    log.info("Evaluating %d trial × variant combinations (substrate #8 sizing)",
             len(trials))
    results: list[gnt.GateResults] = []
    for i, trial in enumerate(trials):
        log.info("[%d/%d] %s", i + 1, len(trials), trial.name)
        try:
            r = _evaluate_trial_s8(trial, market, factor_panel,
                                    boot_seed=boot_seed + i)
        except Exception as e:
            log.warning("trial %s errored: %s", trial.name, e)
            r = gnt.GateResults(
                trial_name=trial.name, variant=trial.variant.value,
                direction=trial.direction.value,
                n_obs_oos_a=0, n_obs_oos_b=0,
                sharpe_oos_a=float("nan"), sharpe_oos_b=float("nan"),
                dsr_oos_a=0.0, dsr_oos_b=0.0,
                gate1_passes_a=False, gate1_passes_b=False, gate1_passes=False,
                boot_ci_oos_a=(float("nan"), float("nan")),
                boot_ci_oos_b=(float("nan"), float("nan")),
                gate2_passes_a=False, gate2_passes_b=False, gate2_passes=False,
                gate3_passes=False,
                sharpe_oos_a_gate4=float("nan"), sharpe_oos_b_gate4=float("nan"),
                gate4_passes_a=False, gate4_passes_b=False, gate4_passes=False,
                gate5_result={"error": str(e)}, gate5_passes=False,
                gate6_result={"error": str(e)}, gate6_passes=False,
                resid_result={"error": str(e)}, resid_passes=False,
                all_six_gates_pass=False, deploy_ready=False,
            )
        results.append(r)

    return gnt.GauntletResults(
        design_doc_sha=design_sha,
        phase2_spec_sha=s8_sha,  # we overload this slot for substrate-8 SHA
        timestamp_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        market_frame_summary={
            "n_rows": int(len(frame)),
            "first_date": str(frame.index.min().date()),
            "last_date": str(frame.index.max().date()),
        },
        per_trial=results,
    )


# ---------------------------------------------------------------------------
# Verdict writer (substrate-#8 wording)
# ---------------------------------------------------------------------------

def write_verdict_s8(results: gnt.GauntletResults, path: Path) -> None:
    lines: list[str] = []
    lines.append("# VIX — Substrate #8 Verdict (VIX-baseline-anchored sizing)")
    lines.append("")
    lines.append(f"_Generated {results.timestamp_utc}_  ")
    lines.append(f"_VIX_DESIGN.md SHA-256 (parent): `{results.design_doc_sha}`_  ")
    lines.append(f"_SUBSTRATE8_DESIGN.md SHA-256: `{results.phase2_spec_sha}`_  ")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    n_total = len(results.per_trial)
    lines.append(f"- Trial × variant combos evaluated: **{n_total}**")
    lines.append(f"- Combos passing all 6 gates: **{results.n_all_six_gates}**")
    lines.append(f"- Combos passing all 6 gates + §7 residualization (DEPLOY-READY): "
                 f"**{results.n_deploy_ready}**")
    lines.append("")
    if results.n_deploy_ready == 0:
        if results.n_all_six_gates == 0:
            lines.append("**Outcome: SUBSTRATE #8 CLOSED FAILED.** Per §12 decision "
                         "matrix row 2 — no trial × variant pair clears all six gates "
                         "at the VIX-baseline-anchored sizing.")
        else:
            lines.append(f"**Outcome: CONDITIONAL.** {results.n_all_six_gates} "
                         "combo(s) clear Gates 1-6 but fail §7 four-factor "
                         "residualization. Per §12 decision matrix row 3 — "
                         "documented but not deployable.")
    else:
        lines.append(f"**Outcome: DEPLOY-READY.** {results.n_deploy_ready} "
                     "trial × variant combo(s) cleared all six gates AND the §7 "
                     "residualization at the substrate-#8 sizing. Per §12 row 4 — "
                     "Phase 4 (live paper trading) is the next step, pending "
                     "founder approval. **This would be the project's first "
                     "DEPLOY-READY verdict across eight substrates.**")
    lines.append("")
    lines.append(f"Market frame: {results.market_frame_summary['n_rows']} rows "
                 f"{results.market_frame_summary['first_date']} → "
                 f"{results.market_frame_summary['last_date']}")
    lines.append("")
    lines.append("## Sizing rule — what changed vs substrate #7")
    lines.append("")
    lines.append("Substrate #7 §9.1: `max_notional = 0.10 × pv / VIX_t`  "
                 "→ ~0.5% NAV at VIX=20.  ")
    lines.append("Substrate #8 §9.1: `max_notional = 0.10 × pv × (20 / VIX_t)` "
                 "→ ~10% NAV at VIX=20. Exactly 20× substrate #7 at every VIX level. "
                 "Auto-deleverage shape preserved.")
    lines.append("")
    lines.append("## Per-trial × variant gate breakdown")
    lines.append("")
    lines.append("Legend: G1 = DSR > 0.95, G2 = bootstrap CI > 0, G3 = sign agreement, "
                 "G4 = cost-double survival, G5 = max-DD per stress period, "
                 "G6 = CF-Sharpe > 0.5, R = §7 residualization alpha t > 1.96.")
    lines.append("")
    lines.append("| Trial × variant | OOS-A Sharpe | OOS-B Sharpe | DSR-A | DSR-B | G1 | G2 | G3 | G4 | G5 | G6 | R | DEPLOY |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in results.per_trial:
        def yn(b: bool) -> str: return "✓" if b else "·"
        lines.append(
            f"| `{r.trial_name}` | {r.sharpe_oos_a:+.2f} | {r.sharpe_oos_b:+.2f} | "
            f"{r.dsr_oos_a:.3f} | {r.dsr_oos_b:.3f} | "
            f"{yn(r.gate1_passes)} | {yn(r.gate2_passes)} | {yn(r.gate3_passes)} | "
            f"{yn(r.gate4_passes)} | {yn(r.gate5_passes)} | {yn(r.gate6_passes)} | "
            f"{yn(r.resid_passes)} | {yn(r.deploy_ready)} |"
        )
    lines.append("")
    lines.append("## §7 residualization note")
    lines.append("")
    lines.append("Substrate #8 inherits the §7 falloff from substrate #7 — only "
                 "SPY + ΔVIX are wired into the OLS (2/4 factors). ST-Reversal and "
                 "Carry factors are not staged. Per-trial `provisional=True` flag "
                 "in the machine output.")
    lines.append("")
    lines.append("## §15 hard-rule reminder")
    lines.append("")
    lines.append("This verdict is reported on the *pre-committed* trial set frozen "
                 f"in `VIX_DESIGN.md` (SHA `{results.design_doc_sha}`) and the "
                 f"*substrate-#8* sizing rule frozen in `SUBSTRATE8_DESIGN.md` "
                 f"(SHA `{results.phase2_spec_sha}`). The substrate-#8 runner refuses "
                 "to execute if either SHA mismatches its anchor.")
    path.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run substrate-#8 gauntlet.")
    p.add_argument("--data-root", type=Path, default=ROOT / "data")
    p.add_argument("--results-json", type=Path, default=RESULTS_JSON)
    p.add_argument("--verdict-md", type=Path, default=VERDICT_MD)
    p.add_argument("--boot-seed", type=int, default=42)
    p.add_argument("-v", "--verbose", action="count", default=1)
    args = p.parse_args(argv)

    logging.basicConfig(
        level=max(logging.WARNING - 10 * args.verbose, logging.DEBUG),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        results = run_substrate8(args.data_root, boot_seed=args.boot_seed)
    except AnchorError as e:
        log.error("Anchor refusal: %s", e)
        return 2

    args.results_json.write_text(
        json.dumps(results.to_dict(), indent=2, default=gnt._json_default) + "\n"
    )
    write_verdict_s8(results, args.verdict_md)
    print("Substrate #8 gauntlet complete:")
    print(f"  Combos evaluated:    {len(results.per_trial)}")
    print(f"  6-gate pass:         {results.n_all_six_gates}")
    print(f"  Deploy-ready:        {results.n_deploy_ready}")
    print(f"  Results: {args.results_json}")
    print(f"  Verdict: {args.verdict_md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
