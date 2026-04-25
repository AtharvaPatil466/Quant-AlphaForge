"""MARL ablation ladder with paired bootstrap significance.

Computes, for each pair of ablation configurations found in training
artifacts under alphaforge-marl/, a paired stationary-bootstrap test on
the difference of Sharpes: does adding MARL (vs single-agent PPO, vs
equal-weight) produce a Sharpe lift that survives bootstrap resampling?

Configurations are identified by name prefixes:
  - ``baseline_equal_weight`` : universe equal-weight (no learning)
  - ``single_agent_ppo``      : single-agent PPO (no evolution, no bandit)
  - ``marl_full``             : full stack (evolution + PPO + MAML + bandit)

Paired test uses the per-day validation return series saved in
``oos_metrics.daily_returns`` (see CLAUDE.md: daily-series logging).

Output:
  research/out/ablation_ladder_report.md
  research/out/ablation_ladder_results.json
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

MARL_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = Path(__file__).resolve().parent / "out"
OUT_DIR.mkdir(exist_ok=True)

# Configurations we look for. The actual naming will depend on the user's
# ablation batch; `config` here is a substring match against directory names.
LADDER = [
    ("baseline_equal_weight", "Equal-weight universe (no learning)"),
    ("single_agent_ppo",      "Single-agent PPO (no evolution, no bandit)"),
    ("no_bandit",             "MARL − bandit (evolution + PPO only)"),
    ("no_evolution",          "MARL − evolution (PPO + bandit only)"),
    ("marl_full",             "Full MARL stack"),
]

BOOT_REPS = 2000
BOOT_BLOCKS = 21
SEED = 42


@dataclass
class ConfigRun:
    name: str
    label: str
    daily_returns: np.ndarray  # concatenated across folds
    source_path: str


def _find_summary_files(root: Path) -> List[Path]:
    """All summary.json files under the MARL root — the per-config evaluation
    artifacts produced by evaluate_checkpoint_cost_grid / walk-forward."""
    return sorted(root.rglob("summary.json"))


def _extract_daily_returns(summary: dict) -> Optional[np.ndarray]:
    """Pull the concatenated daily-return series from a summary dict.

    The daily-series logging is documented in CLAUDE.md: list-valued keys
    are concatenated across windows inside ``oos_metrics.daily_returns``
    or inside each fold's ``metrics.daily_returns``.
    """
    oos = summary.get("oos_metrics", {})
    daily = oos.get("daily_returns")
    if isinstance(daily, list) and len(daily) > 30:
        return np.asarray(daily, dtype=float)
    # Try per-fold aggregation
    folds = summary.get("folds") or summary.get("windows") or []
    combined: List[float] = []
    for f in folds:
        m = f.get("metrics", {}) if isinstance(f, dict) else {}
        dr = m.get("daily_returns")
        if isinstance(dr, list):
            combined.extend(dr)
    if len(combined) > 30:
        return np.asarray(combined, dtype=float)
    return None


def collect_runs() -> List[ConfigRun]:
    runs: List[ConfigRun] = []
    for path in _find_summary_files(MARL_ROOT):
        try:
            data = json.loads(path.read_text())
        except Exception:
            continue
        series = _extract_daily_returns(data)
        if series is None:
            continue
        name_lower = str(path.parent.name).lower()
        for prefix, label in LADDER:
            if prefix in name_lower:
                runs.append(ConfigRun(name=path.parent.name, label=label,
                                     daily_returns=series, source_path=str(path)))
                break
    return runs


# ─── paired stationary bootstrap on Sharpe delta ─────────────────────────

def _ann_sharpe(r: np.ndarray) -> float:
    if len(r) < 30 or r.std(ddof=1) == 0:
        return 0.0
    return float(r.mean() / r.std(ddof=1) * math.sqrt(252))


def paired_bootstrap_sharpe_diff(
    a: np.ndarray, b: np.ndarray, reps: int = BOOT_REPS,
    mean_block: int = BOOT_BLOCKS, seed: int = SEED,
) -> Dict[str, float]:
    """Paired stationary bootstrap on Sharpe(a) − Sharpe(b).

    Both series must be aligned (same length, same dates). Uses shared
    resampling indices so we isolate the strategy difference from
    market-day effects.
    """
    n = min(len(a), len(b))
    if n < 60:
        return {"delta_mean": 0.0, "ci_lo": 0.0, "ci_hi": 0.0, "p_positive": 0.0}
    a = a[-n:]; b = b[-n:]
    rng = np.random.default_rng(seed)
    p = 1.0 / mean_block
    out = np.empty(reps)
    for r in range(reps):
        idxs = np.empty(n, dtype=np.int64)
        i = int(rng.integers(0, n))
        for k in range(n):
            if k > 0 and rng.random() < p:
                i = int(rng.integers(0, n))
            else:
                i = (i + 1) % n if k > 0 else i
            idxs[k] = i
        sa = a[idxs]; sb = b[idxs]
        out[r] = _ann_sharpe(sa) - _ann_sharpe(sb)
    return {
        "delta_mean": float(out.mean()),
        "ci_lo": float(np.quantile(out, 0.025)),
        "ci_hi": float(np.quantile(out, 0.975)),
        "p_positive": float((out > 0).mean()),
        "observed_delta": _ann_sharpe(a) - _ann_sharpe(b),
    }


def main():
    runs = collect_runs()
    if not runs:
        print("No MARL summary.json with daily_returns found under", MARL_ROOT)
        print("Skipping ablation ladder — rerun an ablation batch first.")
        # Still emit an empty report so downstream CI has a stable target
        (OUT_DIR / "ablation_ladder_report.md").write_text(
            "# MARL Ablation Ladder\n\n_No runs with daily_returns logs found._\n"
        )
        (OUT_DIR / "ablation_ladder_results.json").write_text(
            json.dumps({"runs": [], "comparisons": []}, indent=2)
        )
        return

    # Collapse multiple runs per config by mean Sharpe (keep the longest series)
    by_label: Dict[str, ConfigRun] = {}
    for r in runs:
        prev = by_label.get(r.label)
        if prev is None or len(r.daily_returns) > len(prev.daily_returns):
            by_label[r.label] = r

    labels_in_order = [lbl for _, lbl in LADDER if lbl in by_label]

    # Pairwise comparisons up the ladder
    comparisons = []
    for i in range(1, len(labels_in_order)):
        hi = by_label[labels_in_order[i]]
        lo = by_label[labels_in_order[i - 1]]
        result = paired_bootstrap_sharpe_diff(hi.daily_returns, lo.daily_returns)
        comparisons.append({
            "upper": hi.label,
            "lower": lo.label,
            "upper_sharpe": _ann_sharpe(hi.daily_returns),
            "lower_sharpe": _ann_sharpe(lo.daily_returns),
            **result,
        })

    # Also: every rung vs equal-weight if present
    vs_ew = []
    if labels_in_order and "Equal-weight" in labels_in_order[0]:
        ew = by_label[labels_in_order[0]]
        for lbl in labels_in_order[1:]:
            hi = by_label[lbl]
            result = paired_bootstrap_sharpe_diff(hi.daily_returns, ew.daily_returns)
            vs_ew.append({
                "config": lbl,
                "config_sharpe": _ann_sharpe(hi.daily_returns),
                "baseline_sharpe": _ann_sharpe(ew.daily_returns),
                **result,
            })

    summary = {
        "runs": [
            {"label": r.label, "n_days": int(len(r.daily_returns)),
             "sharpe": _ann_sharpe(r.daily_returns), "source": r.source_path}
            for r in by_label.values()
        ],
        "ladder_comparisons": comparisons,
        "versus_equal_weight": vs_ew,
        "bootstrap_config": {"reps": BOOT_REPS, "mean_block": BOOT_BLOCKS, "seed": SEED},
    }
    (OUT_DIR / "ablation_ladder_results.json").write_text(
        json.dumps(summary, indent=2, default=float)
    )

    lines = []
    A = lines.append
    A("# MARL Ablation Ladder — Paired Bootstrap Sharpe Differences")
    A("")
    A("Honest question: does each layer of the MARL stack add Sharpe that "
      "survives paired stationary-bootstrap resampling vs the rung below?")
    A("")
    A("## Configurations Found")
    A("")
    A("| Rung | Days | Ann. Sharpe | Source |")
    A("|---|---:|---:|---|")
    for r in by_label.values():
        A(f"| {r.label} | {len(r.daily_returns)} | {_ann_sharpe(r.daily_returns):+.2f} "
          f"| `{Path(r.source_path).relative_to(MARL_ROOT)}` |")
    A("")
    A("## Adjacent-Rung Comparisons")
    A("")
    A("| Upper | Lower | ΔSharpe (obs) | 95% CI | p(Δ>0) |")
    A("|---|---|---:|---:|---:|")
    for c in comparisons:
        A(f"| {c['upper']} | {c['lower']} | {c['observed_delta']:+.2f} | "
          f"[{c['ci_lo']:+.2f}, {c['ci_hi']:+.2f}] | {c['p_positive']:.2f} |")
    A("")
    if vs_ew:
        A("## Each Rung vs Equal-Weight Baseline")
        A("")
        A("| Rung | ΔSharpe | 95% CI | p(Δ>0) |")
        A("|---|---:|---:|---:|")
        for v in vs_ew:
            A(f"| {v['config']} | {v['observed_delta']:+.2f} | "
              f"[{v['ci_lo']:+.2f}, {v['ci_hi']:+.2f}] | {v['p_positive']:.2f} |")
        A("")
    A("## Interpretation")
    A("")
    A("A Sharpe-delta whose 95% CI brackets zero means the added component "
      "has no statistically distinguishable contribution on this validation "
      "set. A strict 10/10 research project would prune any such component.")
    (OUT_DIR / "ablation_ladder_report.md").write_text("\n".join(lines))
    print("Wrote", OUT_DIR / "ablation_ladder_report.md")


if __name__ == "__main__":
    main()
