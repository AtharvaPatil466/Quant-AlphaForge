"""Phase 1 orchestrator — runs all 22 pre-committed trials on IS data.

Per `research/INDIA_DESIGN.md` §8. Phase 1 is a pre-filter: which of the
22 pre-committed signal trials deserve Phase 2 + Phase 3 work? OOS data
is NOT touched here — only the IS window 2004-01-01 → 2014-12-31.

Two signal families:

  1. Delivery-pct (§8.1) — 18 trials. For each trial, compute the
     cross-sectional z-score signal, the IC at the trial's holding
     period, and the **dual-window** IC report mandated by §8.1
     (full IS + 2010-onward sub-window separately; sign agreement
     required between windows or the trial fails Phase 1A).

  2. F&O expiry (§8.3) — 4 trials. Event-study t-test on pre/post
     expiry returns. Pass: p < 0.05 at pre OR post AND ≥ 70% sign
     consistency.

(FII/DII Phase 1B is CANCELLED per §17 ADDENDUM and is not run.)

Output:
  - `research/PHASE1_RESULTS.json` — full metrics for all 22 trials
  - `research/PHASE1_VERDICT.md`  — markdown summary + survivors list

Phase 1 exit rule (§8.4): at least one signal must pass for the substrate
to proceed to Phase 2. Zero survivors → CLOSED FAILED at Phase 1.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

# Path bootstrap — allow `python -m research.run_phase1` from sub-project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from signals import delivery_pct as DP  # noqa: E402
from signals import fo_expiry as FOE    # noqa: E402

log = logging.getLogger("india.run_phase1")


# ---------------------------------------------------------------------------
# Constants from INDIA_DESIGN.md
# ---------------------------------------------------------------------------

IS_START = date(2004, 1, 1)
IS_END = date(2014, 12, 31)

# §8.1 mandatory dual-window IC report — sub-window for post-quality-improvement
# delivery-pct data per §14.1.
DUAL_WINDOW_SUB_START = date(2010, 1, 1)

# §8.1 pass criteria thresholds.
IC_THRESHOLD = 0.03                  # |IC| must exceed this at trial horizon
ROLLING_IC_POS_FRAC = 0.70           # ≥ 70% of rolling 12-month windows positive
ROLLING_WINDOW_DAYS = 252            # ~ 12 trading months

# §8.3 pass criteria — implemented in `signals.fo_expiry.run_event_study`.


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class DeliveryPctPhase1Result:
    trial_name: str
    lookback: int
    bucket: str
    holding_period: int

    # Full IS window
    ic_full_is: float | None
    ic_full_is_n: int
    rolling_ic_full_pos_frac: float | None
    rolling_ic_full_n: int

    # 2010-onward sub-window
    ic_subwindow: float | None
    ic_subwindow_n: int
    rolling_ic_sub_pos_frac: float | None
    rolling_ic_sub_n: int

    # Pass criteria
    passes_ic_threshold: bool
    passes_sign_agreement: bool
    passes_rolling_positivity: bool
    passes_phase1: bool

    reason: str = ""


@dataclass
class Phase1Verdict:
    is_start: str
    is_end: str
    deliv_pct_results: list[DeliveryPctPhase1Result]
    foe_results: list[dict[str, Any]]
    survivors_deliv_pct: list[str]
    survivors_foe: list[str]
    total_trials: int
    n_survivors: int
    closed_failed_at_phase1: bool
    generated_at: str
    design_doc_sha: str = ""


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_bhavcopy_panel(
    processed_dir: Path, is_start: date, is_end: date,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load processed bhavcopy parquet, filter to IS, pivot to wide panels.

    Returns
    -------
    (close_df, deliv_pct_df) — both wide panels, index=trading dates,
    columns=symbols. NaN where a symbol didn't trade.
    """
    # Accept either {YYYY}.parquet (canonical, written by ingest.build_parquet)
    # or legacy bhavcopy*.parquet test fixtures.
    files = sorted(
        list(processed_dir.rglob("[0-9][0-9][0-9][0-9].parquet"))
        + list(processed_dir.rglob("bhavcopy*.parquet"))
    )
    if not files:
        raise FileNotFoundError(
            f"no bhavcopy parquets under {processed_dir}. Run the downloader "
            "+ parsers before Phase 1."
        )
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    df = df[(df["date"] >= pd.Timestamp(is_start))
            & (df["date"] <= pd.Timestamp(is_end))]
    if df.empty:
        raise ValueError(f"no rows in IS window [{is_start}, {is_end}]")
    # Defensive dedup: era-overlap dates can appear twice in the parquet
    # store. Exact-identical rows are safe to drop.
    df = df.drop_duplicates(subset=["date", "symbol"], keep="first")

    close_df = df.pivot(index="date", columns="symbol", values="close")
    deliv_pct_df = df.pivot(index="date", columns="symbol", values="deliv_pct")
    close_df = close_df.sort_index()
    deliv_pct_df = deliv_pct_df.sort_index()
    # Align columns — symbols missing from either panel become all-NaN.
    all_syms = close_df.columns.union(deliv_pct_df.columns)
    close_df = close_df.reindex(columns=all_syms)
    deliv_pct_df = deliv_pct_df.reindex(columns=all_syms)
    return close_df, deliv_pct_df


