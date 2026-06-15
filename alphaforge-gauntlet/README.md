# afgauntlet — the canonical AlphaForge evaluation gauntlet

One audited, version-pinned implementation of every statistic the substrate
verdicts depend on. Historically each substrate (crypto, PEAD, India, VIX)
shipped its **own** copy of these primitives; this package consolidates them so
that (a) every future verdict runs identical, unit-tested code, and (b)
`source_hash()` lets a verdict pin exactly which code produced it.

## Why this exists

The VIX substrate's first Phase-3 run "passed" 18/28 — a cash-carry bug, caught
only on manual inspection. That is the failure mode of four duplicated
statistical harnesses: a bug in one can silently produce a false verdict, and
nothing guarantees the other substrates used the same maths. This package is the
single source of truth, with two kinds of evidence behind it:

- **Golden tests** (`tests/test_golden.py`) — analytic invariants (DSR
  monotonicities and bounds, bootstrap reproducibility, CV purge gaps, …).
- **Reconciliation tests** (`tests/test_reconciliation.py`,
  `tests/test_dsr_variants.py`) — the canonical functions reproduce the *actual
  published* substrate code (loaded by file path), to float equality where the
  formulas match and to a quantified bound where they don't.

## What's inside

| Module | Contents |
|--------|----------|
| `sharpe.py` | `annualized_sharpe`, skew/excess-kurtosis, `cornish_fisher_sharpe`, `sign_agreement` |
| `deflated.py` | `deflated_sharpe_ratio` (exact E[max], analytic σ̂), `deflated_sharpe_ratio_from_trials` (empirical cross-trial σ̂), `expected_max_sharpe` |
| `bootstrap.py` | `stationary_bootstrap_sharpe_ci` + the shared index generator |
| `multiple_testing.py` | `hansen_spa_test`, `white_reality_check` |
| `cross_val.py` | `PurgedEmbargoedKFold`, `cross_sectional_ic_cv` |
| `gates.py` | composable gate constructors + `GauntletReport` (deploy-ready = AND of gates) |
| `version.py` | `source_hash()` for verdict pinning |

## The DSR-consistency finding

The substrates ran **four** different DSR estimators against one 0.95 hurdle:

| Substrate | σ̂(SR) | E[max] | tail moments | E[max] ÷ √var |
|---|---|---|---|---|
| VIX | analytic (Lo) | exact two-quantile | live | no |
| crypto | analytic (Lo) | exact two-quantile | live | yes |
| India | analytic (Lo) | **Euler-asymptotic** | live | yes |
| PEAD | **empirical cross-trial** | exact two-quantile | **hardcoded Gaussian** | n/a |

`reports/dsr_variant_divergence.py` measures the disagreement across
sr×N×n_obs. Result: max |ΔDSR| is **0.026** (India), and there are **zero
verdict flips** across 96 grid points — no historical verdict was an artifact of
its DSR estimator. The canonical package standardizes on the exact analytic form
(`deflated_sharpe_ratio`) and offers the faithful empirical form
(`deflated_sharpe_ratio_from_trials`).

## Usage

```python
import afgauntlet as g

report = g.evaluate_gates([
    g.gate_deflated_sharpe(oos_returns, n_trials=28),
    g.gate_bootstrap_excludes_zero(oos_returns),
    g.gate_sign_agreement(oos_a, oos_b),
    g.gate_cost_survival(oos_returns_doubled_cost),
    g.gate_max_drawdown(nav_series, max_drawdown=0.30),
    g.gate_cornish_fisher(oos_returns, threshold=0.5),
])
print(report.summary())          # per-gate PASS/FAIL + DEPLOY-READY/REJECTED
verdict = {"gauntlet_source_hash": g.source_hash(), **report.to_dict()}
```

## Running

```bash
cd alphaforge-gauntlet
python3.13 -m pytest tests/ -q                    # 31 tests
python3.13 reports/dsr_variant_divergence.py      # writes reports/out/*.{md,json}
```

Pure numpy/pandas; only `cross_sectional_ic_cv` needs scipy (imported lazily).
