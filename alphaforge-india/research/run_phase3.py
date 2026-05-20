"""Phase 3 orchestrator — runs the 5-gate gauntlet on Phase 1 survivors.

Per `research/INDIA_DESIGN.md` §10. For each survivor from Phase 1:

  1. Recompute the signal panel on OOS-A + OOS-B data.
  2. Form the long-short portfolio (equal-weighted within bucket).
  3. Compute daily portfolio returns net of base costs (§6 stack).
  4. Optionally residualize against four-factor model (§7) if factor data
     is supplied. Otherwise run gauntlet on raw returns with a noted
     limitation.
  5. Run all 5 gates via `gauntlet.gates.run_gauntlet`.

Verdict classification per §12 decision matrix:

  - **CLOSED FAILED**: 0 trials pass all 5 gates.
  - **CONDITIONAL**: ≥1 trial passes Gates 1-4 but fails Gate 5
    (regime stress). Survivor is documented but NOT deployable.
  - **DEPLOY-READY**: ≥1 trial passes all 5 gates. Proceeds to Phase 4.

Output:
  - `research/PHASE3_RESULTS.json` — full per-trial gauntlet metrics.
  - `research/GAUNTLET_VERDICT.md` — markdown verdict report.

Limitations carried into this session:
  - F&O expiry survivors are NOT processed in Phase 3 yet — they emit a
    SKIP gauntlet result. The event-driven return-series construction
    needs the per-event high-OI stock list (requires OI data).
  - If no factor matrix is supplied via `--factor-matrix`, the gauntlet
    runs on raw portfolio returns. §7 residualization is then a noted
    limitation in the verdict report.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# Path bootstrap — allow `python -m research.run_phase3` from sub-project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gauntlet import gates as G   # noqa: E402
from signals import delivery_pct as DP  # noqa: E402

log = logging.getLogger("india.run_phase3")


# ---------------------------------------------------------------------------
# Constants from INDIA_DESIGN.md
# ---------------------------------------------------------------------------

# Cover both OOS windows + embargo + warmup. Embargo is 21 trading days at
# each boundary per §3; we cushion with an extra month for signal warmup.
OOS_DATA_START = date(2014, 11, 1)   # ~ OOS-A_start - 60 calendar days
OOS_DATA_END = date(2026, 5, 18)     # present

# Base per-trial costs per §6 (single number for cost subtraction on
# rebalance days). Per-side = 13.7bp buy + 22.2bp sell = 35.9bp round-trip.
# Impact = 10bp per unit turnover. For full long-short swap turnover ≈ 2.
BASE_RT_BPS = 35.9
BASE_IMPACT_BPS_PER_TURNOVER = 10.0
ASSUMED_REBALANCE_TURNOVER = 2.0       # full long+short rotation

# Pre-committed total trial count for DSR deflation
N_TRIALS = G.N_TRIALS  # 22


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class TrialVerdict:
    trial_name: str
    family: str               # "delivery_pct" or "fo_expiry"
    gauntlet_passed: bool
    gates_1_to_4_passed: bool
    gate5_passed: bool
    per_gate: list[dict[str, Any]]
    skipped: bool = False
    skip_reason: str = ""


@dataclass
class Phase3Verdict:
    verdict: str               # "DEPLOY-READY", "CONDITIONAL", "CLOSED FAILED"
    survivors: list[str]        # trials passing all 5 gates
    conditional_survivors: list[str]  # passed 1-4 but failed gate 5
    failures: list[str]
    trial_verdicts: list[TrialVerdict]
    total_trials_evaluated: int
    n_trials_for_dsr: int       # always 22 — never less, per §4
    factor_residualization_applied: bool
    generated_at: str
    design_doc_sha: str = ""


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_phase1_survivors(phase1_results: Path) -> tuple[list[str], list[str]]:
    """Returns (delivery_pct_trial_names, fo_expiry_trial_names)."""
    if not phase1_results.exists():
        raise FileNotFoundError(
            f"Phase 1 results not found at {phase1_results}. Run "
            "`python -m research.run_phase1` first."
        )
    data = json.loads(phase1_results.read_text())
    return (
        list(data.get("survivors_deliv_pct", [])),
        list(data.get("survivors_foe", [])),
    )


def load_oos_panel(
    processed_dir: Path,
    start: date = OOS_DATA_START,
    end: date = OOS_DATA_END,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load processed bhavcopy parquet, filter to OOS range, pivot to wide
    panels. Returns (close_df, deliv_pct_df)."""
    # Accept either {YYYY}.parquet (canonical, written by ingest.build_parquet)
    # or legacy bhavcopy*.parquet test fixtures.
    files = sorted(
        list(processed_dir.rglob("[0-9][0-9][0-9][0-9].parquet"))
        + list(processed_dir.rglob("bhavcopy*.parquet"))
    )
    if not files:
        raise FileNotFoundError(
            f"No bhavcopy parquets under {processed_dir}. Phase 3 needs the "
            "full processed substrate."
        )
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    df = df[(df["date"] >= pd.Timestamp(start))
            & (df["date"] <= pd.Timestamp(end))]
    if df.empty:
        raise ValueError(f"No rows in OOS range [{start}, {end}]")
    # Defensive dedup: era-overlap dates can appear twice.
    df = df.drop_duplicates(subset=["date", "symbol"], keep="first")

    close_df = df.pivot(index="date", columns="symbol", values="close").sort_index()
    deliv_pct_df = df.pivot(index="date", columns="symbol",
                            values="deliv_pct").sort_index()
    all_syms = close_df.columns.union(deliv_pct_df.columns)
    return (close_df.reindex(columns=all_syms),
            deliv_pct_df.reindex(columns=all_syms))


