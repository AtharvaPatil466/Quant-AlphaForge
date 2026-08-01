"""Study statistics for the research scripts — an adapter over `afgauntlet`.

The Sharpe and stationary-bootstrap math is NOT implemented here. It is the
canonical `afgauntlet` package (`annualized_sharpe`,
`stationary_bootstrap_indices`), so these studies run the same audited,
version-pinned code as every substrate verdict.

What survives locally is only what afgauntlet does not export:

  - `ann_return` / `max_drawdown` — NAV-path descriptives, not gauntlet
    statistics; no canonical home.
  - the dict-shaped bootstrap return (`mean` / `ci_lo` / `ci_hi` /
    `p_positive`). afgauntlet's `stationary_bootstrap_sharpe_ci` returns a
    `SharpeBootstrapCI` carrying the *point* Sharpe and CI bounds, and drops
    the replicate array — so it cannot produce `mean` (the bootstrap
    distribution's mean) or `p_positive`, both of which these reports print.
    We rebuild the distribution from afgauntlet's index generator instead of
    re-deriving the resampling scheme.

Verified bit-identical to the previous local implementation: same RNG stream,
same quantiles, same `mean`/`p_positive`.

`reps` and `mean_block` have module defaults but every caller passes its own
BOOT_REPS / BOOT_BLOCKS explicitly — factor_study uses 2000 reps where the
others use 1000, and a shared default would silently change call sites.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd

# The canonical gauntlet package lives in the sibling `alphaforge-gauntlet/`
# and is not pip-installed — same sys.path pattern alphaforge-prediction uses.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_GAUNTLET = _REPO_ROOT / "alphaforge-gauntlet"
if str(_GAUNTLET) not in sys.path:
    sys.path.insert(0, str(_GAUNTLET))

from afgauntlet import (ANNUALIZATION, annualized_sharpe,  # noqa: E402
                        stationary_bootstrap_indices)

DEFAULT_BOOT_REPS = 1000
DEFAULT_BOOT_BLOCKS = 21

# Below this many observations, an annualized Sharpe and its bootstrap CI are
# not meaningful. Shared by every caller.
MIN_OBS = 30

TRADING_DAYS = int(ANNUALIZATION)


def ann_sharpe(r: pd.Series) -> float:
    """Annualized Sharpe. 0.0 on degenerate input (too short, or zero vol).

    The `MIN_OBS` floor is this project's convention and sits on top of
    afgauntlet, which has no minimum-length opinion of its own.
    """
    if len(r) < MIN_OBS:
        return 0.0
    return float(annualized_sharpe(r, TRADING_DAYS))


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

    Resampling and per-replicate Sharpe both come from afgauntlet; this only
    reduces the replicate distribution to the dict shape the reports print.
    """
    n = len(r)
    if n < MIN_OBS:
        return {"mean": 0.0, "ci_lo": 0.0, "ci_hi": 0.0, "p_positive": 0.0}

    rng = np.random.default_rng(seed)
    out = np.empty(reps)
    for b in range(reps):
        idxs = stationary_bootstrap_indices(n, mean_block, rng)
        out[b] = annualized_sharpe(r[idxs], TRADING_DAYS)

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
    assert stationary_bootstrap_sharpe(short.to_numpy()) == {
        "mean": 0.0, "ci_lo": 0.0, "ci_hi": 0.0, "p_positive": 0.0
    }

    # Delegating to afgauntlet FIXED a sharp edge the four original local
    # copies shared: their zero-vol guard was an exact `std(ddof=1) == 0`, and
    # a constant *non-zero* series has std ~1.7e-18, so it slipped through and
    # returned a Sharpe of ~9e16. afgauntlet's guard is FP-tolerant.
    assert ann_sharpe(pd.Series([0.01] * 100)) == 0.0

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
