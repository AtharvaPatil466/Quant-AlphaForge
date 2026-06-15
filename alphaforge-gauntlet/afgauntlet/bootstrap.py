"""Stationary-bootstrap Sharpe CI (Politis & Romano 1994) — canonical.

The 1-D ``stationary_bootstrap_indices`` here is the single index generator
used by *both* the Sharpe CI (this module) and the multiple-testing layer
(``multiple_testing.py``). It is verbatim-equivalent to the VIX substrate's
generator, and consumes the RNG stream identically to the equity stack's
``stats_hygiene._stationary_bootstrap_indices`` when looped per replication —
so reconciliation against both upstreams is bit-exact.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .sharpe import ANNUALIZATION, annualized_sharpe


def stationary_bootstrap_indices(
    n: int,
    expected_block_size: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """One bootstrap resample of indices (Politis-Romano, geometric blocks).

    ``expected_block_size`` is the mean block length in observations.
    """
    if n <= 0:
        return np.array([], dtype=int)
    if expected_block_size < 1:
        raise ValueError("expected_block_size must be >= 1")
    p = 1.0 / expected_block_size
    out = np.empty(n, dtype=int)
    idx = int(rng.integers(0, n))
    out[0] = idx
    for t in range(1, n):
        if rng.random() < p:
            idx = int(rng.integers(0, n))
        else:
            idx = (idx + 1) % n
        out[t] = idx
    return out


@dataclass(frozen=True)
class SharpeBootstrapCI:
    sharpe: float
    lower: float
    upper: float
    n_replications: int
    expected_block_size: int
    seed: int

    @property
    def excludes_zero(self) -> bool:
        """True iff the whole CI is on one side of zero (both bounds finite)."""
        if not (np.isfinite(self.lower) and np.isfinite(self.upper)):
            return False
        return self.lower > 0 or self.upper < 0


def stationary_bootstrap_sharpe_ci(
    daily_returns: np.ndarray | pd.Series,
    n_replications: int = 4000,
    expected_block_size: int = 21,
    confidence: float = 0.95,
    seed: int = 0,
    annualization: float = ANNUALIZATION,
) -> SharpeBootstrapCI:
    """Stationary-bootstrap CI for annualized Sharpe (geometric blocks)."""
    if isinstance(daily_returns, pd.Series):
        daily_returns = daily_returns.dropna().to_numpy()
    daily_returns = np.asarray(daily_returns, dtype=float)
    if daily_returns.size < expected_block_size + 1:
        return SharpeBootstrapCI(
            sharpe=annualized_sharpe(daily_returns, annualization),
            lower=float("nan"), upper=float("nan"),
            n_replications=0,
            expected_block_size=expected_block_size, seed=seed,
        )
    rng = np.random.default_rng(seed)
    base_sharpe = annualized_sharpe(daily_returns, annualization)
    boots = np.empty(n_replications, dtype=float)
    n = daily_returns.size
    for k in range(n_replications):
        idx = stationary_bootstrap_indices(n, expected_block_size, rng)
        sample = daily_returns[idx]
        boots[k] = annualized_sharpe(sample, annualization)
    boots = boots[np.isfinite(boots)]
    alpha = 1.0 - confidence
    lower = float(np.quantile(boots, alpha / 2.0))
    upper = float(np.quantile(boots, 1.0 - alpha / 2.0))
    return SharpeBootstrapCI(
        sharpe=base_sharpe,
        lower=lower,
        upper=upper,
        n_replications=int(boots.size),
        expected_block_size=expected_block_size,
        seed=seed,
    )
