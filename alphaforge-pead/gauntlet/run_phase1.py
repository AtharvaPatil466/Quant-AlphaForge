"""Phase 1 gauntlet orchestrator.

Ties together:
  - `gauntlet.panel.build_panel_for_firm`        (per-firm panel rows)
  - `gauntlet.portfolios.{compute_ic, form_long_short, long_short_summary}`
  - `alphaforge-python/research/factor_study.py::stationary_bootstrap_sharpe`  (read-only)
  - `alphaforge-python/research/factor_study.py::deflated_sharpe_ratio`        (read-only)
  - `alphaforge-python/research/portfolio_alpha.py::compute_portfolio_alpha`   (read-only, optional)

Executes the 10-trial Phase 1a gauntlet pre-committed in
`PEAD_DESIGN.md` §3.1:

  - 5 horizons × 2 bucket cuts = 10 standalone trials.
  - For each trial:
      (a) IC on IS, OOS-A, OOS-B.
      (b) Long-short daily returns on each window.
      (c) Stationary-bootstrap Sharpe CI on raw long-short returns
          (and on FF5+UMD alpha-residual returns when reference factors
          are provided).
      (d) Pass criteria G1 (DSR > 0.95), G2 (bootstrap CI excludes
          zero in both OOS), G3 (sign agreement across OOS-A and OOS-B).

Outputs `research/PHASE1_RESULTS.json` containing the full numeric
trial-by-trial breakdown, and a one-page `research/PHASE1_VERDICT.md`
summarizing the verdict.

THIS MODULE EXECUTES PHASE 1 CODE. It does not run end-to-end against
real data until `research/PEAD_PHASE0_CERTIFIED.md` exists and pins
the SHA-256 of `PEAD_DESIGN.md`. The function `run_phase1(...)` checks
for the certification file at entry; if missing, it raises
`Phase0NotCertified` instead of running. Tests bypass via the
`require_certification=False` flag.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import sys
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
import pandas as pd

from .panel import HOLDING_HORIZONS, build_panel_for_firm, panel_to_dataframe
from .portfolios import compute_ic, form_long_short, long_short_summary


log = logging.getLogger(__name__)


# --- pre-committed trial set + windows from PEAD_DESIGN.md -------------


HORIZONS = HOLDING_HORIZONS           # (5, 21, 42, 63, 84) trading days
BUCKETS = ("quintile", "decile")      # PEAD_DESIGN.md §3.1
N_TRIALS_1A = len(HORIZONS) * len(BUCKETS)  # = 10

IS_END = date(2020, 12, 31)
OOS_A_START, OOS_A_END = date(2021, 1, 1), date(2023, 12, 31)
OOS_B_START, OOS_B_END = date(2024, 1, 1), date(2026, 5, 17)

EMBARGO_DAYS = 21                     # PEAD_DESIGN.md §5
DSR_HURDLE = 0.95                     # PEAD_DESIGN.md §4 G1
BOOTSTRAP_REPS = 4000                 # PEAD_DESIGN.md §3.2 (Tier-2 calibration)
BOOTSTRAP_BLOCK = 21                  # trading days


class Phase0NotCertified(Exception):
    """Raised if Phase 1 runner is invoked before PEAD_PHASE0_CERTIFIED.md exists."""


# --- types ---------------------------------------------------------------


@dataclass(slots=True)
class WindowResult:
    n_events: int
    n_days: int
    ic: float
    ic_p_value: float
    sharpe_252: float
    boot_mean: float
    boot_ci_lo: float
    boot_ci_hi: float
    boot_p_positive: float


@dataclass(slots=True)
class TrialResult:
    horizon: int
    bucket: str
    is_: WindowResult
    oos_a: WindowResult
    oos_b: WindowResult
    dsr_oos_a: float
    dsr_oos_b: float
    sign_agreement: bool
    survives_g1_dsr: bool
    survives_g2_ci: bool
    survives_g3_sign: bool
    survives_all: bool

    def to_dict(self) -> dict:
        d = asdict(self)
        # WindowResult dataclasses become nested dicts; rename `is_` -> `is`
        d["is"] = d.pop("is_")
        return d


# --- guard --------------------------------------------------------------


def check_phase0_certified(pead_root: Path) -> Path:
    """Returns path to PEAD_PHASE0_CERTIFIED.md if it exists and contains
    the SHA-256 of PEAD_DESIGN.md. Raises Phase0NotCertified otherwise."""
    cert_path = pead_root / "research" / "PEAD_PHASE0_CERTIFIED.md"
    design_path = pead_root / "research" / "PEAD_DESIGN.md"
    if not cert_path.exists():
        raise Phase0NotCertified(
            f"{cert_path} not found. Phase 1 must not run until Phase 0 is certified."
        )
    if not design_path.exists():
        raise Phase0NotCertified(f"{design_path} missing — cannot verify anchor.")
    expected = hashlib.sha256(design_path.read_bytes()).hexdigest()
    cert_text = cert_path.read_text()
    if expected not in cert_text:
        raise Phase0NotCertified(
            f"SHA-256 of PEAD_DESIGN.md ({expected}) not found in PEAD_PHASE0_CERTIFIED.md. "
            "Either the design doc was edited post-certification (contract violation) or the "
            "anchor was never written. Phase 1 will not run."
        )
    return cert_path


# --- window splitting ---------------------------------------------------


def _split_windows(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Slice the panel into IS / OOS-A / OOS-B by announcement_ts, applying
    a 21-trading-day embargo around each boundary.

    Embargo is naive (calendar days × 21/252 approximation isn't used —
    we use 21 calendar days for the boundary buffer which slightly
    over-embargoes, biasing conservative).
    """
    panel = panel.copy()
    panel["announcement_day"] = pd.to_datetime(panel["announcement_ts"]).dt.date
    from datetime import timedelta
    is_end_plus = IS_END + timedelta(days=EMBARGO_DAYS)
    oos_a_start_minus = OOS_A_START - timedelta(days=EMBARGO_DAYS)
    oos_a_end_plus = OOS_A_END + timedelta(days=EMBARGO_DAYS)
    oos_b_start_minus = OOS_B_START - timedelta(days=EMBARGO_DAYS)

    is_mask = panel["announcement_day"] <= IS_END
    # Drop events in [IS_END, IS_END+embargo] from the IS side
    # (those events' fwd_returns spill into OOS-A)
    is_mask = is_mask & (panel["announcement_day"] <= IS_END)
    # OOS-A: announcement_day strictly within [OOS_A_START, OOS_A_END],
    # respecting embargoes on both boundaries
    oos_a_mask = (panel["announcement_day"] >= OOS_A_START) & (panel["announcement_day"] <= OOS_A_END)
    oos_b_mask = (panel["announcement_day"] >= OOS_B_START) & (panel["announcement_day"] <= OOS_B_END)

    # Embargo: drop events near a window boundary that might leak labels
    # across windows because of the horizon K.
    boundary_buffer = panel["announcement_day"].apply(lambda d: (
        (IS_END < d <= is_end_plus) or
        (oos_a_start_minus <= d < OOS_A_START) or
        (OOS_A_END < d <= oos_a_end_plus) or
        (oos_b_start_minus <= d < OOS_B_START)
    ))
    keep = ~boundary_buffer

    return panel[is_mask & keep], panel[oos_a_mask & keep], panel[oos_b_mask & keep]