def parse_deliv_pct_trial_name(name: str) -> DP.DeliveryPctSignal | None:
    """Re-instantiate a DeliveryPctSignal from its trial_name string.

    Format: `deliv_pct_L{lookback}_Q{5|10}_H{holding_period}`.
    Returns None on malformed input — caller decides whether to skip.
    """
    parts = name.split("_")
    if len(parts) < 5 or parts[0] != "deliv" or parts[1] != "pct":
        return None
    try:
        lookback = int(parts[2][1:])           # 'L20' → 20
        q = int(parts[3][1:])                  # 'Q5' or 'Q10'
        holding = int(parts[4][1:])            # 'H5' → 5
        bucket = "quintile" if q == 5 else "decile"
        return DP.DeliveryPctSignal(lookback=lookback, bucket=bucket,
                                     holding_period=holding)
    except (ValueError, IndexError):
        return None


# ---------------------------------------------------------------------------
# Portfolio-returns construction (delivery_pct)
# ---------------------------------------------------------------------------

def compute_long_short_returns(
    close_df: pd.DataFrame,
    deliv_pct_df: pd.DataFrame,
    trial: DP.DeliveryPctSignal,
    rebalance_cost_bps: float = BASE_RT_BPS,
    rebalance_impact_bps: float = (
        BASE_IMPACT_BPS_PER_TURNOVER * ASSUMED_REBALANCE_TURNOVER
    ),
) -> pd.Series:
    """Daily long-short portfolio returns for a delivery_pct trial.

    Strategy:
      - At each rebalance date (every `holding_period` trading days),
        sort stocks by signal z-score, take EW long position in top
        bucket, EW short position in bottom bucket.
      - Hold the bucket assignment for `holding_period` days.
      - Daily portfolio return = mean(long-leg daily returns)
                                 − mean(short-leg daily returns), / 2.
        (The /2 normalizes so the dollar-neutral spread is reported on
        per-side scale, matching how gates.py treats net daily returns.)
      - On rebalance days, deduct `(rebalance_cost_bps +
        rebalance_impact_bps) / 10000` from the day's return.
    """
    if close_df.empty or deliv_pct_df.empty:
        return pd.Series([], dtype=float, name=trial.trial_name)

    signal_df = trial.compute_signal(close_df, deliv_pct_df)
    bucket_df = trial.assign_buckets(signal_df)

    # Hold positions: rebalance every `holding_period` days; in between, the
    # bucket assignment is forward-filled.
    rebal_idx = bucket_df.index[::trial.holding_period]
    held = bucket_df.reindex(rebal_idx).reindex(bucket_df.index).ffill()

    daily_ret = close_df.pct_change()
    # Align daily_ret with held positions; positions taken at close of day t
    # earn return on day t+1. Shift held by 1 day forward.
    held_lagged = held.shift(1)
    long_mask = held_lagged == 1.0
    short_mask = held_lagged == -1.0

    long_leg = daily_ret.where(long_mask).mean(axis=1).fillna(0.0)
    short_leg = daily_ret.where(short_mask).mean(axis=1).fillna(0.0)
    portfolio_ret = (long_leg - short_leg) / 2.0

    # Per-rebalance cost: deducted on the day the new position is put on
    # (which is the rebalance date).
    cost_bps = rebalance_cost_bps + rebalance_impact_bps
    cost_per_rebal = cost_bps / 10000.0
    portfolio_ret_net = portfolio_ret.copy()
    rebal_mask = portfolio_ret_net.index.isin(rebal_idx)
    portfolio_ret_net.loc[rebal_mask] -= cost_per_rebal

    portfolio_ret_net.name = trial.trial_name
    return portfolio_ret_net


