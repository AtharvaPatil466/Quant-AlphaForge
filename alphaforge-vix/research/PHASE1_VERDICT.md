# VIX — Phase 1 Verdict

_Generated 2026-05-21T10:50:30+00:00_  
_VIX_DESIGN.md SHA-256: `66a6c45a90bdda5879cc37348ac01bc7aea59e5c8403531592c3d9509cdabb0b`_

## Summary

- Phase 1A — VRP: **10/18** trials pass
- Phase 1B — Slope: **0/6** trials pass
- Phase 1C — Regime: characterization only (not a pass test)

**Outcome: Phase 2 OPEN** — 10 signal(s) qualify for strategy-design pre-commit. Phase 3 still required for any substrate verdict.

## Inputs

- VIX spot: 1990-01-02 → 2026-05-19 (9188 rows)
- SPY: 1993-01-29 → 2026-05-20 (8384 rows)
- Term panel columns: VIX, VIX1D, VIX9D, VIX3M, VIX6M

## Phase 1A — VRP carry (18 trials)

Pass criteria (per §8.1):
- |IC| > 0.05 at peak horizon
- ≥ 8/11 IS years with consistent-sign IC
- ≥ 6/9 ex-2008/09 years consistent-sign

Forward-return proxy: `-log(VIX_{t+h}/VIX_t)` per §17.7 ADDENDUM.

| Trial | n_obs | IC by horizon | Peak | Yr+/All | Yr+/Ex-08/09 | Verdict |
|---|---|---|---|---|---|---|
| `vrp_L10_thr0_hold5` | 2712 | 5d:+0.039  10d:-0.004  21d:-0.027  42d:-0.062  63d:-0.078 | h=5 ic=+0.039 | 7/11 | 6/9 | FAIL |
| `vrp_L10_thr0_hold21` | 2712 | 5d:+0.039  10d:-0.004  21d:-0.027  42d:-0.062  63d:-0.078 | h=5 ic=+0.039 | 7/11 | 6/9 | FAIL |
| `vrp_L10_thr2_hold5` | 2712 | 5d:+0.051  10d:-0.000  21d:-0.011  42d:-0.047  63d:-0.039 | h=5 ic=+0.051 | 8/11 | 6/9 | PASS |
| `vrp_L10_thr2_hold21` | 2712 | 5d:+0.051  10d:-0.000  21d:-0.011  42d:-0.047  63d:-0.039 | h=5 ic=+0.051 | 8/11 | 6/9 | PASS |
| `vrp_L10_thr4_hold5` | 2712 | 5d:+0.070  10d:+0.046  21d:+0.025  42d:+0.016  63d:+0.020 | h=5 ic=+0.070 | 8/11 | 7/9 | PASS |
| `vrp_L10_thr4_hold21` | 2712 | 5d:+0.070  10d:+0.046  21d:+0.025  42d:+0.016  63d:+0.020 | h=5 ic=+0.070 | 8/11 | 7/9 | PASS |
| `vrp_L21_thr0_hold5` | 2712 | 5d:+0.020  10d:-0.025  21d:-0.024  42d:-0.021  63d:-0.027 | h=5 ic=+0.020 | 6/11 | 5/9 | FAIL |
| `vrp_L21_thr0_hold21` | 2712 | 5d:+0.020  10d:-0.025  21d:-0.024  42d:-0.021  63d:-0.027 | h=5 ic=+0.020 | 6/11 | 5/9 | FAIL |
| `vrp_L21_thr2_hold5` | 2712 | 5d:+0.034  10d:-0.020  21d:-0.023  42d:-0.028  63d:-0.017 | h=5 ic=+0.034 | 6/11 | 5/9 | FAIL |
| `vrp_L21_thr2_hold21` | 2712 | 5d:+0.034  10d:-0.020  21d:-0.023  42d:-0.028  63d:-0.017 | h=5 ic=+0.034 | 6/11 | 5/9 | FAIL |
| `vrp_L21_thr4_hold5` | 2712 | 5d:+0.080  10d:+0.049  21d:+0.071  42d:+0.033  63d:+0.044 | h=5 ic=+0.080 | 8/11 | 7/9 | PASS |
| `vrp_L21_thr4_hold21` | 2712 | 5d:+0.080  10d:+0.049  21d:+0.071  42d:+0.033  63d:+0.044 | h=5 ic=+0.080 | 8/11 | 7/9 | PASS |
| `vrp_L63_thr0_hold5` | 2712 | 5d:+0.050  10d:+0.034  21d:+0.015  42d:-0.046  63d:-0.082 | h=5 ic=+0.050 | 9/11 | 8/9 | FAIL |
| `vrp_L63_thr0_hold21` | 2712 | 5d:+0.050  10d:+0.034  21d:+0.015  42d:-0.046  63d:-0.082 | h=5 ic=+0.050 | 9/11 | 8/9 | FAIL |
| `vrp_L63_thr2_hold5` | 2712 | 5d:+0.073  10d:+0.044  21d:+0.049  42d:+0.009  63d:-0.031 | h=5 ic=+0.073 | 10/11 | 9/9 | PASS |
| `vrp_L63_thr2_hold21` | 2712 | 5d:+0.073  10d:+0.044  21d:+0.049  42d:+0.009  63d:-0.031 | h=5 ic=+0.073 | 10/11 | 9/9 | PASS |
| `vrp_L63_thr4_hold5` | 2712 | 5d:+0.141  10d:+0.136  21d:+0.180  42d:+0.117  63d:+0.078 | h=21 ic=+0.180 | 9/11 | 8/9 | PASS |
| `vrp_L63_thr4_hold21` | 2712 | 5d:+0.141  10d:+0.136  21d:+0.180  42d:+0.117  63d:+0.078 | h=21 ic=+0.180 | 9/11 | 8/9 | PASS |

