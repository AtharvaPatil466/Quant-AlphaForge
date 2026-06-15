# DSR Variant Divergence Report

Four historical DSR implementations vs the canonical Family-A estimator,
measured across sr∈{0..3} × N∈{10,28,56} × n_obs∈{252..2520}.

## Max |ΔDSR| vs canonical (Family A: exact E[max], analytic Lo σ̂)

- VIX (analytic, exact E[max], no ÷√var):    **0.00e+00**
- crypto (analytic, exact E[max], ÷√var):    **0.0066**
- India (analytic, *asymptotic* E[max], ÷√var): **0.0260**
- PEAD (empirical cross-trial σ̂) vs canonical Family C: **1.66e-10**

## Verdict flips across variants near the 0.95 hurdle: **0** of 96 grid points

A flip = one variant clears 0.95 while another does not, at the same
(sr, N, n_obs). Zero flips means the estimator choice never changed a
pass/fail decision on this grid.

## Illustrative slice (N=28, n_obs=1260)

| sr_ann | canonical_A | vix | crypto | india |
|--------|-------------|-----|--------|-------|
| 0.00 | 0.0204 | 0.0204 | 0.0204 | 0.0225 |
| 0.25 | 0.0686 | 0.0686 | 0.0687 | 0.0742 |
| 0.50 | 0.1768 | 0.1768 | 0.1770 | 0.1877 |
| 0.75 | 0.3559 | 0.3559 | 0.3564 | 0.3715 |
| 1.00 | 0.5746 | 0.5746 | 0.5754 | 0.5912 |
| 1.50 | 0.9033 | 0.9033 | 0.9041 | 0.9108 |
| 2.00 | 0.9920 | 0.9920 | 0.9922 | 0.9930 |
| 3.00 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |

## Interpretation

- VIX reconciles to canonical to machine precision (same code lineage).
- crypto/India diverge only by the ÷√var placement on the E[max] term
  (and, for India, the asymptotic vs exact E[max] form). The divergence
  is largest at high sr where var_factor departs from 1.
- PEAD's empirical-σ̂ form reconciles to the canonical `from_trials`
  variant to machine precision.
- The flip count is the bottom line: if 0, the historical verdicts are
  robust to the estimator inconsistency.
