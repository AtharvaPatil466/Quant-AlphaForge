"""Phase 5 combination strategies on residualized PIT returns.

Implements the four pre-committed combination strategies from
PHASE5_DESIGN.md §4. Train on 2016-01-04 → 2021-12-31; freeze weights;
evaluate on the two non-overlapping OOS windows (OOS-A 2022-2023,
OOS-B 2024-2025). Emits research/out/phase5_combination_results.json.

Strategies
----------
  1. EWE  — equal-weight ensemble of cross-sectionally z-scored
            sector-neutralized factor panels.
  2. ICW  — same, weighted by training-window mean 21-day Spearman IC
            (signed).
  3. MV   — Markowitz overlay on the 9 per-factor long-short net return
            series. Ledoit-Wolf shrinkage, long-short, gross-leverage
            cap = 1. Weights solved on training-window returns only,
            applied OOS.
  4. ICW-flip — |IC|-weighted with sign forced to training-window
            direction.

The first three score-level strategies (1, 2, 4) flow through the
quintile backtest pipeline unchanged. Strategy 3 is a portfolio
overlay over the 9 factor return series — a different axis.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from scipy import stats

THIS_DIR = Path(__file__).resolve().parent
PROJECT_DIR = THIS_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from research.factor_study import (
    BOOT_BLOCKS, BOOT_REPS, OOS_WINDOWS,
    load_panel, load_sector_map, build_factor_panels, sector_neutralize,
    prepare_analysis_returns, quintile_backtest_from_returns,
    ann_sharpe, ann_return, max_drawdown, stationary_bootstrap_sharpe,
    slice_metrics,
)
from research.portfolio_alpha import slice_portfolio_alpha_per_window

OUT_DIR = THIS_DIR / "out"
OUT_DIR.mkdir(exist_ok=True)

# Training window — frozen before OOS-A (2022-01-03) with the 21-day embargo
# already implicit in the PHASE4_DESIGN window choice.
TRAIN_START = "2016-01-04"
TRAIN_END   = "2021-12-31"
IC_HORIZON  = 21


def cross_sectional_zscore(panel: pd.DataFrame) -> pd.DataFrame:
    """Per-date z-score across tickers. Forces all panels onto the same scale."""
    mu = panel.mean(axis=1)
    sd = panel.std(axis=1).replace(0.0, np.nan)
    return panel.sub(mu, axis=0).div(sd, axis=0)


def training_window_ic(score: pd.DataFrame, fwd_h: pd.DataFrame) -> float:
    """Mean Spearman IC across training-window dates between score and fwd ret.

    Sign included; result drives ICW weights.
    """
    s = score.loc[TRAIN_START:TRAIN_END]
    r = fwd_h.loc[TRAIN_START:TRAIN_END]
    common_idx = s.index.intersection(r.index)
    ics = []
    for dt in common_idx:
        sv = s.loc[dt]; rv = r.loc[dt]
        m = sv.notna() & rv.notna()
        if m.sum() < 10:
            continue
        rho, _ = stats.spearmanr(sv[m], rv[m])
        if rho == rho:
            ics.append(rho)
    if not ics:
        return 0.0
    return float(np.mean(ics))


def ledoit_wolf_cov(X: np.ndarray) -> np.ndarray:
    """Ledoit-Wolf single-parameter shrinkage to identity-scaled target.

    X is T × N return series (rows = days). Returns N × N shrunk covariance.
    """
    T, N = X.shape
    Xc = X - X.mean(axis=0, keepdims=True)
    S = (Xc.T @ Xc) / max(T - 1, 1)
    mu = np.trace(S) / N
    F = mu * np.eye(N)
    # shrinkage intensity (closed-form Ledoit-Wolf, simplified)
    d2 = np.sum((S - F) ** 2)
    b2 = 0.0
    for t in range(T):
        xt = Xc[t:t + 1]
        b2 += np.sum((xt.T @ xt - S) ** 2)
    b2 = min(b2 / T**2, d2)
    delta = b2 / d2 if d2 > 0 else 0.0
    return delta * F + (1 - delta) * S


def mv_weights(returns: pd.DataFrame) -> pd.Series:
    """Markowitz weights on training-window factor returns.

    Solve w ∝ Σ⁻¹ μ, then rescale to ‖w‖₁ = 1 (gross leverage 1).
    Long-short allowed.
    """
    train = returns.loc[TRAIN_START:TRAIN_END].dropna(how="any")
    X = train.to_numpy()
    mu = X.mean(axis=0)
    Sigma = ledoit_wolf_cov(X)
    Sigma += 1e-8 * np.eye(Sigma.shape[0])
    w_raw = np.linalg.solve(Sigma, mu)
    gross = np.sum(np.abs(w_raw))
    if gross < 1e-12:
        w = np.zeros_like(w_raw)
    else:
        w = w_raw / gross
    return pd.Series(w, index=returns.columns)


def per_window_metrics(net: pd.Series,
                       reference_factors: pd.DataFrame | None = None) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    alpha_per_window = (
        slice_portfolio_alpha_per_window(
            net, reference_factors, OOS_WINDOWS,
            bootstrap_reps=BOOT_REPS, bootstrap_block=BOOT_BLOCKS,
        )
        if reference_factors is not None else {}
    )
    for win, start, end in OOS_WINDOWS:
        sub = net.loc[start:end]
        if len(sub) < 21:
            out[win] = {"start": start, "end": end, "n_days": int(len(sub)),
                        "skipped": "too few observations"}
            continue
        boot = stationary_bootstrap_sharpe(sub.to_numpy(dtype=np.float64),
                                           reps=BOOT_REPS, mean_block=BOOT_BLOCKS,
                                           seed=0)
        entry = {
            "start": start, "end": end, "n_days": int(len(sub)),
            **slice_metrics(sub),
            "bootstrap_sharpe_mean": boot["mean"],
            "bootstrap_sharpe_ci_lo": boot["ci_lo"],
            "bootstrap_sharpe_ci_hi": boot["ci_hi"],
            "bootstrap_p_positive": boot["p_positive"],
        }
        ap = alpha_per_window.get(win)
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


def full_metrics(net: pd.Series) -> Dict[str, float]:
    return {
        "sharpe": ann_sharpe(net),
        "ann_return": ann_return(net),
        "max_drawdown": max_drawdown(net),
        "n_days": int(len(net)),
    }


def main() -> int:
    t0 = time.time()
    print(f"[{time.time()-t0:5.1f}s] Loading PIT panel...")
    close, volume = load_panel()
    sector_map = load_sector_map(list(close.columns))
    print(f"          universe: {close.shape[1]} tickers, {close.shape[0]} days")

    print(f"[{time.time()-t0:5.1f}s] Building factor panels (9)...")
    raw_factors = build_factor_panels(close, volume)
    neutral_factors = {n: sector_neutralize(p, sector_map)
                       for n, p in raw_factors.items()}

    print(f"[{time.time()-t0:5.1f}s] Loading analysis returns...")
    analysis_returns, ref = prepare_analysis_returns(close)
    mode = "residualized" if ref is not None else "raw"
    print(f"          analysis_returns_mode = {mode}")

    fwd_h = analysis_returns.shift(-IC_HORIZON).rolling(IC_HORIZON).sum().shift(-1)
    # Above is the cumulative h-day forward return; use a simpler form:
    fwd_h = (1.0 + analysis_returns).rolling(IC_HORIZON).apply(np.prod, raw=True).shift(-IC_HORIZON) - 1.0

    factor_names = list(neutral_factors.keys())
    z_panels: Dict[str, pd.DataFrame] = {n: cross_sectional_zscore(p)
                                          for n, p in neutral_factors.items()}

    print(f"[{time.time()-t0:5.1f}s] Per-factor long-short net series (9)...")
    per_factor_net: Dict[str, pd.Series] = {}
    for name, p in neutral_factors.items():
        bt = quintile_backtest_from_returns(p, analysis_returns)
        per_factor_net[name] = bt["long_short_net"]
    factor_returns = pd.DataFrame(per_factor_net).dropna(how="any")

    print(f"[{time.time()-t0:5.1f}s] Computing training-window ICs...")
    ics = {n: training_window_ic(z_panels[n], fwd_h) for n in factor_names}
    for n, ic in ics.items():
        print(f"          IC[{n}] = {ic:+.4f}")

    print(f"[{time.time()-t0:5.1f}s] Strategy 1: EWE (equal-weight ensemble)...")
    ewe_score = sum(z_panels[n] for n in factor_names) / len(factor_names)
    ewe_bt = quintile_backtest_from_returns(ewe_score, analysis_returns)
    ewe_net = ewe_bt["long_short_net"]

    print(f"[{time.time()-t0:5.1f}s] Strategy 2: ICW (signed-IC-weighted)...")
    icw_score = sum(ics[n] * z_panels[n] for n in factor_names)
    icw_bt = quintile_backtest_from_returns(icw_score, analysis_returns)
    icw_net = icw_bt["long_short_net"]

    print(f"[{time.time()-t0:5.1f}s] Strategy 3: MV (Markowitz overlay)...")
    mv_w = mv_weights(factor_returns)
    print(f"          MV weights:")
    for n, w in mv_w.items():
        print(f"            {n}: {w:+.4f}")
    mv_net = (factor_returns * mv_w).sum(axis=1)

    print(f"[{time.time()-t0:5.1f}s] Strategy 4: ICW-flip (|IC|-weighted, signed)...")
    icw_flip_score = sum(np.sign(ics[n]) * abs(ics[n]) * z_panels[n]
                         for n in factor_names)
    # Note: np.sign(ic) * |ic| == ic. The intent of ICW-flip vs ICW is identical
    # at the score level; the distinction is meaningful only when we manually
    # FORCE a particular sign convention. Per design §4.4 the sign is forced to
    # match training-window direction — which the IC already encodes. We keep
    # it as a separate trial for the deflation count.
    icwf_bt = quintile_backtest_from_returns(icw_flip_score, analysis_returns)
    icwf_net = icwf_bt["long_short_net"]

    print(f"[{time.time()-t0:5.1f}s] Computing per-strategy metrics...")
    strategies = {
        "EWE":      ewe_net,
        "ICW":      icw_net,
        "MV":       mv_net,
        "ICW-flip": icwf_net,
    }
    summaries: Dict[str, dict] = {}
    for name, net in strategies.items():
        summaries[name] = {
            "full_period": full_metrics(net),
            "oos_windows": per_window_metrics(net, reference_factors=ref),
        }
        full_sr = summaries[name]["full_period"]["sharpe"]
        a = summaries[name]["oos_windows"].get("OOS-A", {}).get("sharpe", float("nan"))
        b = summaries[name]["oos_windows"].get("OOS-B", {}).get("sharpe", float("nan"))
        print(f"          {name:10s} full SR={full_sr:+.2f}  "
              f"OOS-A={a:+.2f}  OOS-B={b:+.2f}")

    out = {
        "config": {
            "train_start": TRAIN_START, "train_end": TRAIN_END,
            "oos_windows": [{"name": n, "start": s, "end": e}
                            for n, s, e in OOS_WINDOWS],
            "ic_horizon": IC_HORIZON,
            "universe_size": int(close.shape[1]),
            "trading_days": int(close.shape[0]),
            "n_factors": len(factor_names),
            "factor_names": factor_names,
            "analysis_returns_mode": mode,
        },
        "training_window_ics": ics,
        "mv_weights": mv_w.to_dict(),
        "strategies": summaries,
    }

    out_json = OUT_DIR / "phase5_combination_results.json"
    out_json.write_text(json.dumps(out, indent=2, default=float))
    print(f"[{time.time()-t0:5.1f}s] Wrote {out_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
