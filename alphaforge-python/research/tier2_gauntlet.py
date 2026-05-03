"""Tier 2 Phase 2 — gauntlet runner for the 8 pre-committed MV-class strategies.

Per TIER2_DESIGN.md §3 + §5, runs the lower-turnover gauntlet on:

  1. MV-63              63d rebalance, vanilla
  2. MV-126             126d rebalance, vanilla
  3. MV-63-volcap       63d  + target portfolio vol = 8% annualized
  4. MV-126-volcap      126d + target portfolio vol = 8% annualized
  5. MV-63-shrunk       63d  + force Ledoit-Wolf δ ≥ 0.5
  6. MV-126-shrunk      126d + force Ledoit-Wolf δ ≥ 0.5
  7. MV-63-ext          63d  on extended history (2010-2025)
  8. MV-126-ext         126d on extended history (2010-2025)

For each strategy: build per-factor LS net return series at the strategy's
rebalance horizon, solve MV weights on the training window with the
strategy's variant, freeze weights, apply OOS, compute per-OOS-window
FF5+UMD alpha residuals (4000 bootstrap reps, sector-neutral defaults
applied to the underlying factor panels per the Phase 5 baseline).

Outputs:
  research/out/tier2/tier2_phase2_results.json
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

THIS_DIR = Path(__file__).resolve().parent
PROJECT_DIR = THIS_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from research.factor_study import (
    BOOT_BLOCKS, OOS_WINDOWS,
    load_panel, load_sector_map, build_factor_panels, sector_neutralize,
    prepare_analysis_returns, quintile_backtest_from_returns,
    ann_sharpe, ann_return, max_drawdown, stationary_bootstrap_sharpe,
    slice_metrics,
)
from research.phase5_combine import ledoit_wolf_cov
from research.portfolio_alpha import slice_portfolio_alpha_per_window

OUT_DIR = THIS_DIR / "out" / "tier2"
OUT_DIR.mkdir(parents=True, exist_ok=True)

TRAIN_START_TIER1 = "2016-01-04"
TRAIN_START_EXT   = "2010-01-04"
TRAIN_END         = "2021-12-31"
BOOT_REPS_T2      = 4000  # vs Tier 1's 2000

# Vol-cap and shrinkage knobs
VOLCAP_TARGET_ANNUAL = 0.08
SHRUNK_MIN_DELTA     = 0.5

# 8 pre-committed strategies (locked per TIER2_DESIGN.md §3).
# Each entry: (name, rebalance_days, training_start, variant_kwargs)
STRATEGIES: List[Tuple[str, int, str, Dict[str, object]]] = [
    ("MV-63",         63,  TRAIN_START_TIER1, {}),
    ("MV-126",        126, TRAIN_START_TIER1, {}),
    ("MV-63-volcap",  63,  TRAIN_START_TIER1, {"volcap": True}),
    ("MV-126-volcap", 126, TRAIN_START_TIER1, {"volcap": True}),
    ("MV-63-shrunk",  63,  TRAIN_START_TIER1, {"min_delta": SHRUNK_MIN_DELTA}),
    ("MV-126-shrunk", 126, TRAIN_START_TIER1, {"min_delta": SHRUNK_MIN_DELTA}),
    ("MV-63-ext",     63,  TRAIN_START_EXT,   {}),
    ("MV-126-ext",    126, TRAIN_START_EXT,   {}),
]


def ledoit_wolf_cov_with_min_delta(X: np.ndarray, min_delta: float = 0.0) -> np.ndarray:
    """Same as ledoit_wolf_cov but enforces a floor on the shrinkage intensity."""
    T, N = X.shape
    Xc = X - X.mean(axis=0, keepdims=True)
    S = (Xc.T @ Xc) / max(T - 1, 1)
    mu = np.trace(S) / N
    F = mu * np.eye(N)
    d2 = np.sum((S - F) ** 2)
    b2 = 0.0
    for t in range(T):
        xt = Xc[t:t + 1]
        b2 += np.sum((xt.T @ xt - S) ** 2)
    b2 = min(b2 / T**2, d2)
    delta = b2 / d2 if d2 > 0 else 0.0
    delta = max(delta, min_delta)
    return delta * F + (1 - delta) * S


def mv_weights(returns: pd.DataFrame, train_start: str, train_end: str,
               *, min_delta: float = 0.0) -> pd.Series:
    train = returns.loc[train_start:train_end].dropna(how="any")
    X = train.to_numpy()
    if X.shape[0] < 30:
        return pd.Series(np.zeros(returns.shape[1]), index=returns.columns)
    mu = X.mean(axis=0)
    Sigma = ledoit_wolf_cov_with_min_delta(X, min_delta=min_delta)
    Sigma += 1e-8 * np.eye(Sigma.shape[0])
    w_raw = np.linalg.solve(Sigma, mu)
    gross = np.sum(np.abs(w_raw))
    w = w_raw / gross if gross > 1e-12 else np.zeros_like(w_raw)
    return pd.Series(w, index=returns.columns)


def apply_volcap(net: pd.Series, target_annual: float, train_start: str,
                 train_end: str) -> pd.Series:
    """Scale the strategy's daily returns so realized training-window vol
    matches `target_annual`. Frozen scalar applied OOS."""
    train = net.loc[train_start:train_end].dropna()
    if len(train) < 30 or train.std(ddof=1) <= 1e-12:
        return net
    train_vol_annual = train.std(ddof=1) * np.sqrt(252)
    scalar = target_annual / train_vol_annual
    return net * scalar


def per_factor_net_at_horizon(neutral_factors: Dict[str, pd.DataFrame],
                              analysis_returns: pd.DataFrame,
                              rebalance: int) -> pd.DataFrame:
    nets: Dict[str, pd.Series] = {}
    for name, panel in neutral_factors.items():
        bt = quintile_backtest_from_returns(panel, analysis_returns,
                                             holding_period=rebalance)
        nets[name] = bt["long_short_net"]
    return pd.DataFrame(nets).dropna(how="any")


def per_window_metrics(net: pd.Series, ref: pd.DataFrame) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    alpha_per_win = slice_portfolio_alpha_per_window(
        net, ref, OOS_WINDOWS,
        bootstrap_reps=BOOT_REPS_T2, bootstrap_block=BOOT_BLOCKS,
    )
    for win, start, end in OOS_WINDOWS:
        sub = net.loc[start:end]
        if len(sub) < 21:
            out[win] = {"start": start, "end": end, "n_days": int(len(sub)),
                        "skipped": "too few observations"}
            continue
        boot = stationary_bootstrap_sharpe(sub.to_numpy(dtype=np.float64),
                                            reps=BOOT_REPS_T2,
                                            mean_block=BOOT_BLOCKS, seed=0)
        entry = {
            "start": start, "end": end, "n_days": int(len(sub)),
            **slice_metrics(sub),
            "bootstrap_sharpe_mean": boot["mean"],
            "bootstrap_sharpe_ci_lo": boot["ci_lo"],
            "bootstrap_sharpe_ci_hi": boot["ci_hi"],
            "bootstrap_p_positive": boot["p_positive"],
        }
        ap = alpha_per_win.get(win)
        if ap and not ap.get("skipped"):
            entry["ff5_alpha"] = {
                "alpha_annual": ap["alpha_annual"],
                "alpha_t": ap["alpha_t"],
                "alpha_p_two_sided": ap["alpha_p_two_sided"],
                "r_squared": ap["r_squared"],
                "residual_sharpe": ap["residual_sharpe"],
                "residual_sharpe_ci_lo": ap["residual_sharpe_ci_lo"],
                "residual_sharpe_ci_hi": ap["residual_sharpe_ci_hi"],
                "residual_p_positive": ap["residual_p_positive"],
                "n_obs": ap["n_obs"],
            }
        out[win] = entry
    return out


def main() -> int:
    t0 = time.time()
    print(f"[{time.time()-t0:6.1f}s] Loading PIT close + volume panels...")
    close, volume = load_panel()
    sector_map = load_sector_map(list(close.columns))
    print(f"          baseline universe: {close.shape[1]} tickers, "
          f"{close.shape[0]} days")

    print(f"[{time.time()-t0:6.1f}s] Building factor panels (9 factors)...")
    raw_factors = build_factor_panels(close, volume)
    print(f"[{time.time()-t0:6.1f}s] Sector-neutralizing factor panels "
          f"(default per Phase 2 mitigation #1)...")
    neutral_factors = {n: sector_neutralize(p, sector_map)
                       for n, p in raw_factors.items()}

    print(f"[{time.time()-t0:6.1f}s] Loading analysis returns + reference factors...")
    import os
    os.environ.setdefault("ALPHAFORGE_FACTOR_STUDY_RESIDUALIZE", "1")
    os.environ.setdefault("ALPHAFORGE_REFERENCE_FACTORS",
                          "research/out/phase3_reference_staged.csv")
    # Reload prepare_analysis_returns to pick up env vars
    import importlib
    import research.factor_study as fs
    importlib.reload(fs)
    analysis_returns, ref = fs.prepare_analysis_returns(close)
    if ref is None:
        print("ERROR: reference factors not loaded; cannot compute alpha.",
              file=sys.stderr)
        return 2

    summaries: Dict[str, dict] = {}

    for name, rebalance, train_start, variant in STRATEGIES:
        print(f"[{time.time()-t0:6.1f}s] === {name} (rebalance={rebalance}d, "
              f"train_start={train_start}, variant={variant}) ===")

        # 1. Per-factor LS net at this strategy's rebalance horizon
        factor_returns = per_factor_net_at_horizon(neutral_factors,
                                                    analysis_returns, rebalance)
        if factor_returns.empty:
            print(f"          SKIPPED — empty factor return panel")
            continue
        n_train = len(factor_returns.loc[train_start:TRAIN_END])
        if n_train < 30:
            print(f"          SKIPPED — insufficient training data "
                  f"({n_train} days)")
            continue

        # 2. MV weights with strategy variant
        min_delta = float(variant.get("min_delta", 0.0))
        w = mv_weights(factor_returns, train_start, TRAIN_END,
                       min_delta=min_delta)
        print(f"          MV weights gross-leverage = {w.abs().sum():.4f}")

        # 3. Apply weights OOS
        net = (factor_returns * w).sum(axis=1)

        # 4. Vol-cap variant: scale by frozen training-window vol scalar
        if variant.get("volcap"):
            net = apply_volcap(net, VOLCAP_TARGET_ANNUAL,
                               train_start, TRAIN_END)
            print(f"          Vol-capped to target {VOLCAP_TARGET_ANNUAL:.1%} annual")

        # 5. Per-window metrics + FF5+UMD alpha residuals
        wm = per_window_metrics(net, ref)

        full_sr = ann_sharpe(net)
        oos_a_sr = wm.get("OOS-A", {}).get("sharpe", float("nan"))
        oos_b_sr = wm.get("OOS-B", {}).get("sharpe", float("nan"))
        oos_a_alpha = wm.get("OOS-A", {}).get("ff5_alpha", {}).get("residual_sharpe", float("nan"))
        oos_b_alpha = wm.get("OOS-B", {}).get("ff5_alpha", {}).get("residual_sharpe", float("nan"))
        print(f"          full SR={full_sr:+.2f}  OOS-A raw={oos_a_sr:+.2f} "
              f"alpha={oos_a_alpha:+.2f}  OOS-B raw={oos_b_sr:+.2f} "
              f"alpha={oos_b_alpha:+.2f}")

        summaries[name] = {
            "config": {
                "rebalance_days": rebalance,
                "train_start": train_start,
                "train_end": TRAIN_END,
                "variant": variant,
            },
            "mv_weights": w.to_dict(),
            "full_period": {
                "sharpe": full_sr,
                "ann_return": ann_return(net),
                "max_drawdown": max_drawdown(net),
                "n_days": int(len(net)),
            },
            "oos_windows": wm,
        }

    out = {
        "config": {
            "tier": 2,
            "phase": 2,
            "n_strategies": len(summaries),
            "bootstrap_reps": BOOT_REPS_T2,
            "bootstrap_block": BOOT_BLOCKS,
            "train_end": TRAIN_END,
            "oos_windows": [{"name": n, "start": s, "end": e}
                            for n, s, e in OOS_WINDOWS],
            "sector_neutral_default": True,
            "vol_target_annual": VOLCAP_TARGET_ANNUAL,
            "shrunk_min_delta": SHRUNK_MIN_DELTA,
        },
        "strategies": summaries,
    }

    out_path = OUT_DIR / "tier2_phase2_results.json"
    out_path.write_text(json.dumps(out, indent=2, default=float))
    print(f"[{time.time()-t0:6.1f}s] Wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
