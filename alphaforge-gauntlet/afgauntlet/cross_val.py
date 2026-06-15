"""Purged + embargoed k-fold CV (López de Prado 2018) — canonical.

Consolidated verbatim from ``alphaforge-python/research/stats_hygiene.py``.
Standard CV leaks across labels when forward-return horizons overlap training
folds. Purge removes training samples whose label window touches the test fold;
embargo additionally drops a buffer of samples after the test fold.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterator, List, Tuple

import numpy as np
import pandas as pd


@dataclass
class PurgedEmbargoedKFold:
    """K-fold generator with label-horizon purge + post-fold embargo.

    Args:
        n_splits:      number of folds.
        label_horizon: H — each sample's label depends on the H days after its
                       observation date; training samples within H days of the
                       test fold are purged.
        embargo_pct:   fraction of total samples embargoed after each test fold.
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

            purge_start = max(0, test_start - self.label_horizon)
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

    Both panels are aligned (T rows × N tickers). Returns per-fold and
    aggregate IC stats.
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