def apply_membership_mask(
    panel: pd.DataFrame, membership_mask: pd.DataFrame | None,
) -> pd.DataFrame:
    """Mask non-members to NaN. PIT discipline (§3): only symbols in the
    Nifty 500 on date `d` are eligible for that date's signal.

    If `membership_mask` is None (no PIT layer), returns panel unchanged.
    """
    if membership_mask is None:
        return panel
    aligned = membership_mask.reindex(
        index=panel.index, columns=panel.columns, fill_value=False
    )
    return panel.where(aligned)


# ---------------------------------------------------------------------------
# IC + rolling-IC helpers
# ---------------------------------------------------------------------------

def _aggregate_ic(ic_series: pd.Series) -> tuple[float | None, int]:
    """Mean of a per-rebalance-date IC series, with sample size."""
    s = ic_series.dropna()
    if s.empty:
        return None, 0
    return float(s.mean()), int(len(s))


def _rolling_ic_pos_frac(
    ic_series: pd.Series, window_days: int = ROLLING_WINDOW_DAYS,
) -> tuple[float | None, int]:
    """Fraction of rolling 12-month windows where the IC mean is positive.

    Returns (frac, n_windows). frac is None if there's no full-length window.
    """
    s = ic_series.dropna()
    if s.empty:
        return None, 0
    # Treat each IC observation as a sample on its rebalance date. Roll by
    # CALENDAR days using a time-based rolling window.
    s.index = pd.to_datetime(s.index)
    if len(s) < 4:
        return None, 0
    rolling_mean = s.rolling(f"{window_days}D", min_periods=4).mean()
    valid = rolling_mean.dropna()
    if valid.empty:
        return None, 0
    pos_frac = float((valid > 0).mean())
    return pos_frac, int(len(valid))


# ---------------------------------------------------------------------------
# Phase 1A — delivery_pct
# ---------------------------------------------------------------------------

