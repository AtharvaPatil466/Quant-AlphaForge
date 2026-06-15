"""Multiple-testing controls — Hansen SPA (2005) + White's Reality Check (2000).

Consolidated from ``alphaforge-python/research/stats_hygiene.py``. The only
structural change is that index generation reuses the shared 1-D
``stationary_bootstrap_indices`` (looped per replication) instead of a private
2-D builder; the RNG stream is identical, so results reconcile bit-for-bit
against the equity stack.

Both tests share an input/output shape so they can be reported side-by-side.
White's RC (no Hansen recentering) is strictly more conservative than SPA.
"""
from __future__ import annotations

import numpy as np

from .bootstrap import stationary_bootstrap_indices


def hansen_spa_test(
    perf_matrix: np.ndarray,
    reps: int = 2000,
    mean_block: int = 21,
    seed: int = 0,
) -> dict:
    """Hansen's Superior Predictive Ability test.

    Args:
        perf_matrix: (T, K) per-period performance deltas for K candidate
            strategies vs a common benchmark.
        reps:        bootstrap repetitions.
        mean_block:  stationary-bootstrap mean block length.
        seed:        RNG seed.

    Returns a dict with ``T_spa``, ``p_value``, ``argmax``, ``best_mean``.
    A p-value < 0.05 means at least one candidate shows performance that
    cannot be explained by data-snooping across the K models.
    """
    perf_matrix = np.asarray(perf_matrix, dtype=float)
    T, K = perf_matrix.shape
    if T < 30 or K < 1:
        return {"T_spa": float("nan"), "p_value": float("nan"),
                "argmax": -1, "best_mean": float("nan")}

    rng = np.random.default_rng(seed)
    means = perf_matrix.mean(axis=0)
    stds = perf_matrix.std(axis=0, ddof=1)
    stds = np.where(stds < 1e-12, 1e-12, stds)

    # Hansen recentering: subtract only the non-negative bias correction.
    recenter = np.maximum(means, 0.0)
    t_obs = (np.sqrt(T) * means / stds).max()

    t_boot = np.empty(reps)
    for b in range(reps):
        idx = stationary_bootstrap_indices(T, mean_block, rng)
        sample = perf_matrix[idx]
        boot_mean = sample.mean(axis=0) - recenter
        boot_std = sample.std(axis=0, ddof=1)
        boot_std = np.where(boot_std < 1e-12, 1e-12, boot_std)
        t_boot[b] = (np.sqrt(T) * boot_mean / boot_std).max()

    p_value = float((t_boot >= t_obs).mean())
    return {
        "T_spa": float(t_obs),
        "p_value": p_value,
        "argmax": int(means.argmax()),
        "best_mean": float(means.max()),
    }


def white_reality_check(
    perf_matrix: np.ndarray,
    reps: int = 2000,
    mean_block: int = 21,
    seed: int = 0,
) -> dict:
    """White's Reality Check for data-snooping bias.

    Same inputs/outputs as ``hansen_spa_test`` but recenters each candidate's
    resampled mean by its *observed* mean (no Hansen max(·,0) correction),
    making it strictly more conservative when some candidates have negative
    mean. Output keys: ``T_rc``, ``p_value``, ``argmax``, ``best_mean``.
    """
    perf_matrix = np.asarray(perf_matrix, dtype=float)
    T, K = perf_matrix.shape
    if T < 30 or K < 1:
        return {"T_rc": float("nan"), "p_value": float("nan"),
                "argmax": -1, "best_mean": float("nan")}

    rng = np.random.default_rng(seed)
    means = perf_matrix.mean(axis=0)
    stds = perf_matrix.std(axis=0, ddof=1)
    stds = np.where(stds < 1e-12, 1e-12, stds)

    t_obs = (np.sqrt(T) * means / stds).max()

    t_boot = np.empty(reps)
    for b in range(reps):
        idx = stationary_bootstrap_indices(T, mean_block, rng)
        sample = perf_matrix[idx]
        boot_mean = sample.mean(axis=0) - means
        boot_std = sample.std(axis=0, ddof=1)
        boot_std = np.where(boot_std < 1e-12, 1e-12, boot_std)
        t_boot[b] = (np.sqrt(T) * boot_mean / boot_std).max()

    p_value = float((t_boot >= t_obs).mean())
    return {
        "T_rc": float(t_obs),
        "p_value": p_value,
        "argmax": int(means.argmax()),
        "best_mean": float(means.max()),
    }
