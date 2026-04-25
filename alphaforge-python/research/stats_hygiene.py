"""Advanced statistical hygiene beyond Deflated Sharpe.

Two tools:

1. **Hansen SPA (2005)** — Superior Predictive Ability test. Null: no
   model in the candidate set has positive expected Sharpe (or any chosen
   performance statistic) after accounting for the fact that we picked
   the best one ex-post. We use the stationary-bootstrap distribution of
   the studentized max across candidates and compute the SPA p-value.

2. **Purged + embargoed k-fold CV** (López de Prado, 2018). Standard CV
   leaks across labels when forward-return horizons overlap training
   folds. Purge removes training samples whose label window touches the
   test fold; embargo additionally drops a buffer of samples after the
   test fold.

Both tools are importable from research/factor_study.py.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterator, List, Sequence, Tuple

import numpy as np
import pandas as pd


# ─── Hansen SPA ──────────────────────────────────────────────────────────

def _stationary_bootstrap_indices(n: int, reps: int, mean_block: int,
                                   rng: np.random.Generator) -> np.ndarray:
    """Return (reps, n) array of resample indices under stationary bootstrap."""
    p = 1.0 / mean_block
    out = np.empty((reps, n), dtype=np.int64)
    for b in range(reps):
        i = int(rng.integers(0, n))
        for k in range(n):
            if k > 0 and rng.random() < p:
                i = int(rng.integers(0, n))
            else:
                i = (i + 1) % n if k > 0 else i
            out[b, k] = i
    return out


def hansen_spa_test(
    perf_matrix: np.ndarray,
    reps: int = 2000,
    mean_block: int = 21,
    seed: int = 0,
) -> dict:
    """Hansen's Superior Predictive Ability test.

    Args:
        perf_matrix: shape (T, K) of per-period performance deltas
            (e.g., daily excess returns for each of K candidate strategies
            against a common benchmark). A strategy with positive mean
            performance is a candidate for "superior".
        reps:       bootstrap repetitions.
        mean_block: stationary-bootstrap mean block length (days).
        seed:       RNG seed for reproducibility.

    Returns:
        {
          'T_spa'     : observed test statistic (studentized max mean),
          'p_value'   : SPA p-value (larger = weaker evidence of skill),
          'argmax'    : index of best candidate,
          'best_mean' : per-period mean of the best candidate
        }

    A p-value < 0.05 means at least one candidate shows performance that
    cannot be explained by data-snooping across the K models.
    """
    T, K = perf_matrix.shape
    if T < 30 or K < 1:
        return {"T_spa": float("nan"), "p_value": float("nan"),
                "argmax": -1, "best_mean": float("nan")}

    rng = np.random.default_rng(seed)
    means = perf_matrix.mean(axis=0)
    stds = perf_matrix.std(axis=0, ddof=1)
    stds = np.where(stds < 1e-12, 1e-12, stds)

    # Hansen's recentering: subtract only the "non-worse-than-worst" bias
    # correction. We use the simple SPA_c variant (consistent) that
    # recenters each candidate's resampled mean by max(mean, 0).
    recenter = np.maximum(means, 0.0)

    t_obs = (np.sqrt(T) * means / stds).max()

    boot_idx = _stationary_bootstrap_indices(T, reps, mean_block, rng)
    t_boot = np.empty(reps)
    for b in range(reps):
        sample = perf_matrix[boot_idx[b]]  # (T, K)
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


# ─── White's Reality Check (2000) ────────────────────────────────────────

def white_reality_check(
    perf_matrix: np.ndarray,
    reps: int = 2000,
    mean_block: int = 21,
    seed: int = 0,
) -> dict:
    """White's Reality Check for data-snooping bias.

    Null: the best candidate has no positive expected performance once
    the selection from K candidates is accounted for. Uses a plain
    stationary-bootstrap distribution of the studentized max without the
    Hansen-style recentering; this makes it more conservative than SPA
    (harder to reject) when some candidates have negative mean.

    Inputs and output shape mirror ``hansen_spa_test`` so the two can be
    reported side-by-side.
    """
    T, K = perf_matrix.shape
    if T < 30 or K < 1:
        return {"T_rc": float("nan"), "p_value": float("nan"),
                "argmax": -1, "best_mean": float("nan")}

    rng = np.random.default_rng(seed)
    means = perf_matrix.mean(axis=0)
    stds = perf_matrix.std(axis=0, ddof=1)
    stds = np.where(stds < 1e-12, 1e-12, stds)

    t_obs = (np.sqrt(T) * means / stds).max()

    boot_idx = _stationary_bootstrap_indices(T, reps, mean_block, rng)
    t_boot = np.empty(reps)
    for b in range(reps):
        sample = perf_matrix[boot_idx[b]]
        # Naive (no recentering): subtract the *observed* sample mean so
        # the bootstrap distribution is centered at zero under H0.
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


# ─── Purged + embargoed k-fold CV ────────────────────────────────────────

@dataclass
class PurgedEmbargoedKFold:
    """K-fold generator that purges training samples whose label horizon
    overlaps the test fold, then embargoes a buffer after the test fold.

    Args:
        n_splits:    number of folds.
        label_horizon: H — each sample's label depends on the H days after
                     its observation date. Training samples within H days
                     of the test fold are purged.
        embargo_pct: fraction of total samples to embargo after each test
                     fold (López de Prado 2018, ch. 7).
    """
    n_splits: int = 5
    label_horizon: int = 21
    embargo_pct: float = 0.01

    def split(self, n_samples: int) -> Iterator[Tuple[np.ndarray, np.ndarray]]:
        if self.n_splits < 2:
            raise ValueError("n_splits must be >= 2")
        indices = np.arange(n_samples)
        fold_size = n_samples // self.n_splits
        embargo = int(round(self.embargo_pct * n_samples))

        for k in range(self.n_splits):
            test_start = k * fold_size
            test_end = (k + 1) * fold_size if k < self.n_splits - 1 else n_samples
            test_idx = indices[test_start:test_end]

            # Purge: remove training samples whose label window
            # [i, i + label_horizon] touches the test fold.
            purge_start = max(0, test_start - self.label_horizon)
            # Embargo: buffer after the test fold.
            embargo_end = min(n_samples, test_end + embargo)

            train_mask = np.ones(n_samples, dtype=bool)
            train_mask[purge_start:embargo_end] = False
            train_idx = indices[train_mask]
            yield train_idx, test_idx


def cross_sectional_ic_cv(
    factor_panel: pd.DataFrame,
    fwd_ret_panel: pd.DataFrame,
    cv: PurgedEmbargoedKFold,
) -> dict:
    """Per-fold mean Spearman IC using purged+embargoed CV.

    Both panels are aligned DataFrames (T rows × N tickers). Returns
    per-fold and aggregate IC stats.
    """
    from scipy import stats

    common_idx = factor_panel.index.intersection(fwd_ret_panel.index)
    f = factor_panel.loc[common_idx]
    r = fwd_ret_panel.loc[common_idx]
    n = len(common_idx)
    fold_ics: List[float] = []
    fold_sizes: List[int] = []
    for train_idx, test_idx in cv.split(n):
        ics = []
        for i in test_idx:
            fv = f.iloc[i].to_numpy()
            rv = r.iloc[i].to_numpy()
            mask = np.isfinite(fv) & np.isfinite(rv)
            if mask.sum() < 10:
                continue
            rho, _ = stats.spearmanr(fv[mask], rv[mask])
            if np.isfinite(rho):
                ics.append(rho)
        if ics:
            fold_ics.append(float(np.mean(ics)))
            fold_sizes.append(len(ics))
    if not fold_ics:
        return {"folds": [], "mean_ic": float("nan"),
                "ic_std": float("nan"), "ic_t": float("nan")}
    arr = np.array(fold_ics)
    mean_ic = float(arr.mean())
    sd = float(arr.std(ddof=1)) if len(arr) > 1 else 0.0
    t_stat = mean_ic / (sd / math.sqrt(len(arr))) if sd > 0 else float("nan")
    return {
        "folds": [{"ic": a, "n_days": s} for a, s in zip(fold_ics, fold_sizes)],
        "mean_ic": mean_ic,
        "ic_std": sd,
        "ic_t": t_stat,
        "n_folds": len(fold_ics),
    }