def analyze_deliv_pct_trial(
    trial: DP.DeliveryPctSignal,
    close_df: pd.DataFrame,
    deliv_pct_df: pd.DataFrame,
    sub_window_start: date = DUAL_WINDOW_SUB_START,
) -> DeliveryPctPhase1Result:
    """Run dual-window IC analysis for one delivery-pct trial.

    Per §8.1 pass criteria:
      - |IC| > 0.03 at the trial's holding period
      - IC sign agreement between full IS + 2010-onward sub-window
      - IC positive in ≥ 70% of rolling 12-month windows (each window
        separately satisfies this)
    """
    if close_df.empty or deliv_pct_df.empty:
        return DeliveryPctPhase1Result(
            trial_name=trial.trial_name,
            lookback=trial.lookback, bucket=trial.bucket,
            holding_period=trial.holding_period,
            ic_full_is=None, ic_full_is_n=0,
            rolling_ic_full_pos_frac=None, rolling_ic_full_n=0,
            ic_subwindow=None, ic_subwindow_n=0,
            rolling_ic_sub_pos_frac=None, rolling_ic_sub_n=0,
            passes_ic_threshold=False, passes_sign_agreement=False,
            passes_rolling_positivity=False, passes_phase1=False,
            reason="no data",
        )

    signal_df = trial.compute_signal(close_df, deliv_pct_df)
    fwd_ret_df = DP.compute_forward_returns(close_df, trial.holding_period)
    ic_full = trial.compute_ic_series(signal_df, fwd_ret_df)
    # `compute_ic_series` builds the Series from a dict of Timestamps, which
    # yields an object-dtype Index. Force DatetimeIndex so date subsetting +
    # time-based rolling work downstream.
    if len(ic_full) > 0:
        ic_full.index = pd.to_datetime(ic_full.index)

    sub_ts = pd.Timestamp(sub_window_start)
    ic_sub = ic_full[ic_full.index >= sub_ts] if len(ic_full) else ic_full

    ic_full_mean, n_full = _aggregate_ic(ic_full)
    ic_sub_mean, n_sub = _aggregate_ic(ic_sub)
    rolling_full_pos, n_roll_full = _rolling_ic_pos_frac(ic_full)
    rolling_sub_pos, n_roll_sub = _rolling_ic_pos_frac(ic_sub)

    # Pass criteria per §8.1
    passes_threshold = False
    if ic_full_mean is not None and ic_sub_mean is not None:
        passes_threshold = (abs(ic_full_mean) > IC_THRESHOLD) or (
            abs(ic_sub_mean) > IC_THRESHOLD
        )

    passes_sign = False
    if ic_full_mean is not None and ic_sub_mean is not None:
        passes_sign = np.sign(ic_full_mean) == np.sign(ic_sub_mean) and (
            ic_full_mean != 0
        )

    passes_rolling = False
    if rolling_full_pos is not None and rolling_sub_pos is not None:
        # Sign-aware: if mean IC is negative, we want NEGATIVE rolling
        # windows in proportion. Use absolute "consistency with sign of mean".
        if ic_full_mean is not None and ic_full_mean < 0:
            consistency_full = 1.0 - rolling_full_pos
        else:
            consistency_full = rolling_full_pos
        if ic_sub_mean is not None and ic_sub_mean < 0:
            consistency_sub = 1.0 - rolling_sub_pos
        else:
            consistency_sub = rolling_sub_pos
        passes_rolling = (
            consistency_full >= ROLLING_IC_POS_FRAC
            and consistency_sub >= ROLLING_IC_POS_FRAC
        )

    passes_phase1 = passes_threshold and passes_sign and passes_rolling
    reasons: list[str] = []
    if not passes_threshold:
        reasons.append("IC below 0.03 in both windows")
    if not passes_sign:
        reasons.append("IC sign disagreement between full IS and 2010-onward")
    if not passes_rolling:
        reasons.append("Rolling 12mo IC positive fraction below 70% in some window")

    return DeliveryPctPhase1Result(
        trial_name=trial.trial_name,
        lookback=trial.lookback,
        bucket=trial.bucket,
        holding_period=trial.holding_period,
        ic_full_is=ic_full_mean, ic_full_is_n=n_full,
        rolling_ic_full_pos_frac=rolling_full_pos,
        rolling_ic_full_n=n_roll_full,
        ic_subwindow=ic_sub_mean, ic_subwindow_n=n_sub,
        rolling_ic_sub_pos_frac=rolling_sub_pos,
        rolling_ic_sub_n=n_roll_sub,
        passes_ic_threshold=passes_threshold,
        passes_sign_agreement=passes_sign,
        passes_rolling_positivity=passes_rolling,
        passes_phase1=passes_phase1,
        reason=" | ".join(reasons) if reasons else "ALL CRITERIA MET",
    )


