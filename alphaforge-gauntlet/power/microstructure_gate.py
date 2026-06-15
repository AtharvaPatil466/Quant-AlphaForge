"""Operating-characteristics of the microstructure Phase 1 gate.

This characterizes the *decision rule* in `alphaforge-microstructure/research/
PHASE1_DESIGN.md` — it never computes a real IC, never reads the book data, and
never touches the frozen contract. It is the IC-gate analogue of
``power/calibrate.py`` (which calibrates the Sharpe/DSR gauntlet).

The Phase 1 gate, per §2, declares a (signal, parameter) CONFIG a survivor iff:

  G1  |IC| ≥ 0.03 at the config's peak horizon, in BOTH the IS and OOS halves.
  G2  sign(IC at peak) agrees between the two halves.
  G3  the OOS peak horizon is within ±1 grid step of the IS peak horizon.

(The contract's wording is slightly ambiguous about "the peak horizon"; we take
the faithful reading above — each half has its own peak, G1 requires both peaks
to clear 0.03, G2 compares the peak signs, G3 compares the peak positions. The
reading is stated so a reviewer can object.)

§4.4 of the design asserts that with ~2.6×10⁷ observations per half "statistical
power at |IC|=0.03 is overwhelming ... the risk is regime specificity, not
power." That argument uses the RAW observation count. But the IC is computed on
K-horizon returns sampled every 100 ms, which **overlap**: adjacent K-horizon
returns share all but 100 ms of their window, so the series is heavily
autocorrelated and the *effective* sample size is

    n_eff ≈ N_total / (overlap length in samples)

which for the 1-hour horizon is N_total / 36000 — hundreds, not millions. This
module makes that quantitative and propagates it through the gate to a
false-positive rate and a power curve, per horizon.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

# The pre-committed 7-horizon grid (seconds) and the 100 ms book cadence.
HORIZONS_SECONDS = (1, 5, 30, 60, 300, 900, 3600)
CADENCE_HZ = 10.0          # 100 ms snapshots → 10 observations/second
IC_THRESHOLD = 0.03        # §2 G1
N_CONFIGS_1A = 8           # 4 OBI depths + 4 TFI windows (§3.1)


def effective_n(total_obs: float, horizon_seconds: float,
                cadence_hz: float = CADENCE_HZ,
                signal_autocorr_seconds: float = 0.0) -> float:
    """Autocorrelation-deflated effective sample size for an IC at one horizon.

    Overlapping K-horizon returns have an autocorrelation length of about
    ``horizon_seconds × cadence_hz`` samples; a persistent signal adds its own
    floor via ``signal_autocorr_seconds``. The effective number of (nearly)
    independent observations is the total divided by the larger of the two
    overlap lengths. Floored at 2 so downstream SEs stay finite.
    """
    overlap = max(horizon_seconds, signal_autocorr_seconds) * cadence_hz
    overlap = max(overlap, 1.0)
    return max(total_obs / overlap, 2.0)


def ic_null_se(n_eff: float) -> float:
    """Standard error of a Pearson IC near zero ≈ 1/√(n_eff − 1)."""
    return 1.0 / math.sqrt(max(n_eff - 1.0, 1.0))


def _horizon_corr(n_horizons: int, rho: float) -> np.ndarray:
    """AR(1)-style correlation between the per-horizon IC estimates: adjacent
    horizons share overlapping returns, so their IC noise is correlated."""
    idx = np.arange(n_horizons)
    return rho ** np.abs(idx[:, None] - idx[None, :])


@dataclass(frozen=True)
class GateResult:
    pass_rate: float
    g1_rate: float
    g2_given_g1: float
    g3_given_g1: float
    n_eff_by_horizon: tuple


def simulate_config(
    true_ic: np.ndarray,
    total_obs_per_half: float,
    *,
    horizon_corr_rho: float = 0.5,
    signal_autocorr_seconds: float = 1.0,
    n_mc: int = 20000,
    threshold: float = IC_THRESHOLD,
    seed: int = 0,
) -> GateResult:
    """Monte-Carlo pass rate of one config through G1∧G2∧G3.

    ``true_ic`` is the population IC at each of the 7 horizons (all zeros = null;
    a bump at one horizon = alternative). IS and OOS halves are drawn
    independently (the contract's two-sample split is the deflation mechanism).
    """
    h = len(HORIZONS_SECONDS)
    true_ic = np.asarray(true_ic, dtype=float)
    assert true_ic.shape == (h,)
    se = np.array([ic_null_se(effective_n(total_obs_per_half, k,
                                          signal_autocorr_seconds=signal_autocorr_seconds))
                   for k in HORIZONS_SECONDS])
    R = _horizon_corr(h, horizon_corr_rho)
    cov = np.outer(se, se) * R
    L = np.linalg.cholesky(cov + 1e-18 * np.eye(h))
    rng = np.random.default_rng(seed)

    def draw():
        z = rng.standard_normal((n_mc, h))
        return true_ic[None, :] + z @ L.T

    ic_is = draw()
    ic_oos = draw()
    peak_is = np.argmax(np.abs(ic_is), axis=1)
    peak_oos = np.argmax(np.abs(ic_oos), axis=1)
    rows = np.arange(n_mc)
    ic_is_peak = ic_is[rows, peak_is]
    ic_oos_peak = ic_oos[rows, peak_oos]

    g1 = (np.abs(ic_is_peak) >= threshold) & (np.abs(ic_oos_peak) >= threshold)
    g2 = np.sign(ic_is_peak) == np.sign(ic_oos_peak)
    g3 = np.abs(peak_oos - peak_is) <= 1
    passed = g1 & g2 & g3

    g1n = int(g1.sum())
    return GateResult(
        pass_rate=float(passed.mean()),
        g1_rate=float(g1.mean()),
        g2_given_g1=float(g2[g1].mean()) if g1n else float("nan"),
        g3_given_g1=float(g3[g1].mean()) if g1n else float("nan"),
        n_eff_by_horizon=tuple(round(effective_n(total_obs_per_half, k,
                               signal_autocorr_seconds=signal_autocorr_seconds), 1)
                               for k in HORIZONS_SECONDS),
    )


def family_wise_fp(per_config_pass_prob: float, n_configs: int = N_CONFIGS_1A) -> float:
    """P(≥1 false survivor among ``n_configs`` independent configs under null)."""
    p = min(max(per_config_pass_prob, 0.0), 1.0)
    return 1.0 - (1.0 - p) ** n_configs


def null_ic_vector() -> np.ndarray:
    return np.zeros(len(HORIZONS_SECONDS))


def alternative_ic_vector(peak_horizon_seconds: int, peak_ic: float,
                          decay: float = 0.5) -> np.ndarray:
    """True-IC vector with a bump at one horizon decaying to neighbours."""
    h = len(HORIZONS_SECONDS)
    peak_idx = HORIZONS_SECONDS.index(peak_horizon_seconds)
    idx = np.arange(h)
    return peak_ic * (decay ** np.abs(idx - peak_idx))