## Phase 1B — Term-structure slope (6 trials)

**Contango sanity check (per §8.2):** contango n=1227 mean_fwd_ret_21=-0.01197, backwardation n=104 mean_fwd_ret_21=+0.19145.  **FAIL** (contango_positive=False, backwardation_negative_or_zero=False)

> ⚠ Contango sanity check FAILED. Per §8.2 the index-ratio slope-proxy mechanism is broken in this data; slope-trial verdicts below are reported but should be treated as suspect pending investigation.

| Trial | n_obs | Eff. start | IC by horizon | Peak | Yr+/All | Yr+/Ex-08/09 | Verdict |
|---|---|---|---|---|---|---|---|
| `slope_slope_3M_thr1.05` | 2712 | 2004-03-26 | 5d:-0.102  10d:-0.116  21d:-0.114  42d:-0.090  63d:-0.083 | h=63 ic=-0.083 | 0/6 | 0/5 | FAIL |
| `slope_slope_3M_thr1.1` | 2712 | 2004-03-26 | 5d:-0.111  10d:-0.144  21d:-0.170  42d:-0.155  63d:-0.132 | h=5 ic=-0.111 | 0/6 | 0/5 | FAIL |
| `slope_slope_6M_thr1.05` | 2712 | 2004-03-26 | 5d:-0.083  10d:-0.085  21d:-0.107  42d:-0.144  63d:-0.145 | h=5 ic=-0.083 | 0/7 | 0/5 | FAIL |
| `slope_slope_6M_thr1.1` | 2712 | 2004-03-26 | 5d:-0.082  10d:-0.098  21d:-0.122  42d:-0.148  63d:-0.138 | h=5 ic=-0.082 | 1/7 | 0/5 | FAIL |
| `slope_slope_diff_thr0.05` | 2712 | 2004-03-26 | 5d:-0.092  10d:-0.106  21d:-0.101  42d:-0.068  63d:-0.064 | h=63 ic=-0.064 | 0/6 | 0/5 | FAIL |
| `slope_slope_diff_thr0.1` | 2712 | 2004-03-26 | 5d:-0.093  10d:-0.108  21d:-0.101  42d:-0.067  63d:-0.065 | h=63 ic=-0.065 | 0/6 | 0/5 | FAIL |