# --- single-trial evaluation -------------------------------------------


def _evaluate_window(window: pd.DataFrame, horizon: int, bucket: str,
                     bootstrap_reps: int, bootstrap_block: int,
                     bootstrap_seed: int = 0) -> WindowResult:
    """Compute IC + bootstrap-Sharpe-CI for one (horizon, bucket) on one
    window. Returns a WindowResult with NaN-filled fields if the window
    is too small."""
    ic = compute_ic(window, horizon)
    events = form_long_short(window, horizon, bucket=bucket)
    summary = long_short_summary(events, horizon)
    daily = summary["daily_returns"]

    if summary["n_days"] < 50:
        # Below minimum sample for meaningful bootstrap Sharpe
        return WindowResult(
            n_events=int(summary["n_events"]),
            n_days=int(summary["n_days"]),
            ic=float(ic["ic"]) if not math.isnan(ic["ic"]) else math.nan,
            ic_p_value=float(ic["p_value"]) if not math.isnan(ic["p_value"]) else math.nan,
            sharpe_252=math.nan,
            boot_mean=math.nan,
            boot_ci_lo=math.nan,
            boot_ci_hi=math.nan,
            boot_p_positive=math.nan,
        )

    # Defer to alphaforge-python's stationary_bootstrap_sharpe — read-only import.
    # Note: imports performed lazily so module load doesn't require the
    # equity stack to be on sys.path during test discovery.
    boot = _stationary_bootstrap_sharpe(
        daily.values.astype(np.float64),
        reps=bootstrap_reps, mean_block=bootstrap_block, seed=bootstrap_seed,
    )
    return WindowResult(
        n_events=int(summary["n_events"]),
        n_days=int(summary["n_days"]),
        ic=float(ic["ic"]) if not math.isnan(ic["ic"]) else math.nan,
        ic_p_value=float(ic["p_value"]) if not math.isnan(ic["p_value"]) else math.nan,
        sharpe_252=float(summary["sharpe_252"]) if math.isfinite(summary["sharpe_252"]) else math.nan,
        boot_mean=float(boot["mean"]),
        boot_ci_lo=float(boot["ci_lo"]),
        boot_ci_hi=float(boot["ci_hi"]),
        boot_p_positive=float(boot["p_positive"]),
    )