# ---------------------------------------------------------------------------
# Per-trial gauntlet evaluation
# ---------------------------------------------------------------------------

def evaluate_trial_deliv_pct(
    trial_name: str,
    close_df: pd.DataFrame,
    deliv_pct_df: pd.DataFrame,
    factor_matrix: pd.DataFrame | None = None,
    n_trials: int = N_TRIALS,
) -> TrialVerdict:
    """Build portfolio returns + run the gauntlet for a delivery_pct trial."""
    trial = parse_deliv_pct_trial_name(trial_name)
    if trial is None:
        return TrialVerdict(
            trial_name=trial_name, family="delivery_pct",
            gauntlet_passed=False, gates_1_to_4_passed=False,
            gate5_passed=False, per_gate=[], skipped=True,
            skip_reason=f"could not parse trial name {trial_name!r}",
        )

    portfolio_ret = compute_long_short_returns(close_df, deliv_pct_df, trial)
    if portfolio_ret.empty:
        return TrialVerdict(
            trial_name=trial_name, family="delivery_pct",
            gauntlet_passed=False, gates_1_to_4_passed=False,
            gate5_passed=False, per_gate=[], skipped=True,
            skip_reason="empty portfolio return series",
        )

    # §7 residualization — applied if factor data is available.
    residual_ret = portfolio_ret
    if factor_matrix is not None and not factor_matrix.empty:
        residual_ret = _residualize_returns(portfolio_ret, factor_matrix)

    # Ensure DatetimeIndex for gates.py
    residual_ret.index = pd.to_datetime(residual_ret.index)

    result = G.run_gauntlet(
        trial_name=trial_name,
        daily_returns=residual_ret,
        n_trials=n_trials,
    )

    gate_results = [
        {"gate_name": g.gate_name, "passed": g.passed, "summary": g.summary,
         "metrics": g.metrics}
        for g in result.gate_results
    ]
    g14 = all(g.passed for g in result.gate_results[:4])
    g5 = result.gate_results[4].passed if len(result.gate_results) >= 5 else False
    return TrialVerdict(
        trial_name=trial_name, family="delivery_pct",
        gauntlet_passed=result.all_gates_passed,
        gates_1_to_4_passed=g14, gate5_passed=g5,
        per_gate=gate_results,
    )


def evaluate_trial_fo_expiry(trial_name: str) -> TrialVerdict:
    """F&O expiry Phase 3 not yet implemented — returns a documented SKIP."""
    return TrialVerdict(
        trial_name=trial_name, family="fo_expiry",
        gauntlet_passed=False, gates_1_to_4_passed=False,
        gate5_passed=False, per_gate=[], skipped=True,
        skip_reason=(
            "F&O Phase 3 daily-return construction requires per-event "
            "high-OI stock universe (needs OI data). Not implemented in "
            "this session — file follow-up."
        ),
    )


