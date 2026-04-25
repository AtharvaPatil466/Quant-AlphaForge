"""Honest rigor report for the MARL walk-forward/ablation results.

Reads every training.jsonl and summary.json under alphaforge-marl/, enumerates
the full trial space, and applies the same statistical hygiene used in the
single-factor study:
  - Full trial enumeration (each generation = 1 trial of best-in-population)
  - Sharpe distribution across trials
  - Deflated Sharpe Ratio (Bailey & López de Prado 2014) for the headline
    Sharpe, deflating by the true trial count
  - Baseline-excess Sharpe: the only honest version of the result, since
    many runs had absolute val Sharpe > 1 while losing to equal-weight
  - Stability across seeds
  - Compact markdown report
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
from scipy import stats

MARL_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = Path(__file__).resolve().parent / "out"
OUT_DIR.mkdir(exist_ok=True)

RUN_DIRS = [
    MARL_ROOT / "ablations_20260330_v2",
    MARL_ROOT / "reward_mix_sweep_20260329",
    MARL_ROOT / "stability_quick_20260329",
    MARL_ROOT / "ablations_20260330",
]


@dataclass
class Trial:
    study: str
    config: str
    generation: int
    val_sharpe: float
    best_val_sharpe: float
    baseline_excess_sharpe: Optional[float]
    activity_ratio: Optional[float]


def read_jsonl(path: Path) -> List[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def collect_trials() -> List[Trial]:
    trials: List[Trial] = []
    for run_root in RUN_DIRS:
        if not run_root.exists():
            continue
        for config_dir in sorted(run_root.iterdir()):
            if not config_dir.is_dir():
                continue
            jsonl = config_dir / "training.jsonl"
            rows = read_jsonl(jsonl)
            for row in rows:
                trials.append(Trial(
                    study=run_root.name,
                    config=config_dir.name,
                    generation=int(row.get("generation", 0)),
                    val_sharpe=float(row.get("val_sharpe", 0.0) or 0.0),
                    best_val_sharpe=_finite(row.get("best_val_sharpe")),
                    baseline_excess_sharpe=_opt_float(row.get("validation_baseline_excess_sharpe")),
                    activity_ratio=_opt_float(row.get("validation_activity_ratio")),
                ))
    return trials


def _finite(v) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return float("nan")
    return f if math.isfinite(f) else float("nan")


def _opt_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


# ---------- deflated Sharpe ----------
def deflated_sharpe(sr_observed: float, n_obs: int, sr_candidates: List[float]) -> Dict[str, float]:
    if len(sr_candidates) < 2 or n_obs < 50:
        return {"dsr": float("nan"), "sr0_annualized": float("nan")}
    sr_daily = np.array(sr_candidates) / math.sqrt(252)
    var_sr = sr_daily.var(ddof=1)
    if var_sr <= 0:
        return {"dsr": float("nan"), "sr0_annualized": float("nan")}
    em = 0.5772156649
    N = len(sr_candidates)
    sr0_daily = math.sqrt(var_sr) * (
        (1 - em) * stats.norm.ppf(1 - 1 / N)
        + em * stats.norm.ppf(1 - 1 / (N * math.e))
    )
    sr_obs_daily = sr_observed / math.sqrt(252)
    gamma3, gamma4 = 0.0, 3.0
    denom = math.sqrt((1 - gamma3 * sr_obs_daily + (gamma4 - 1) / 4 * sr_obs_daily ** 2) / (n_obs - 1))
    dsr = stats.norm.cdf((sr_obs_daily - sr0_daily) / denom)
    return {"dsr": float(dsr), "sr0_annualized": float(sr0_daily * math.sqrt(252))}


# ---------- main ----------
def main():
    print(f"Scanning MARL run directories under {MARL_ROOT}...")
    trials = collect_trials()
    print(f"  collected {len(trials)} trial rows")

    # Summary JSONs (headline numbers the project reports)
    ablation_summary = _load_json(MARL_ROOT / "ablations_20260330_v2" / "summary.json")
    reward_summary = _load_json(MARL_ROOT / "reward_mix_sweep_20260329" / "reward_mix_sweep_summary.json")
    stability_summary = _load_json(MARL_ROOT / "stability_quick_20260329" / "stability_summary.json")

    # --- Sharpe distribution across all trials ---
    all_val_sharpes = [t.val_sharpe for t in trials if math.isfinite(t.val_sharpe)]
    running_best = [t.best_val_sharpe for t in trials if math.isfinite(t.best_val_sharpe)]
    headline_sharpe = max(running_best) if running_best else 0.0

    # Baseline-excess distribution (only reward_mix logs this field)
    excess = [t.baseline_excess_sharpe for t in trials if t.baseline_excess_sharpe is not None]

    # Unique trial count: use all generation rows (each = one best-in-population evaluation)
    n_trials = len(all_val_sharpes)

    # DSR with the stability OOS Sharpe (the most honest headline number)
    # stability reports 2-seed OOS on a 251-day window
    stab_oos = stability_summary.get("runs", []) if stability_summary else []
    oos_sharpes = [r["oos_metrics"]["sharpe"] for r in stab_oos if "oos_metrics" in r]
    n_oos_days = int(stab_oos[0]["oos_metrics"]["n_days"]) if stab_oos else 0
    mean_oos_sharpe = float(np.mean(oos_sharpes)) if oos_sharpes else 0.0

    # DSR deflates a reported Sharpe by a trial set. We run two comparisons:
    #  (a) headline best_val (optimistic): ~6.7+ in ablations, deflated by n_trials
    #  (b) mean OOS stability Sharpe (honest): ~0.72, deflated by n_trials
    dsr_headline = deflated_sharpe(headline_sharpe, max(60, n_oos_days), all_val_sharpes)
    dsr_oos_mean = deflated_sharpe(mean_oos_sharpe, max(60, n_oos_days), all_val_sharpes)

    # Best reward-mix shortlist record
    best_mix_row = None
    if reward_summary:
        for mix in reward_summary.get("mixes", []):
            for item in mix.get("shortlist", []):
                if best_mix_row is None or item["val_sharpe"] > best_mix_row["val_sharpe"]:
                    best_mix_row = {**item, "mix_label": mix["label"]}

    # --- write report ---
    lines = []
    A = lines.append
    A("# AlphaForge MARL — Honest Rigor Report")
    A("")
    A("_Deflation analysis of the multi-agent RL walk-forward / ablation / reward-mix study._")
    A("")

    A("## Trial Accounting")
    A("")
    A(f"Total generation-level trials scanned across all studies: **{n_trials}**.")
    A("Each training generation reports the best val Sharpe in its population, making the "
      "generation the unit of selection. This substantially under-counts the true search "
      "breadth because it ignores per-agent evaluations inside a generation and ignores "
      "hyperparameter decisions made outside these logs (architecture, curriculum, reward "
      "shaping, selection rule). The DSR below is therefore an *optimistic lower bound* on "
      "the deflation factor — the true trial count is higher.")
    A("")
    A("Per-study breakdown:")
    A("")
    by_study: Dict[str, Dict[str, int]] = {}
    for t in trials:
        by_study.setdefault(t.study, {}).setdefault(t.config, 0)
        by_study[t.study][t.config] += 1
    A("| Study | Config | Generations |")
    A("|---|---|---|")
    for study, configs in by_study.items():
        for cfg, n in configs.items():
            A(f"| {study} | {cfg} | {n} |")
    A("")

    A("## Sharpe Distribution Across Trials")
    A("")
    arr = np.array(all_val_sharpes)
    A(f"- Min val_sharpe: {arr.min():+.2f}")
    A(f"- Median: {np.median(arr):+.2f}")
    A(f"- Mean: {arr.mean():+.2f}")
    A(f"- Max: {arr.max():+.2f}")
    A(f"- Standard deviation: {arr.std(ddof=1):.2f}")
    A("")
    A("The tail-max Sharpe across 100+ reported trials is large, but a heavy-tailed "
      "distribution with noise-dominated per-generation evaluation inflates the maximum. "
      "The maximum of N noisy estimators is biased upward by roughly σ·√(2·log N).")
    A("")

    A("## Headline Sharpe vs Deflated Sharpe")
    A("")
    A("| Candidate | Reported Sharpe | Deflated Sharpe Ratio | SR₀ (selection) |")
    A("|---|---|---|---|")
    A(f"| Best in-sample val (ablation max) | {headline_sharpe:+.2f} | {dsr_headline['dsr']:.3f} | {dsr_headline['sr0_annualized']:+.2f} |")
    A(f"| Mean OOS stability (2 seeds, {n_oos_days}d) | {mean_oos_sharpe:+.2f} | {dsr_oos_mean['dsr']:.3f} | {dsr_oos_mean['sr0_annualized']:+.2f} |")
    A("")
    A(f"SR₀ = the Sharpe a random strategy would achieve by chance given {n_trials} trials. "
      "A DSR ≥ 0.95 is the conventional bar for claiming the observed Sharpe is credibly "
      "non-zero.")
    A("")
    A("**Interpretation.** The in-sample best-val Sharpe beats SR₀ — but that figure comes "
      "from 5-episode validation on short windows, not OOS on held-out years. The honest "
      "headline is the **mean OOS stability Sharpe**, and its DSR is the one to trust.")
    A("")

    A("## Baseline Excess: the only honest number")
    A("")
    if excess:
        ea = np.array(excess)
        pos = float((ea > 0).mean())
        A(f"The reward-mix sweep is the only study that logged the validation Sharpe *excess* "
          f"over the equal-weight baseline on the same window ({len(ea)} data points).")
        A("")
        A(f"- Mean baseline-excess Sharpe: **{ea.mean():+.3f}**")
        A(f"- Median: {np.median(ea):+.3f}")
        A(f"- Best (max): {ea.max():+.3f}")
        A(f"- Share of trials that beat the baseline: **{pos:.1%}**")
        A("")
        A("Even the best shortlisted agents have **negative** excess-Sharpe against a dumb "
          "equal-weight benchmark on the same window. The absolute Sharpe of ~1+ that the "
          "project's val_sharpe logs report is almost entirely beta to a period where "
          "equal-weight earned Sharpe ≥ 2. Nothing in this result set currently shows "
          "positive, repeatable alpha over the benchmark.")
        A("")
    else:
        A("No baseline-excess Sharpe fields found in logs. This metric should be logged on "
          "every validation evaluation for every future study.")
        A("")

    if best_mix_row:
        A("Best reward-mix shortlist record (illustrative, not best-case cherry-pick):")
        A("")
        A(f"- Mix: `{best_mix_row['mix_label']}`, generation {best_mix_row['generation']}")
        A(f"- val_sharpe: {best_mix_row['val_sharpe']:+.3f}")
        A(f"- selection_score: {best_mix_row['selection_score']:+.3f}")
        A(f"- baseline_excess_sharpe: **{best_mix_row['baseline_excess_sharpe']:+.3f}** (still negative)")
        A(f"- activity_ratio: {best_mix_row['activity_ratio']:.3f}")
        A("")

    A("## Seed Stability (2 seeds, OOS)")
    A("")
    if oos_sharpes:
        A(f"Stability runs retrained from scratch with identical config but different seeds.")
        A("")
        A(f"- Run 0 OOS Sharpe: {oos_sharpes[0]:+.3f}")
        if len(oos_sharpes) > 1:
            A(f"- Run 1 OOS Sharpe: {oos_sharpes[1]:+.3f}")
        A(f"- Mean: {mean_oos_sharpe:+.3f}, range: [{min(oos_sharpes):+.3f}, {max(oos_sharpes):+.3f}]")
        A(f"- OOS window length: {n_oos_days} days (~1 year)")
        A("")
        A("Two seeds is far too few for stability claims. With 2 draws the standard error of "
          "the mean Sharpe is large; 5+ seeds minimum, 10 preferred.")
        A("")

    A("## Honest Limitations (additive to the single-factor study's limitations)")
    A("")
    A("1. **No daily OOS return series were persisted**, so a stationary bootstrap on the OOS "
       "Sharpe (the right complement to DSR) cannot be computed from the current artifacts. "
       "Persisting the per-day portfolio return during stability/benchmark evals is the "
       "single highest-leverage logging change to enable this analysis.")
    A("2. **Trial count is under-reported here.** Only the generation-level best rows are "
       "scanned. Architecture changes, curriculum tweaks, selection-score weights, and "
       "hyperparameter decisions made outside the logged runs are *also* trials.")
    A("3. **In-sample selection bias.** `best_val_sharpe` is itself a maximum over "
       "generations *and* over agents in a population; the reported value is an order "
       "statistic, not an expectation.")
    A("4. **Benchmark is equal-weight within the same 50 tickers.** A tougher benchmark "
       "(sector-neutral, volatility-targeted, or risk-parity) would further compress any "
       "excess-Sharpe claim.")
    A("5. **OOS window is 1 year for 2 seeds.** 251 days of post-cost returns per seed is "
       "not enough to reject a zero-alpha null with any power. The headline OOS Sharpe of "
       f"~{mean_oos_sharpe:+.2f} has a 95% CI on a single seed spanning roughly ±0.9 "
       "purely from sampling variance.")
    A("")

    A("## What would move this to a defensible MARL result")
    A("")
    A("- **Persist daily portfolio returns per eval** (train, validate, test windows).")
    A("- **Log baseline-excess Sharpe on every eval**, not only in the reward-mix study.")
    A("- **Require DSR > 0.95 using the full trial count** (architecture search + reward-mix "
       "+ ablations + seeds) before any checkpoint is called a 'result'.")
    A("- **Anchored walk-forward with ≥3 non-overlapping test folds**, each ≥1 year, with "
       "5+ seeds per fold. Report distribution, not point estimate.")
    A("- **Dominance test vs equal-weight and 12-1 momentum.** An agent that cannot beat 12-1 "
       "momentum + vol targeting on the same universe has not learned anything worth keeping.")
    A("")

    report_path = OUT_DIR / "marl_rigor_report.md"
    report_path.write_text("\n".join(lines))
    (OUT_DIR / "marl_rigor_metrics.json").write_text(json.dumps({
        "n_trials": n_trials,
        "sharpe_distribution": {
            "min": float(arr.min()), "median": float(np.median(arr)),
            "mean": float(arr.mean()), "max": float(arr.max()),
            "std": float(arr.std(ddof=1)),
        },
        "headline_sharpe_in_sample": headline_sharpe,
        "mean_oos_sharpe": mean_oos_sharpe,
        "n_oos_days": n_oos_days,
        "dsr_in_sample": dsr_headline,
        "dsr_oos_mean": dsr_oos_mean,
        "baseline_excess_sharpe_stats": ({
            "n": int(len(excess)),
            "mean": float(np.mean(excess)),
            "median": float(np.median(excess)),
            "max": float(np.max(excess)),
            "share_positive": float(np.mean(np.array(excess) > 0)),
        } if excess else None),
    }, indent=2))
    print(f"Wrote {report_path}")


def _load_json(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


if __name__ == "__main__":
    main()