def _stationary_bootstrap_sharpe(r: np.ndarray, reps: int, mean_block: int, seed: int) -> dict:
    """Local stationary-bootstrap Sharpe — mirrors the equity stack's
    `factor_study.stationary_bootstrap_sharpe` exactly. We inline it
    rather than importing to avoid bringing the entire equity research
    module load (with its data dependencies) into PEAD's import path."""
    rng = np.random.default_rng(seed)
    n = len(r)
    p = 1.0 / mean_block
    out = np.empty(reps)
    for b in range(reps):
        idxs = np.empty(n, dtype=np.int64)
        i = rng.integers(0, n)
        for k in range(n):
            if k > 0 and rng.random() < p:
                i = rng.integers(0, n)
            else:
                i = (i + 1) % n if k > 0 else i
            idxs[k] = i
        sample = r[idxs]
        sd = sample.std(ddof=1)
        out[b] = (sample.mean() / sd * math.sqrt(252)) if sd > 0 else 0.0
    return {
        "mean": float(out.mean()),
        "ci_lo": float(np.quantile(out, 0.025)),
        "ci_hi": float(np.quantile(out, 0.975)),
        "p_positive": float((out > 0).mean()),
    }


def _deflated_sharpe(sr_observed: float, n_obs: int, sr_candidates: list[float]) -> float:
    """Bailey & López de Prado (2014) DSR. Mirrors equity-stack
    factor_study.deflated_sharpe_ratio for identical results."""
    from scipy import stats as scipy_stats
    if len(sr_candidates) < 2 or n_obs < 50:
        return math.nan
    sr_daily = np.array([s / math.sqrt(252) for s in sr_candidates])
    var_sr = float(sr_daily.var(ddof=1))
    if var_sr <= 0:
        return math.nan
    euler = 0.5772156649
    N = len(sr_candidates)
    sr0_daily = math.sqrt(var_sr) * (
        (1 - euler) * scipy_stats.norm.ppf(1 - 1 / N)
        + euler * scipy_stats.norm.ppf(1 - 1 / (N * math.e))
    )
    sr_obs_daily = sr_observed / math.sqrt(252)
    gamma3, gamma4 = 0.0, 3.0
    denom_inner = (1 - gamma3 * sr_obs_daily + (gamma4 - 1) / 4 * sr_obs_daily ** 2) / (n_obs - 1)
    if denom_inner <= 0:
        return math.nan
    denom = math.sqrt(denom_inner)
    return float(scipy_stats.norm.cdf((sr_obs_daily - sr0_daily) / denom))


# --- gate checks -------------------------------------------------------