# ---------------------------------------------------------------------------
# Residualization (thin adapter — defers to gauntlet.residualization if
# available; otherwise no-op with warning)
# ---------------------------------------------------------------------------

def _residualize_returns(
    portfolio_ret: pd.Series,
    factor_matrix: pd.DataFrame,
) -> pd.Series:
    """Residualize `portfolio_ret` against `factor_matrix`. Returns the
    residual time series (raw minus factor-explained component)."""
    try:
        from gauntlet import residualization as RES
        result = RES.residualize(portfolio_ret, factor_matrix)
        # The user's API returns a result object — extract residuals.
        residuals = getattr(result, "residuals", None)
        if residuals is None:
            log.warning("residualize() returned no `residuals`; using raw.")
            return portfolio_ret
        return residuals
    except Exception as e:
        log.warning("residualize failed (%r); using raw portfolio returns.", e)
        return portfolio_ret


# ---------------------------------------------------------------------------
# Verdict classification (§12 decision matrix)
# ---------------------------------------------------------------------------

def classify_phase3(
    trial_verdicts: list[TrialVerdict],
) -> tuple[str, list[str], list[str], list[str]]:
    """Returns (verdict_label, survivors, conditional_survivors, failures)."""
    survivors = [t.trial_name for t in trial_verdicts
                 if not t.skipped and t.gauntlet_passed]
    conditional = [t.trial_name for t in trial_verdicts
                   if not t.skipped and t.gates_1_to_4_passed
                   and not t.gate5_passed]
    failures = [t.trial_name for t in trial_verdicts
                if not t.skipped and not t.gauntlet_passed
                and t.trial_name not in conditional]

    if survivors:
        label = "DEPLOY-READY"
    elif conditional:
        label = "CONDITIONAL"
    else:
        label = "CLOSED FAILED"
    return label, survivors, conditional, failures


# ---------------------------------------------------------------------------
# Verdict builder + markdown
# ---------------------------------------------------------------------------

def build_phase3_verdict(
    trial_verdicts: list[TrialVerdict],
    factor_residualization_applied: bool,
    design_doc_sha: str = "",
) -> Phase3Verdict:
    label, survivors, conditional, failures = classify_phase3(trial_verdicts)
    return Phase3Verdict(
        verdict=label,
        survivors=survivors,
        conditional_survivors=conditional,
        failures=failures,
        trial_verdicts=trial_verdicts,
        total_trials_evaluated=len(trial_verdicts),
        n_trials_for_dsr=N_TRIALS,
        factor_residualization_applied=factor_residualization_applied,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        design_doc_sha=design_doc_sha,
    )


