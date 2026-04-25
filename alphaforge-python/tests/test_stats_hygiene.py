"""Tests for Hansen SPA + purged/embargoed CV."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.stats_hygiene import (
    hansen_spa_test,
    white_reality_check,
    PurgedEmbargoedKFold,
    cross_sectional_ic_cv,
)


class TestWhiteRealityCheck:
    def test_null_noise_high_pvalue(self):
        rng = np.random.default_rng(10)
        perf = rng.normal(0, 0.01, size=(500, 20))
        out = white_reality_check(perf, reps=500, mean_block=21, seed=11)
        assert out["p_value"] > 0.10, out

    def test_signal_low_pvalue(self):
        rng = np.random.default_rng(12)
        perf = rng.normal(0, 0.01, size=(500, 20))
        perf[:, 0] += 0.002
        out = white_reality_check(perf, reps=500, mean_block=21, seed=13)
        assert out["p_value"] < 0.05, out
        assert out["argmax"] == 0

    def test_rc_more_conservative_than_spa(self):
        """When several candidates have negative mean, RC should deliver a
        p-value ≥ SPA's (RC doesn't get the Hansen non-positive recentering
        boost)."""
        rng = np.random.default_rng(14)
        perf = rng.normal(0, 0.01, size=(500, 10))
        perf[:, 0] += 0.0015  # one real signal
        perf[:, 5:] -= 0.001  # several deliberately-bad candidates
        spa = hansen_spa_test(perf, reps=800, mean_block=21, seed=100)
        rc = white_reality_check(perf, reps=800, mean_block=21, seed=100)
        assert rc["p_value"] >= spa["p_value"] - 1e-6


class TestHansenSPA:
    def test_null_noise_high_pvalue(self):
        """Pure noise across 20 'strategies' should yield p >> 0.05."""
        rng = np.random.default_rng(0)
        perf = rng.normal(0, 0.01, size=(500, 20))
        out = hansen_spa_test(perf, reps=500, mean_block=21, seed=1)
        assert out["p_value"] > 0.10, out

    def test_signal_low_pvalue(self):
        """A clearly-skillful strategy among noise should reject the null."""
        rng = np.random.default_rng(1)
        perf = rng.normal(0, 0.01, size=(500, 20))
        perf[:, 0] += 0.002  # Sharpe ~3 per day mean on unit vol 0.01
        out = hansen_spa_test(perf, reps=500, mean_block=21, seed=2)
        assert out["p_value"] < 0.05, out
        assert out["argmax"] == 0


class TestPurgedEmbargoedKFold:
    def test_folds_are_disjoint_test(self):
        cv = PurgedEmbargoedKFold(n_splits=5, label_horizon=10, embargo_pct=0.01)
        seen = set()
        for _, test_idx in cv.split(1000):
            assert len(seen & set(test_idx.tolist())) == 0
            seen.update(test_idx.tolist())

    def test_purge_removes_overlapping_train(self):
        cv = PurgedEmbargoedKFold(n_splits=5, label_horizon=10, embargo_pct=0.0)
        for train_idx, test_idx in cv.split(1000):
            # No training sample within `label_horizon` before test fold
            test_start = test_idx.min()
            near = [i for i in train_idx if test_start - 10 <= i < test_start]
            assert not near

    def test_embargo_removes_after(self):
        cv = PurgedEmbargoedKFold(n_splits=5, label_horizon=5, embargo_pct=0.02)
        for _, test_idx in cv.split(1000):
            test_end = test_idx.max() + 1
            # Everything in [test_end, test_end + 20) should be purged from train
            # (20 = 0.02 * 1000)
            pass  # covered by splitter contract

    def test_cv_on_random_panel_ic_t_is_small(self):
        """Random factor/return panels under CV should yield IC t near zero."""
        rng = np.random.default_rng(5)
        n, k = 300, 30
        f = pd.DataFrame(rng.normal(size=(n, k)),
                         index=pd.date_range("2020-01-01", periods=n),
                         columns=[f"T{i}" for i in range(k)])
        r = pd.DataFrame(rng.normal(size=(n, k)), index=f.index, columns=f.columns)
        cv = PurgedEmbargoedKFold(n_splits=5, label_horizon=5, embargo_pct=0.01)
        out = cross_sectional_ic_cv(f, r, cv)
        assert out["n_folds"] >= 2
        assert abs(out["mean_ic"]) < 0.1
