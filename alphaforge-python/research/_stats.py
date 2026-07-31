"""Shared performance statistics for the research studies.

Extracted from factor_study / capacity_study / tsmom_study / pairs_study, which
each carried their own copy of these four functions. The copies had drifted:

  - `stationary_bootstrap_sharpe` returned a "mean" key in factor_study and
    capacity_study but not in tsmom_study or pairs_study.
  - factor_study had no `n < 30` short-circuit; the other three did.
  - `ann_return` was written as `nav ** (1 / years)` in factor_study and
    `nav ** (252 / len(r))` elsewhere. Algebraically identical.
  - `max_drawdown` differed only in whether `nav.cummax()` was bound to a
    local. Identical.

The capacity_study forms are canonical here: the "mean" key is always present
and the `n < 30` guard always applies. Bootstrapping a 20-observation series
produces a CI that means nothing, so returning zeros is the honest answer.

`reps` and `mean_block` intentionally have module defaults but every caller
passes its own BOOT_REPS / BOOT_BLOCKS explicitly — factor_study uses 2000
reps where the others use 1000, and a shared default would have silently
changed four call sites during extraction.
"""

from __future__ import annotations

import math
from typing import Dict

import numpy as np
import pandas as pd

DEFAULT_BOOT_REPS = 1000
DEFAULT_BOOT_BLOCKS = 21

# Below this many observations, an annualized Sharpe and its bootstrap CI are
# not meaningful. Shared by every caller.
MIN_OBS = 30

TRADING_DAYS = 252


def ann_sharpe(r: pd.Series) -> float:
    """Annualized Sharpe. 0.0 on degenerate input (too short, or zero vol)."""
    if len(r) < MIN_OBS or r.std(ddof=1) == 0:
        return 0.0
    return float(r.mean() / r.std(ddof=1) * math.sqrt(TRADING_DAYS))


def ann_return(r: pd.Series) -> float:
    """Annualized geometric return. 0.0 if the NAV path is wiped out."""
    nav = (1 + r).prod()
    if nav <= 0 or len(r) == 0:
        return 0.0
    return float(nav ** (TRADING_DAYS / len(r)) - 1)


def max_drawdown(r: pd.Series) -> float:
    """Worst peak-to-trough drawdown of the compounded NAV path (negative)."""
    nav = (1 + r).cumprod()
    peak = nav.cummax()
    return float(((nav - peak) / peak).min())


def stationary_bootstrap_sharpe(
    r: np.ndarray,
    reps: int = DEFAULT_BOOT_REPS,
    mean_block: int = DEFAULT_BOOT_BLOCKS,
    seed: int = 0,
) -> Dict[str, float]:
    """Politis-Romano stationary bootstrap CI on the annualized Sharpe.

    Geometric block lengths with mean `mean_block` preserve the serial
    dependence that an i.i.d. bootstrap would destroy. Returns the bootstrap
    distribution's mean, its 95% percentile interval, and the fraction of
    resamples with a positive Sharpe.
    """
    rng = np.random.default_rng(seed)
    n = len(r)
    if n < MIN_OBS:
        return {"mean": 0.0, "ci_lo": 0.0, "ci_hi": 0.0, "p_positive": 0.0}

    p = 1.0 / mean_block
    out = np.empty(reps)
    for b in range(reps):
        idxs = np.empty(n, dtype=np.int64)
        i = int(rng.integers(0, n))
        for k in range(n):
            if k > 0 and rng.random() < p:
                i = int(rng.integers(0, n))
            else:
                i = (i + 1) % n if k > 0 else i
            idxs[k] = i
        sample = r[idxs]
        sd = sample.std(ddof=1)
        out[b] = (sample.mean() / sd * math.sqrt(TRADING_DAYS)) if sd > 0 else 0.0

    return {
        "mean": float(out.mean()),
        "ci_lo": float(np.quantile(out, 0.025)),
        "ci_hi": float(np.quantile(out, 0.975)),
        "p_positive": float((out > 0).mean()),
    }


def _demo() -> None:
    """Self-check: run with `python3 research/_stats.py`."""
    rng = np.random.default_rng(0)

    # Degenerate inputs return zeros rather than NaN/exception.
    short = pd.Series(rng.normal(0, 0.01, 10))
    assert ann_sharpe(short) == 0.0
    assert ann_sharpe(pd.Series([0.0] * 100)) == 0.0           # exactly zero vol
    assert ann_return(pd.Series([], dtype=float)) == 0.0

    # KNOWN SHARP EDGE, carried over unchanged from all four original copies:
    # the zero-vol guard is an exact `== 0` test, and a constant *non-zero*
    # series has std ~1.7e-18 rather than 0.0, so it slips through and yields
    # a nonsense Sharpe. Not fixed here — this extraction is behaviour-
    # preserving by design, and a tolerance would move published numbers.
    assert ann_sharpe(pd.Series([0.01] * 100)) > 1e15
    assert stationary_bootstrap_sharpe(short.to_numpy()) == {
        "mean": 0.0, "ci_lo": 0.0, "ci_hi": 0.0, "p_positive": 0.0
    }

    # A strongly positive drift is detected with the CI above zero.
    good = pd.Series(rng.normal(0.002, 0.01, 500))
    assert ann_sharpe(good) > 1.0
    boot = stationary_bootstrap_sharpe(good.to_numpy(), reps=200, seed=7)
    assert set(boot) == {"mean", "ci_lo", "ci_hi", "p_positive"}
    assert boot["ci_lo"] < boot["mean"] < boot["ci_hi"]
    assert boot["p_positive"] > 0.9

    # Drawdown is negative and bounded below by -1 for a long-only NAV path.
    dd = max_drawdown(pd.Series([0.1, -0.5, 0.2]))
    assert -1.0 <= dd < 0.0

    # Same seed, same answer.
    a = stationary_bootstrap_sharpe(good.to_numpy(), reps=100, seed=3)
    b = stationary_bootstrap_sharpe(good.to_numpy(), reps=100, seed=3)
    assert a == b

    print("_stats self-check OK")


if __name__ == "__main__":
    _demo()