def render_markdown_verdict(v: Phase3Verdict) -> str:
    lines: list[str] = []
    if v.verdict == "CLOSED FAILED":
        lines.append("# Gauntlet Verdict — CLOSED FAILED")
    elif v.verdict == "CONDITIONAL":
        lines.append("# Gauntlet Verdict — CONDITIONAL")
    else:
        lines.append("# Gauntlet Verdict — DEPLOY-READY")
    lines.append("")
    lines.append(f"_Generated {v.generated_at}_")
    if v.design_doc_sha:
        lines.append(f"_INDIA_DESIGN.md SHA-256: `{v.design_doc_sha}`_")
    lines.append("")
    lines.append(f"**Trials evaluated:** {v.total_trials_evaluated}")
    lines.append(f"**DSR deflation denominator:** {v.n_trials_for_dsr} "
                 f"(pre-committed; cancelled FII/DII still counted per §17 ADDENDUM)")
    lines.append(f"**Survivors (all 5 gates):** {len(v.survivors)}")
    lines.append(f"**Conditional (Gates 1-4 pass, Gate 5 fail):** "
                 f"{len(v.conditional_survivors)}")
    if not v.factor_residualization_applied:
        lines.append("")
        lines.append("> ⚠ **Residualization NOT applied** — no four-factor "
                     "matrix supplied. §7 hard rule (alpha-intercept t-stat > "
                     "1.96 after residualization) is therefore unenforced. "
                     "Treat survivors as provisional pending residualization run.")
    lines.append("")

    if v.verdict == "CLOSED FAILED":
        lines.append("## Substrate #6 (India) — CLOSED FAILED at Phase 3")
        lines.append("")
        lines.append("0 trials pass all 5 gates and 0 trials pass even the "
                     "first four. Substrate is closed per §12.")
        lines.append("")
    elif v.verdict == "CONDITIONAL":
        lines.append("## CONDITIONAL — survivor(s) without regime robustness")
        lines.append("")
        lines.append("≥1 trial passes Gates 1-4 but fails Gate 5 (regime "
                     "stress). Per §12, these are documented but NOT "
                     "deployable. Substrate is closed unless Phase 2 strategy "
                     "design respects the pre-commit and Gate 5 can be cleared.")
        lines.append("")
        for s in v.conditional_survivors:
            lines.append(f"- `{s}`")
        lines.append("")
    else:
        lines.append("## DEPLOY-READY — survivor(s) clearing all five gates")
        lines.append("")
        for s in v.survivors:
            lines.append(f"- `{s}`")
        lines.append("")
        lines.append("Per §12, advance to Phase 4 (live paper trading, "
                     "≥60-day window).")
        lines.append("")

    # Per-trial table
    lines.append("## Per-trial gauntlet outcomes")
    lines.append("")
    lines.append("| Trial | Family | G1 DSR | G2 CI | G3 Sign | G4 Cost | "
                 "G5 Regime | Verdict |")
    lines.append("|---|---|:-:|:-:|:-:|:-:|:-:|---|")
    for t in v.trial_verdicts:
        if t.skipped:
            lines.append(f"| `{t.trial_name}` | {t.family} | — | — | — | — "
                         f"| — | SKIPPED: {t.skip_reason[:40]} |")
            continue
        cells = []
        for i in range(5):
            if i < len(t.per_gate):
                cells.append("✓" if t.per_gate[i]["passed"] else "✗")
            else:
                cells.append("—")
        verdict = ("DEPLOY-READY" if t.gauntlet_passed
                   else ("CONDITIONAL" if t.gates_1_to_4_passed else "FAIL"))
        lines.append(f"| `{t.trial_name}` | {t.family} | "
                     + " | ".join(cells) + f" | {verdict} |")
    lines.append("")

    # Per-trial gate detail
    failing_trials = [t for t in v.trial_verdicts
                      if not t.skipped and not t.gauntlet_passed]
    if failing_trials:
        lines.append("## Per-trial gate detail")
        lines.append("")
        for t in failing_trials:
            lines.append(f"### `{t.trial_name}`")
            for g in t.per_gate:
                tag = "✓" if g["passed"] else "✗"
                lines.append(f"- **{g['gate_name']}** {tag} — {g['summary']}")
            lines.append("")

    return "\n".join(lines)