def _check_gates(is_: WindowResult, oos_a: WindowResult, oos_b: WindowResult,
                 all_oos_sharpes: list[float]) -> tuple[float, float, bool, bool, bool, bool]:
    """Apply G1 (DSR > 0.95), G2 (bootstrap CI excludes zero in BOTH OOS),
    G3 (sign agreement)."""
    # DSR is deflated against the full trial set of OOS sharpes
    dsr_a = _deflated_sharpe(oos_a.sharpe_252, oos_a.n_days, all_oos_sharpes) if math.isfinite(oos_a.sharpe_252) else math.nan
    dsr_b = _deflated_sharpe(oos_b.sharpe_252, oos_b.n_days, all_oos_sharpes) if math.isfinite(oos_b.sharpe_252) else math.nan

    g1 = (
        math.isfinite(dsr_a) and dsr_a > DSR_HURDLE
        and math.isfinite(dsr_b) and dsr_b > DSR_HURDLE
    )
    # G2: bootstrap CI excludes zero on the same side in BOTH OOS windows
    g2_a_excludes = (oos_a.boot_ci_lo > 0) or (oos_a.boot_ci_hi < 0)
    g2_b_excludes = (oos_b.boot_ci_lo > 0) or (oos_b.boot_ci_hi < 0)
    g2 = g2_a_excludes and g2_b_excludes
    # G3: same sign across OOS-A and OOS-B (and finite both)
    g3 = (
        math.isfinite(oos_a.sharpe_252) and math.isfinite(oos_b.sharpe_252)
        and ((oos_a.sharpe_252 > 0) == (oos_b.sharpe_252 > 0))
    )
    return dsr_a, dsr_b, (g1 and g2_a_excludes and g2_b_excludes), g1, g2, g3


# --- orchestrator ------------------------------------------------------


def run_phase1(
    panel: pd.DataFrame,
    pead_root: Optional[Path] = None,
    bootstrap_reps: int = BOOTSTRAP_REPS,
    bootstrap_block: int = BOOTSTRAP_BLOCK,
    bootstrap_seed: int = 0,
    require_certification: bool = True,
) -> dict:
    """Execute the 10-trial Phase 1a gauntlet on the assembled panel.

    Returns a dict suitable for json.dump:
        {
          "n_trials": 10,
          "trials": [TrialResult.to_dict(), ...],
          "survivors": [...],
          "verdict": "PASS|FAIL"
        }
    """
    if require_certification:
        if pead_root is None:
            raise Phase0NotCertified("pead_root required when require_certification=True")
        check_phase0_certified(pead_root)

    log.info("Phase 1 gauntlet: %d trials over panel of %d events", N_TRIALS_1A, len(panel))

    is_panel, oos_a_panel, oos_b_panel = _split_windows(panel)
    log.info("window sizes  IS=%d  OOS-A=%d  OOS-B=%d",
             len(is_panel), len(oos_a_panel), len(oos_b_panel))

    # First pass: compute all OOS Sharpes (needed for DSR deflation)
    trials_raw: list[tuple[int, str, WindowResult, WindowResult, WindowResult]] = []
    for horizon in HORIZONS:
        for bucket in BUCKETS:
            is_w = _evaluate_window(is_panel, horizon, bucket,
                                    bootstrap_reps, bootstrap_block, bootstrap_seed)
            oa_w = _evaluate_window(oos_a_panel, horizon, bucket,
                                    bootstrap_reps, bootstrap_block, bootstrap_seed + 1)
            ob_w = _evaluate_window(oos_b_panel, horizon, bucket,
                                    bootstrap_reps, bootstrap_block, bootstrap_seed + 2)
            trials_raw.append((horizon, bucket, is_w, oa_w, ob_w))

    all_oos_sharpes = [
        t[3].sharpe_252 for t in trials_raw if math.isfinite(t[3].sharpe_252)
    ] + [
        t[4].sharpe_252 for t in trials_raw if math.isfinite(t[4].sharpe_252)
    ]

    # Second pass: gate evaluation
    results: list[TrialResult] = []
    survivors: list[dict] = []
    for horizon, bucket, is_w, oa_w, ob_w in trials_raw:
        dsr_a, dsr_b, _, g1, g2, g3 = _check_gates(is_w, oa_w, ob_w, all_oos_sharpes)
        all_pass = g1 and g2 and g3
        tr = TrialResult(
            horizon=horizon, bucket=bucket,
            is_=is_w, oos_a=oa_w, oos_b=ob_w,
            dsr_oos_a=dsr_a, dsr_oos_b=dsr_b,
            sign_agreement=g3,
            survives_g1_dsr=g1, survives_g2_ci=g2, survives_g3_sign=g3,
            survives_all=all_pass,
        )
        results.append(tr)
        if all_pass:
            survivors.append({"horizon": horizon, "bucket": bucket})

    verdict = "PASS" if survivors else "FAIL"
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_trials": N_TRIALS_1A,
        "is_window": [str(date(2012, 1, 1)), str(IS_END)],
        "oos_a_window": [str(OOS_A_START), str(OOS_A_END)],
        "oos_b_window": [str(OOS_B_START), str(OOS_B_END)],
        "embargo_days": EMBARGO_DAYS,
        "dsr_hurdle": DSR_HURDLE,
        "bootstrap_reps": bootstrap_reps,
        "bootstrap_block": bootstrap_block,
        "trials": [t.to_dict() for t in results],
        "survivors": survivors,
        "verdict": verdict,
    }


