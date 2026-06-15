"""Power-calibration harness tests.

Covers the four load-bearing properties of the MDE machinery:

  (a) ``inject_alpha`` lands the *sample* annualized Sharpe near the requested
      true Sharpe on a long, low-noise series (the population identity);
  (b) detection ``power_at`` is monotonically non-decreasing in true Sharpe
      across a coarse grid (a sensitivity floor must rise, not fall, with signal);
  (c) ``find_mde`` linearly interpolates the crossover Sharpe on a hand-built
      power curve;
  (d) the fallback noise path yields a usable (>2000 obs) series when SPY is
      absent.

All stochastic tests are seeded and use small Monte-Carlo / bootstrap counts so
the whole module runs in a few seconds.
"""
import math

import numpy as np
import pytest

from afgauntlet import annualized_sharpe
from power import (PowerPoint, find_mde, inject_alpha, load_base_returns,
                   power_at)
from power.calibrate import ANN

# ─── (a) inject_alpha hits the target population Sharpe ───────────────────────


def test_inject_alpha_recovers_target_sharpe():
    """On a long, low-noise series the *sample* annualized Sharpe of the
    drift-injected path should sit near the requested true Sharpe."""
    rng = np.random.default_rng(123)
    n = 60_000                       # long → sample Sharpe converges to population
    noise_std = 0.002                # 0.2%/day → tight estimate
    noise = rng.normal(0.0, noise_std, size=n)
    noise = noise - noise.mean()     # demean: only the injected drift remains

    for target in (1.0, 2.0, 3.0):
        path = inject_alpha(noise, target, noise_std=float(noise.std(ddof=1)))
        realized = annualized_sharpe(path)
        assert realized == pytest.approx(target, abs=0.25), (
            f"target={target}, realized={realized}")


def test_inject_alpha_drift_formula():
    """The injected drift is exactly S/√252 · σ — a flat additive shift."""
    noise = np.zeros(100)
    path = inject_alpha(noise, true_ann_sharpe=2.0, noise_std=0.01)
    expected_drift = 2.0 / math.sqrt(ANN) * 0.01
    assert np.allclose(path, expected_drift)


# ─── (b) power is monotone non-decreasing in true Sharpe ──────────────────────


def test_power_monotone_in_sharpe():
    """Detection power must not fall as the injected signal strengthens.
    Coarse grid + small MC; allow a little Monte-Carlo slack."""
    noise, _ = load_base_returns()
    kw = dict(n_obs=1260, n_trials=10, n_mc=40, boot_reps=80,
              use_bootstrap=False, seed=7)
    p_lo = power_at(0.5, noise, **kw).power
    p_mid = power_at(2.0, noise, **kw).power
    p_hi = power_at(3.5, noise, **kw).power
    tol = 0.05  # MC noise tolerance at n_mc=40
    assert p_mid >= p_lo - tol, f"0.5→2.0 dropped: {p_lo} -> {p_mid}"
    assert p_hi >= p_mid - tol, f"2.0→3.5 dropped: {p_mid} -> {p_hi}"
    # And the endpoints must be genuinely separated (signal is detectable).
    assert p_hi > p_lo


def test_power_at_returns_gate_breakdown():
    """power_at exposes per-gate pass rates that bound overall detection."""
    noise, _ = load_base_returns()
    pp = power_at(2.0, noise, n_obs=1260, n_trials=10, n_mc=40, boot_reps=80,
                  use_bootstrap=False, seed=3)
    assert isinstance(pp, PowerPoint)
    assert set(pp.gate_power) == {"dsr", "sign", "bootstrap"}
    # Detection requires every gate, so overall power can't exceed any gate.
    for v in pp.gate_power.values():
        assert pp.power <= v + 1e-9
        assert 0.0 <= v <= 1.0


# ─── (c) find_mde interpolates a hand-built power curve ────────────────────────


def _curve(pairs):
    """Build a list[PowerPoint] from (sharpe, power) pairs."""
    return [PowerPoint(true_sharpe=s, power=p,
                       gate_power={"dsr": p, "sign": 1.0, "bootstrap": 1.0})
            for s, p in pairs]


def test_find_mde_interpolates():
    # Power crosses 0.8 between Sharpe 2.0 (0.6) and 3.0 (1.0):
    #   frac = (0.8 - 0.6) / (1.0 - 0.6) = 0.5 → 2.0 + 0.5*(3.0-2.0) = 2.5
    curve = _curve([(1.0, 0.1), (2.0, 0.6), (3.0, 1.0)])
    assert find_mde(curve, 0.8) == pytest.approx(2.5)
    # Crosses 0.5 between 1.0 (0.1) and 2.0 (0.6):
    #   frac = (0.5 - 0.1) / (0.6 - 0.1) = 0.8 → 1.0 + 0.8*1.0 = 1.8
    assert find_mde(curve, 0.5) == pytest.approx(1.8)


def test_find_mde_exact_grid_point():
    """If a grid point exactly meets the level it is returned without interp."""
    curve = _curve([(1.0, 0.2), (2.0, 0.5), (3.0, 0.9)])
    assert find_mde(curve, 0.5) == pytest.approx(2.0)


def test_find_mde_never_reached_is_nan():
    curve = _curve([(1.0, 0.1), (2.0, 0.3), (3.0, 0.49)])
    assert math.isnan(find_mde(curve, 0.5))


def test_find_mde_already_above_at_first_point():
    """If the lowest grid point already clears the level, return it."""
    curve = _curve([(1.0, 0.85), (2.0, 0.95), (3.0, 1.0)])
    assert find_mde(curve, 0.8) == pytest.approx(1.0)


def test_find_mde_unsorted_input():
    """find_mde sorts internally, so input order must not matter."""
    curve = _curve([(3.0, 1.0), (1.0, 0.1), (2.0, 0.6)])
    assert find_mde(curve, 0.8) == pytest.approx(2.5)


# ─── (d) fallback noise path ──────────────────────────────────────────────────


def test_load_base_returns_yields_usable_series():
    noise, source = load_base_returns()
    assert noise.size > 2000
    assert np.all(np.isfinite(noise))
    assert isinstance(source, str) and source


def test_fallback_noise_path_when_spy_absent(monkeypatch):
    """When the SPY parquet path does not exist, the Student-t fallback must
    still return a usable (>2000 obs), clearly-labelled synthetic series."""
    import power.calibrate as calib
    monkeypatch.setattr(calib, "_SPY", "/nonexistent/path/spy.parquet")
    noise, source = calib.load_base_returns(seed=0)
    assert noise.size > 2000
    assert np.all(np.isfinite(noise))
    assert "SYNTHETIC" in source