def _verdict_to_json(v: Phase3Verdict) -> dict[str, Any]:
    return {
        "verdict": v.verdict,
        "survivors": v.survivors,
        "conditional_survivors": v.conditional_survivors,
        "failures": v.failures,
        "trial_verdicts": [asdict(t) for t in v.trial_verdicts],
        "total_trials_evaluated": v.total_trials_evaluated,
        "n_trials_for_dsr": v.n_trials_for_dsr,
        "factor_residualization_applied": v.factor_residualization_applied,
        "generated_at": v.generated_at,
        "design_doc_sha": v.design_doc_sha,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _design_doc_hash(path: Path) -> str:
    if not path.exists():
        return ""
    import hashlib
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Run Phase 3 gauntlet on Phase 1 survivors."
    )
    p.add_argument("--phase1-results", type=Path,
                   default=Path("research/PHASE1_RESULTS.json"))
    p.add_argument("--processed-dir", type=Path,
                   default=Path("data/processed/bhavcopy"))
    p.add_argument("--factor-matrix", type=Path, default=None,
                   help="Optional CSV with four-factor returns (market, "
                        "risk_free, smb, liquidity), date-indexed.")
    p.add_argument("--results-json", type=Path,
                   default=Path("research/PHASE3_RESULTS.json"))
    p.add_argument("--verdict-md", type=Path,
                   default=Path("research/GAUNTLET_VERDICT.md"))
    p.add_argument("--design-doc", type=Path,
                   default=Path("research/INDIA_DESIGN.md"))
    p.add_argument("-v", "--verbose", action="count", default=0)
    args = p.parse_args(argv)

    logging.basicConfig(
        level=max(logging.WARNING - 10 * args.verbose, logging.DEBUG),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    log.info("Loading Phase 1 survivors from %s ...", args.phase1_results)
    deliv_survivors, foe_survivors = load_phase1_survivors(args.phase1_results)
    total_survivors = len(deliv_survivors) + len(foe_survivors)
    log.info("  %d delivery-pct + %d F&O expiry survivors",
             len(deliv_survivors), len(foe_survivors))

    if total_survivors == 0:
        # Short-circuit: no survivors → no Phase 3. Write a CLOSED FAILED
        # verdict that documents this clearly.
        verdict = build_phase3_verdict(
            trial_verdicts=[],
            factor_residualization_applied=False,
            design_doc_sha=_design_doc_hash(args.design_doc),
        )
        args.results_json.parent.mkdir(parents=True, exist_ok=True)
        args.results_json.write_text(json.dumps(_verdict_to_json(verdict),
                                                indent=2, default=str))
        args.verdict_md.parent.mkdir(parents=True, exist_ok=True)
        args.verdict_md.write_text(render_markdown_verdict(verdict))
        log.warning("Phase 1 produced 0 survivors — Phase 3 SKIPPED. "
                    "Verdict file written for record.")
        return 1

    log.info("Loading OOS panel from %s ...", args.processed_dir)
    close_df, deliv_pct_df = load_oos_panel(args.processed_dir)
    log.info("  loaded %d dates × %d symbols",
             len(close_df.index), len(close_df.columns))

    factor_matrix: pd.DataFrame | None = None
    if args.factor_matrix and args.factor_matrix.exists():
        factor_matrix = pd.read_csv(args.factor_matrix,
                                     index_col=0, parse_dates=True)
        log.info("  factor matrix loaded: %d dates × %d factors",
                 len(factor_matrix), len(factor_matrix.columns))
    else:
        log.warning("No factor matrix supplied — residualization SKIPPED. "
                    "Verdict will be marked provisional.")

    trial_verdicts: list[TrialVerdict] = []
    for name in deliv_survivors:
        log.info("Phase 3: %s", name)
        trial_verdicts.append(evaluate_trial_deliv_pct(
            name, close_df, deliv_pct_df,
            factor_matrix=factor_matrix, n_trials=N_TRIALS,
        ))
    for name in foe_survivors:
        log.info("Phase 3: %s (SKIP — F&O not implemented)", name)
        trial_verdicts.append(evaluate_trial_fo_expiry(name))

    verdict = build_phase3_verdict(
        trial_verdicts=trial_verdicts,
        factor_residualization_applied=(factor_matrix is not None),
        design_doc_sha=_design_doc_hash(args.design_doc),
    )

    args.results_json.parent.mkdir(parents=True, exist_ok=True)
    args.results_json.write_text(json.dumps(_verdict_to_json(verdict), indent=2,
                                            default=str))
    args.verdict_md.parent.mkdir(parents=True, exist_ok=True)
    args.verdict_md.write_text(render_markdown_verdict(verdict))

    log.info("Phase 3 complete. Verdict: %s. Survivors: %d. Conditional: %d.",
             verdict.verdict, len(verdict.survivors),
             len(verdict.conditional_survivors))
    return 0 if verdict.verdict == "DEPLOY-READY" else 1


if __name__ == "__main__":
    sys.exit(main())
