"""Core power-calibration machinery.

Method
------
1. Take a *real* daily-return series (SPY by default) as the noise substrate so
   the injected test inherits realistic volatility, fat tails and serial
   dependence. Demean it so the only signal is the one we inject.
2. For a target *true* annualized Sharpe S, build two OOS windows by
   stationary-block-bootstrapping the demeaned noise (preserving autocorrelation)
   and adding a constant drift d = S/√252 · σ_noise. The population Sharpe of the
   result is S; the *sample* Sharpe fluctuates around it — which is the whole
   point of a power study.
3. Run the canonical gauntlet's statistical gates on the two windows and record
   whether the strategy is "detected" (all detection gates pass).
4. Repeat M times → empirical power at S. Sweep S → power curve. The smallest S
   with power ≥ target (default 0.8) is the **minimum detectable effect (MDE)**.

The gates used are the *detection* gates — DSR > 0.95 (deflated against N
trials), bootstrap-CI excludes zero, and OOS sign agreement — in both windows.
Economic gates (cost survival, max drawdown) are substrate-specific and are not
part of the detection floor.

The bootstrap inside the CI gate is vectorized across replications for speed; it
is the statistical twin of ``afgauntlet.stationary_bootstrap_sharpe_ci`` (same
geometric-block scheme), not a bit-identical RNG stream.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass

import numpy as np

from afgauntlet import (annualized_sharpe, deflated_sharpe_ratio,
                        sample_excess_kurtosis, sample_skewness)

ANN = 252.0
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SPY = os.path.join(_REPO_ROOT, "alphaforge-vix", "data", "etps", "spy.parquet")


# ─── base noise ──────────────────────────────────────────────────────────────

def daily_log_returns(prices: np.ndarray) -> np.ndarray:
    p = np.asarray(prices, dtype=float)
    p = p[np.isfinite(p) & (p > 0)]
    return np.diff(np.log(p))


def load_base_returns(seed: int = 0) -> tuple[np.ndarray, str]:
    """Real SPY daily log-returns if available, else a fat-tailed fallback.

    Returns (returns, source_label). The fallback is a Student-t(ν=5) series at
    ~1%/day vol — clearly labelled so a reader never mistakes it for real data.
    """
    if os.path.exists(_SPY):
        try:
            import pandas as pd
            df = pd.read_parquet(_SPY)
            col = "adj_close" if "adj_close" in df.columns else "close"
            r = daily_log_returns(df[col].to_numpy())
            if r.size > 2000:
                return r, f"SPY adj_close ({r.size} days, real)"
        except Exception:
            pass
    rng = np.random.default_rng(seed)
    r = rng.standard_t(5, size=6000) * 0.01 / math.sqrt(5 / 3)  # ~1%/day vol
    return r, "Student-t(5) fallback (SYNTHETIC)"


# ─── injection ───────────────────────────────────────────────────────────────

def _block_bootstrap_path(noise: np.ndarray, n_obs: int, block: int,
                          rng: np.random.Generator) -> np.ndarray:
    """One stationary-bootstrap resample of `noise` of length `n_obs`."""
    n = noise.size
    p = 1.0 / block
    out = np.empty(n_obs)
    i = int(rng.integers(0, n))
    for t in range(n_obs):
        out[t] = noise[i]
        if rng.random() < p:
            i = int(rng.integers(0, n))
        else:
            i = (i + 1) % n
    return out


def inject_alpha(noise_path: np.ndarray, true_ann_sharpe: float,
                 noise_std: float, annualization: float = ANN) -> np.ndarray:
    """Add a constant drift so the population annualized Sharpe is
    `true_ann_sharpe`. `noise_std` is the daily std of the noise substrate."""
    drift = true_ann_sharpe / math.sqrt(annualization) * noise_std
    return noise_path + drift


# ─── vectorized bootstrap CI (detection-gate internal) ───────────────────────

def _bootstrap_excludes_zero(r: np.ndarray, reps: int, block: int,
                             rng: np.random.Generator,
                             confidence: float = 0.95) -> bool:
    n = r.size
    if n < block + 1:
        return False
    p = 1.0 / block
    pos = rng.integers(0, n, size=reps)
    idx = np.empty((reps, n), dtype=np.int64)
    idx[:, 0] = pos
    for t in range(1, n):
        jump = rng.random(reps) < p
        pos = np.where(jump, rng.integers(0, n, size=reps), (pos + 1) % n)
        idx[:, t] = pos
    samples = r[idx]
    mu = samples.mean(axis=1)
    sd = samples.std(axis=1, ddof=1)
    sharpes = np.where(sd > 0, mu / sd * math.sqrt(ANN), 0.0)
    alpha = 1.0 - confidence
    lo = np.quantile(sharpes, alpha / 2.0)
    hi = np.quantile(sharpes, 1.0 - alpha / 2.0)
    return bool(lo > 0 or hi < 0)


# ─── detection ───────────────────────────────────────────────────────────────

def _detect(win_a: np.ndarray, win_b: np.ndarray, n_trials: int,
            dsr_threshold: float, boot_reps: int, block: int,
            rng: np.random.Generator, use_bootstrap: bool) -> dict:
    out = {}
    sr_a, sr_b = annualized_sharpe(win_a), annualized_sharpe(win_b)
    dsr_a = deflated_sharpe_ratio(sr_a, n_trials, win_a.size,
                                  sample_skewness(win_a), sample_excess_kurtosis(win_a))
    dsr_b = deflated_sharpe_ratio(sr_b, n_trials, win_b.size,
                                  sample_skewness(win_b), sample_excess_kurtosis(win_b))
    out["dsr"] = (not math.isnan(dsr_a) and dsr_a > dsr_threshold
                  and not math.isnan(dsr_b) and dsr_b > dsr_threshold)
    out["sign"] = bool(sr_a > 0 and sr_b > 0)
    if use_bootstrap:
        out["bootstrap"] = (_bootstrap_excludes_zero(win_a, boot_reps, block, rng)
                            and _bootstrap_excludes_zero(win_b, boot_reps, block, rng))
    else:
        out["bootstrap"] = True
    out["detected"] = out["dsr"] and out["sign"] and out["bootstrap"]
    return out


# ─── power ───────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PowerPoint:
    true_sharpe: float
    power: float                 # overall detection rate
    gate_power: dict             # per-gate pass rate


def power_at(true_sharpe: float, noise: np.ndarray, n_obs: int, n_trials: int,
             n_mc: int = 300, block: int = 21, boot_reps: int = 300,
             dsr_threshold: float = 0.95, use_bootstrap: bool = True,
             seed: int = 0) -> PowerPoint:
    """Empirical detection power at a given true annualized Sharpe."""
    rng = np.random.default_rng(seed)
    demeaned = noise - noise.mean()
    noise_std = float(demeaned.std(ddof=1))
    tallies = {"detected": 0, "dsr": 0, "sign": 0, "bootstrap": 0}
    for _ in range(n_mc):
        a = inject_alpha(_block_bootstrap_path(demeaned, n_obs, block, rng),
                         true_sharpe, noise_std)
        b = inject_alpha(_block_bootstrap_path(demeaned, n_obs, block, rng),
                         true_sharpe, noise_std)
        res = _detect(a, b, n_trials, dsr_threshold, boot_reps, block, rng, use_bootstrap)
        for k in tallies:
            tallies[k] += int(res[k])
    return PowerPoint(
        true_sharpe=true_sharpe,
        power=tallies["detected"] / n_mc,
        gate_power={k: tallies[k] / n_mc for k in ("dsr", "sign", "bootstrap")},
    )


def power_curve(sharpe_grid, noise, n_obs, n_trials, **kw) -> list[PowerPoint]:
    return [power_at(s, noise, n_obs, n_trials, seed=i, **kw)
            for i, s in enumerate(sharpe_grid)]


def find_mde(curve: list[PowerPoint], power_level: float = 0.8) -> float:
    """Smallest true Sharpe whose power ≥ `power_level`, linearly interpolated
    between bracketing grid points. NaN if the curve never reaches the level."""
    pts = sorted(curve, key=lambda p: p.true_sharpe)
    for prev, cur in zip(pts, pts[1:]):
        if prev.power < power_level <= cur.power:
            if cur.power == prev.power:
                return cur.true_sharpe
            frac = (power_level - prev.power) / (cur.power - prev.power)
            return prev.true_sharpe + frac * (cur.true_sharpe - prev.true_sharpe)
    if pts and pts[0].power >= power_level:
        return pts[0].true_sharpe
    return float("nan")