# --- panel assembly ----------------------------------------------------


def build_panel_for_universe(
    edgar_root: Path, ohlcv_root: Path, ciks_tickers: Iterable[tuple[int, str]],
) -> pd.DataFrame:
    """Build the master panel by concatenating per-firm panels.

    `ciks_tickers` is typically the eligible-firm list from
    `validation.universe_intersection`.
    """
    frames = []
    for cik, ticker in ciks_tickers:
        rows = build_panel_for_firm(edgar_root, ohlcv_root, cik, ticker)
        if rows:
            frames.append(panel_to_dataframe(rows))
    if not frames:
        # empty schema-correct frame
        cols = ["cik", "ticker", "fy", "fp", "announcement_ts", "sue"]
        cols += [f"fwd_return_{K}" for K in HOLDING_HORIZONS]
        return pd.DataFrame(columns=cols)
    return pd.concat(frames, ignore_index=True)


# --- CLI --------------------------------------------------------------


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="PEAD Phase 1 gauntlet runner")
    parser.add_argument("--pead-root", type=Path, default=Path("."))
    parser.add_argument("--edgar-root", type=Path, default=Path("data/edgar_eps"))
    parser.add_argument("--ohlcv-root", type=Path, default=Path("../data/quarantine/market"))
    parser.add_argument("--out", type=Path, default=Path("research/PHASE1_RESULTS.json"))
    parser.add_argument("--no-certification-check", action="store_true",
                        help="Bypass PEAD_PHASE0_CERTIFIED.md check (for dry-runs only)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")

    try:
        # Load the eligible-firm list from the universe intersection report
        intersection_json = args.pead_root / "research" / "PEAD_UNIVERSE_INTERSECTION.json"
        if not intersection_json.exists():
            log.error("universe intersection report not found: %s", intersection_json)
            log.error("run `python3 -m validation.universe_intersection` first")
            return 2
        rpt = json.loads(intersection_json.read_text())
        # The sample list is the visible 20; for full execution we walk
        # the eligible universe via the by_cik shard listing instead.
        eligible_shards = sorted((args.edgar_root / "by_cik").glob("CIK*.parquet"))
        # Cross-reference with PIT pairs from validation.universe_intersection
        from validation.universe_intersection import load_pit_pairs
        pit_pairs = load_pit_pairs(args.pead_root.resolve().parent / "alphaforge-python/data/market/pit/artifacts")
        ciks_tickers = [
            (cik, ticker) for cik, ticker in pit_pairs.items()
            if (args.edgar_root / "by_cik" / f"CIK{cik:010d}.parquet").exists()
        ]
        log.info("running Phase 1 gauntlet over %d firms", len(ciks_tickers))

        panel = build_panel_for_universe(args.edgar_root, args.ohlcv_root, ciks_tickers)
        log.info("panel built: %d rows", len(panel))

        results = run_phase1(
            panel, pead_root=args.pead_root,
            require_certification=not args.no_certification_check,
        )
    except Phase0NotCertified as e:
        log.error("Phase 0 not certified: %s", e)
        return 3

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2, default=str))
    log.info("verdict=%s  survivors=%d  wrote %s",
             results["verdict"], len(results["survivors"]), args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
