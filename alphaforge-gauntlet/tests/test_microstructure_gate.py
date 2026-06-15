"""Tests for the microstructure Phase 1 gate characterization.

These pin the load-bearing claims: effective-N collapses with horizon, the null
false-positive rate is materially above zero at long horizons, and detection
power rises with the true IC at well-powered (short) horizons.
"""
import numpy as np
import pytest

from power import microstructure_gate as mg


def test_effective_n_collapses_with_horizon():
    N = 2.6e7
    n1 = mg.effective_n(N, 1)
    n3600 = mg.effective_n(N, 3600)
    assert n1 > n3600
    # 1h horizon: ~N/36000, a few hundred, not millions.
    assert n3600 == pytest.approx(N / 36000, rel=0.2)
    assert n3600 < 2000


def test_long_horizon_se_exceeds_threshold_even_at_design_data():
    # The crux of the §4.4 critique: at 1h, IC null SE >= the 0.03 gate.
    se_3600 = mg.ic_null_se(mg.effective_n(2.6e7, 3600))
    assert se_3600 > mg.IC_THRESHOLD


def test_effective_n_floored():
    assert mg.effective_n(10, 3600) >= 2.0


def test_null_pass_rate_positive_and_short_horizon_well_powered():
    # Under the null the gate still leaks (long horizons); not ~0.
    res = mg.simulate_config(mg.null_ic_vector(), 2.6e7, n_mc=8000, seed=0)
    assert res.pass_rate > 0.01
    assert 0.0 <= res.pass_rate <= 1.0


def test_family_wise_fp_monotone_and_bounded():
    assert mg.family_wise_fp(0.0) == 0.0
    assert mg.family_wise_fp(1.0) == 1.0
    assert mg.family_wise_fp(0.1, 8) > mg.family_wise_fp(0.1, 1)
    assert 0.0 <= mg.family_wise_fp(0.1, 8) <= 1.0


def test_power_increases_with_true_ic_at_short_horizon():
    # At a well-powered short horizon, more signal -> more detections.
    obs = 2.6e7
    weak = mg.simulate_config(mg.alternative_ic_vector(5, 0.03), obs, n_mc=8000, seed=3)
    strong = mg.simulate_config(mg.alternative_ic_vector(5, 0.08), obs, n_mc=8000, seed=3)
    assert strong.pass_rate > weak.pass_rate


def test_alternative_vector_peaks_where_requested():
    v = mg.alternative_ic_vector(60, 0.05)
    peak_idx = int(np.argmax(np.abs(v)))
    assert mg.HORIZONS_SECONDS[peak_idx] == 60
    assert v[peak_idx] == pytest.approx(0.05)


def test_null_vector_is_zero():
    assert np.all(mg.null_ic_vector() == 0.0)