def run_phase1a(
    close_df: pd.DataFrame, deliv_pct_df: pd.DataFrame,
    sub_window_start: date = DUAL_WINDOW_SUB_START,
) -> list[DeliveryPctPhase1Result]:
    """Run all 18 pre-committed delivery-pct trials."""
    results: list[DeliveryPctPhase1Result] = []
    for trial in DP.enumerate_trials():
        log.info("Phase 1A: %s", trial.trial_name)
        results.append(analyze_deliv_pct_trial(
            trial, close_df, deliv_pct_df, sub_window_start=sub_window_start,
        ))
    return results


# ---------------------------------------------------------------------------
# Phase 1C — F&O expiry
# ---------------------------------------------------------------------------

def run_phase1c(
    close_df: pd.DataFrame, expiry_dates: list[date],
) -> list[FOE.EventStudyResult]:
    """Run all 4 F&O expiry trials."""
    if not expiry_dates:
        log.warning("no expiry dates supplied — Phase 1C skipped.")
        return []
    return FOE.run_all_trials(close_df, expiry_dates)


# ---------------------------------------------------------------------------
# Verdict + reporting
# ---------------------------------------------------------------------------

def build_verdict(
    deliv_results: list[DeliveryPctPhase1Result],
    foe_results: list[FOE.EventStudyResult],
    is_start: date, is_end: date,
    design_doc_sha: str = "",
) -> Phase1Verdict:
    survivors_deliv = [r.trial_name for r in deliv_results if r.passes_phase1]
    survivors_foe = [r.trial_name for r in foe_results if r.passed_phase1]
    total = len(deliv_results) + len(foe_results)
    n_surv = len(survivors_deliv) + len(survivors_foe)

    return Phase1Verdict(
        is_start=is_start.isoformat(),
        is_end=is_end.isoformat(),
        deliv_pct_results=deliv_results,
        foe_results=[asdict(r) for r in foe_results],
        survivors_deliv_pct=survivors_deliv,
        survivors_foe=survivors_foe,
        total_trials=total,
        n_survivors=n_surv,
        closed_failed_at_phase1=(n_surv == 0),
        generated_at=datetime.now(__import__("datetime").timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ"),
        design_doc_sha=design_doc_sha,
    )


def render_markdown_verdict(v: Phase1Verdict) -> str:
    lines: list[str] = []
    if v.closed_failed_at_phase1:
        headline = "# Phase 1 Verdict — CLOSED FAILED"
    else:
        headline = f"# Phase 1 Verdict — {v.n_survivors} survivor(s)"
    lines.append(headline)
    lines.append("")
    lines.append(f"_Generated {v.generated_at}_")
    if v.design_doc_sha:
        lines.append(f"_INDIA_DESIGN.md SHA-256: `{v.design_doc_sha}`_")
    lines.append("")
    lines.append(f"**IS window:** {v.is_start} → {v.is_end}")
    lines.append(f"**Total trials:** {v.total_trials} "
                 f"({len(v.deliv_pct_results)} delivery-pct + "
                 f"{len(v.foe_results)} F&O expiry; FII/DII cancelled per §17)")
    lines.append(f"**Survivors:** {v.n_survivors}")
    lines.append("")

    if v.closed_failed_at_phase1:
        lines.append("## Substrate #6 (India) — CLOSED FAILED at Phase 1")
        lines.append("")
        lines.append("Zero of the 22 pre-committed trials cleared the Phase 1 "
                     "pre-filter. Per §8.4 exit rule, Phase 2 is NOT triggered.")
        lines.append("")
    else:
        lines.append("## Survivors")
        lines.append("")
        for s in v.survivors_deliv_pct:
            lines.append(f"- `{s}` (delivery-pct)")
        for s in v.survivors_foe:
            lines.append(f"- `{s}` (F&O expiry)")
        lines.append("")
        lines.append("Per §8.4, all survivors proceed to Phase 2. DSR deflation "
                     "denominator remains 22 trials regardless.")
        lines.append("")

    # Phase 1A trial table
    lines.append("## Phase 1A — Delivery Percentage (18 trials)")
    lines.append("")
    lines.append("| Trial | IC (full IS) | IC (≥2010) | Roll-12mo (full) | "
                 "Roll-12mo (≥2010) | Verdict |")
    lines.append("|---|---:|---:|---:|---:|---|")
    for r in v.deliv_pct_results:
        ic_full = f"{r.ic_full_is:+.4f}" if r.ic_full_is is not None else "—"
        ic_sub = f"{r.ic_subwindow:+.4f}" if r.ic_subwindow is not None else "—"
        rf = (f"{r.rolling_ic_full_pos_frac:.0%}"
              if r.rolling_ic_full_pos_frac is not None else "—")
        rs = (f"{r.rolling_ic_sub_pos_frac:.0%}"
              if r.rolling_ic_sub_pos_frac is not None else "—")
        verdict = "✓ PASS" if r.passes_phase1 else "✗ FAIL"
        lines.append(f"| `{r.trial_name}` | {ic_full} | {ic_sub} "
                     f"| {rf} | {rs} | {verdict} |")
    lines.append("")

    # Phase 1C
    if v.foe_results:
        lines.append("## Phase 1C — F&O Expiry (4 trials)")
        lines.append("")
        lines.append("| Trial | N events | pre p | pre sign | "
                     "post p | post sign | Verdict |")
        lines.append("|---|---:|---:|---:|---:|---:|---|")
        for r in v.foe_results:
            verdict = "✓ PASS" if r["passed_phase1"] else "✗ FAIL"
            lines.append(
                f"| `{r['trial_name']}` | {r['n_events']} "
                f"| {r['pre_return_p_value']:.3f} "
                f"| {r['pre_sign_consistency']:.0%} "
                f"| {r['post_return_p_value']:.3f} "
                f"| {r['post_sign_consistency']:.0%} | {verdict} |"
            )
        lines.append("")

    # Failure reasons table for failed deliv-pct trials
    failed_deliv = [r for r in v.deliv_pct_results if not r.passes_phase1]
    if failed_deliv:
        lines.append("## Phase 1A failure reasons")
        lines.append("")
        lines.append("| Trial | Reason |")
        lines.append("|---|---|")
        for r in failed_deliv:
            lines.append(f"| `{r.trial_name}` | {r.reason} |")
        lines.append("")

    return "\n".join(lines)


def _verdict_to_json(v: Phase1Verdict) -> dict[str, Any]:
    return {
        "is_start": v.is_start,
        "is_end": v.is_end,
        "deliv_pct_results": [asdict(r) for r in v.deliv_pct_results],
        "foe_results": v.foe_results,
        "survivors_deliv_pct": v.survivors_deliv_pct,
        "survivors_foe": v.survivors_foe,
        "total_trials": v.total_trials,
        "n_survivors": v.n_survivors,
        "closed_failed_at_phase1": v.closed_failed_at_phase1,
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
        description="Run Phase 1 of the alphaforge-india gauntlet (22 trials)."
    )
    p.add_argument("--processed-dir", type=Path,
                   default=Path("data/processed/bhavcopy"),
                   help="Directory of processed bhavcopy parquet files.")
    p.add_argument("--expiry-calendar", type=Path,
                   default=Path("data/processed/fo_expiry_calendar.parquet"),
                   help="Path to F&O monthly expiry calendar parquet.")
    p.add_argument("--results-json", type=Path,
                   default=Path("research/PHASE1_RESULTS.json"))
    p.add_argument("--verdict-md", type=Path,
                   default=Path("research/PHASE1_VERDICT.md"))
    p.add_argument("--design-doc", type=Path,
                   default=Path("research/INDIA_DESIGN.md"))
    p.add_argument("--is-start", default=IS_START.isoformat())
    p.add_argument("--is-end", default=IS_END.isoformat())
    p.add_argument("-v", "--verbose", action="count", default=0)
    args = p.parse_args(argv)

    logging.basicConfig(
        level=max(logging.WARNING - 10 * args.verbose, logging.DEBUG),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    is_start = date.fromisoformat(args.is_start)
    is_end = date.fromisoformat(args.is_end)

    log.info("Loading bhavcopy panel %s → %s ...", is_start, is_end)
    close_df, deliv_pct_df = load_bhavcopy_panel(
        args.processed_dir, is_start, is_end
    )
    log.info("  loaded %d dates × %d symbols",
             len(close_df.index), len(close_df.columns))

    # Construct PIT membership mask
    membership_mask = None
    try:
        from universe.isin_master import ISINMaster
        from universe.pit import PITUniverse
        
        base_dir = Path(__file__).resolve().parent.parent
        equity_l_path = base_dir.parent / "EQUITY_L.csv"
        symbolchange_path = base_dir.parent / "symbolchange.csv"
        xls_path = base_dir.parent / "IndexInclExcl.xls"
        nifty500_list_path = base_dir.parent / "ind_nifty500list.csv"
        
        if equity_l_path.exists() and symbolchange_path.exists() and xls_path.exists() and nifty500_list_path.exists():
            log.info("Loading PIT universe and constructing membership mask...")
            im = ISINMaster(
                equity_l_path=equity_l_path,
                symbolchange_path=symbolchange_path,
            )
            pit = PITUniverse(
                xls_path=xls_path,
                isin_master=im,
                nifty500_list_path=nifty500_list_path,
            )
            
            mask_dict = {}
            for d in close_df.index:
                dt = d.date()
                members = pit.membership_on_date(dt)
                mask_dict[d] = {sym: (sym in members) for sym in close_df.columns}
            
            membership_mask = pd.DataFrame.from_dict(mask_dict, orient="index")
            membership_mask = membership_mask.reindex(index=close_df.index, columns=close_df.columns, fill_value=False)
            log.info("  generated membership mask: %d ever-members.", len(pit.ever_members()))
        else:
            log.warning("Some PIT universe files are missing. Proceeding without membership mask.")
    except Exception as e:
        log.warning("Failed to construct membership mask: %r", e)

    if membership_mask is not None:
        close_df = apply_membership_mask(close_df, membership_mask)
        deliv_pct_df = apply_membership_mask(deliv_pct_df, membership_mask)

    # Phase 1A
    deliv_results = run_phase1a(close_df, deliv_pct_df)

    # Phase 1C — load expiry calendar if present.
    expiry_dates: list[date] = []
    if args.expiry_calendar.exists():
        cal = pd.read_parquet(args.expiry_calendar)
        cal = cal[(cal["expiry_date"] >= pd.Timestamp(is_start))
                  & (cal["expiry_date"] <= pd.Timestamp(is_end))]
        expiry_dates = [d.date() for d in pd.to_datetime(cal["expiry_date"])]
        log.info("  %d expiry events in IS window", len(expiry_dates))
    else:
        log.warning("Expiry calendar not found at %s — Phase 1C trials will "
                    "report n_events=0 and FAIL by default.",
                    args.expiry_calendar)
    foe_results = run_phase1c(close_df, expiry_dates)

    sha = _design_doc_hash(args.design_doc)
    verdict = build_verdict(deliv_results, foe_results, is_start, is_end, sha)

    args.results_json.parent.mkdir(parents=True, exist_ok=True)
    args.results_json.write_text(json.dumps(_verdict_to_json(verdict), indent=2,
                                            default=str))
    args.verdict_md.parent.mkdir(parents=True, exist_ok=True)
    args.verdict_md.write_text(render_markdown_verdict(verdict))

    log.info("Phase 1 complete. Survivors: %d / %d. Verdict: %s",
             verdict.n_survivors, verdict.total_trials,
             "CLOSED FAILED" if verdict.closed_failed_at_phase1 else "ADVANCING")
    return 0 if not verdict.closed_failed_at_phase1 else 1


if __name__ == "__main__":
    sys.exit(main())