## Phase 1C — VIX regime characterization (IS 2004-03-26 → 2014-12-31)

Total IS days: 2712

| Bucket | Range | n_days | Fraction | Mean VIX |
|---|---|---|---|---|
| low_vol | [0.0, 15.0) | 1045 | 0.385 | 12.80 |
| normal | [15.0, 25.0) | 1176 | 0.434 | 19.01 |
| elevated | [25.0, 35.0) | 301 | 0.111 | 28.68 |
| crisis | [35.0, ∞) | 190 | 0.070 | 47.44 |

---

## Discussion

**VRP carry**: 10/18 trials pass. Strongest: `vrp_L63_thr4_hold5` with peak IC `+0.180` at horizon h=21 (9/11 years positive, 8/9 ex-2008/09).

Pass rate by VRP entry threshold: thr=0 → 0/6, thr=2 → 4/6, thr=4 → 6/6. Higher VRP thresholds (richer premium at entry) pass more reliably — consistent with the §1.2 mean-reversion story: when the premium is *large*, the convergence trade is more reliable.

Note: Phase 1 IC is computed against the §8.1 horizons {5,10,21,42,63} for *all* trials. The pre-committed `holding_period` parameter (5 vs 21 days) does not enter the IC computation — it configures the Phase 3 backtest. The 18-trial DSR denominator is preserved; trials at the same (lookback, threshold) produce identical IC by construction. The duplication is a feature of Phase 1, not a bug: holding period earns or loses in Phase 3.

**Term-structure slope**: 0/6 trials pass. All six trials produce *negative* peak IC against the -Δlog(VIX) forward-return proxy (most negative: -0.111). The contango sanity check also flips the textbook story: contango days (n=1227) average a SLIGHTLY POSITIVE 21-day spot-VIX log change (+0.01197 as Δlog, or -0.01197 as the short-vol forward return proxy).

This is the §17.7 ADDENDUM warning realized empirically: the futures-roll-yield economic mechanism (§1.3) does NOT translate cleanly to spot-VIX index changes. Contango captures the *futures-curve shape*, not a directional bet on VIX itself; spot VIX in contango regimes drifts up about as often as it drifts down. The signal direction is empirically inverted under the spot-VIX proxy. Per §15 hard rules this is a clean PHASE-1 FAIL for all 6 slope trials — the trials are NOT relabeled or sign-flipped post-hoc.

**Mean-reversion trials (4) — Phase 3 only.** Per §4.3 the four VIX mean-reversion trials are event-driven (spike entry / mean-revert exit) and are not evaluated via Phase 1 IC. They remain in the 28-trial DSR denominator and will be evaluated in the Phase 3 gauntlet alongside the Phase 1 VRP survivors.

**Next:** 10 survivor(s) → Phase 2 strategy-design pre-commit (§9: position sizing, hedge variants, exit rules). Phase 2 freezes a strategy spec for each survivor BEFORE any OOS data is touched. Phase 3 gauntlet then evaluates all 10 Phase 1 survivors + 4 mean-reversion trials × 2 hedge variants under the §5 six-gate criteria.

---

## §15 hard-rule reminder

This verdict is reported on the *pre-committed* trial set frozen in `VIX_DESIGN.md` (SHA `66a6c45a90bdda5879cc37348ac01bc7aea59e5c8403531592c3d9509cdabb0b`). The Phase 1 orchestrator refuses to run if the design doc SHA does not match the Phase 0 certification anchor. No trial may be added, dropped, or re-parameterized post-Phase-1.
