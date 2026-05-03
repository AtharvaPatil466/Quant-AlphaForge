# Phase 4 Design — Single-Factor Gauntlet on Residualized Returns

**Phase:** Tier 1, Phase 4
**Status:** Design locked 2026-04-30, first run pending
**Owner:** Atharva Patil
**Lifecycle:** Implementation must conform to this memo; deviations
require updating this document first.

---

## 1. The gate (binary, pre-committed)

A factor passes Phase 4 when, on the PIT S&P 500 universe with risk-
model-residualized returns net of costs:

1. **DSR > 0.95** (Bailey & López de Prado deflation, against the
   full trial set) in **both** OOS windows below.
2. **Stationary-bootstrap 95% Sharpe CI excludes zero** in both OOS
   windows.
3. **Sign of OOS Sharpe agrees** between the two windows. (A factor
   that's strongly positive in one window and strongly negative in
   the other is regime-dependent, not robust.)

All three conditions must hold for both windows. A factor that clears
in one window but not the other is *not* a Phase 4 survivor — that's
a regime-dependent signal, addressable in Phase 5 via regime-conditional
modeling, not a free pass.

---

## 2. The two non-overlapping OOS windows

| Window | Range | Trading days (~) | Embargo from training |
|---|---|---:|---|
| **OOS-A** | 2022-01-03 → 2023-12-29 | ~502 | 21 days before 2022-01-03 |
| **OOS-B** | 2024-01-02 → 2025-12-31 | ~503 | 21 days from end of OOS-A |

Training window: `2016-01-04 → 2021-12-31` minus the 21-day embargo
before OOS-A. That's ~1,500 days of in-sample data — comfortable for
factor calibration, IC stability checks, and the bootstrap.

**Why these two windows:**
- Each ~2 years long → enough sample size for stationary-bootstrap
  Sharpe CIs not to collapse; small enough that two non-overlapping
  windows fit in the post-warmup PIT panel (2016-2025).
- The 21-day embargo between OOS-A end and OOS-B start ensures no
  21-day-horizon label can leak across the boundary.
- Both windows include a regime mix: OOS-A spans 2022 bear + 2023
  recovery; OOS-B spans 2024 megacap rally + late-2025 conditions.
  Different enough that a robust signal should clear both.

---

## 3. Residualization scope

Per `PHASE3_VALIDATION_RESULT.md`: residualize against **all six
factors** (MKT, SMB, HML, RMW, CMA, UMD) from Ken French's published
daily series, NOT against the local replica.

Reason: French's published series are CRSP-wide and universe-correct.
The structural-universe issue we hit in Phase 3 was about *building
our own SMB on a 500-ticker substrate*. Residualizing against French's
SMB strips small-firm exposure correctly even though we couldn't
build our own SMB to validate. RMW and CMA same logic.

The reference file is staged at `research/out/phase3_reference_staged.csv`
(spans 1963-07-01 → 2026-02-27, daily, full FF5+UMD).

Residualization parameters (locked):
- `RESIDUAL_WINDOW = 252` (rolling 252-day OLS regression)
- `RESIDUAL_MIN_OBS = 252` (no residual until full lookback available)

---

## 4. Factor universe — 11 factors total

| # | Factor | Source module | Type |
|---|---|---|---|
| 1 | Momentum (12-1) | factor_study.py | cross-sectional |
| 2 | Mean Reversion (5d) | factor_study.py | cross-sectional |
| 3 | Volume Surge | factor_study.py | cross-sectional |
| 4 | RSI Divergence | factor_study.py | cross-sectional |
| 5 | Earnings Drift | factor_study.py | cross-sectional |
| 6 | Amihud Illiquidity | factor_study.py | cross-sectional |
| 7 | Idiosyncratic Volatility | factor_study.py | cross-sectional |
| 8 | Residual Reversal (5d) | factor_study.py | cross-sectional |
| 9 | Low Volatility | factor_study.py | cross-sectional (TODO: confirm in panels) |
| 10 | TSMOM (time-series momentum) | tsmom_study.py | portfolio-level |
| 11 | Pairs (cointegration) | pairs_study.py | portfolio-level |

The 8 cross-sectional panels currently in `build_factor_panels()` are
the ones the gauntlet evaluates first. TSMOM and pairs run through
their own studies and report DSR + bootstrap CIs in their own outputs;
they are evaluated against the same gate but independently, since
their backtests are not panel-based.

Each cross-sectional factor is evaluated in two variants — `raw` and
`sector-neutral` — across both `raw-returns` and `residualized-returns`.
That's 8 × 2 × 2 = 32 panel evaluations, plus the 2 portfolio-level
strategies = 34 total.

The DSR deflation factor must include the full 34-trial count.

---

## 5. Gauntlet stages (per factor variant per OOS window)

Each pass produces:
- IC at horizons {1, 5, 10, 21, 63} (Spearman, t-stat)
- Quintile-spread backtest, monthly rebalance, equal-weight within leg
- Net-of-costs daily return series (commission 1bp + half-spread 2bp + impact 10bp/turnover²)
- OOS-window-sliced metrics:
  - Annualized Sharpe + stationary-bootstrap 95% CI (2,000 reps, mean block 21d)
  - Max drawdown
  - Annualized return
  - Total return
- Hansen SPA + White's Reality Check (across the full 34-trial set)
- Deflated Sharpe Ratio against the 34-trial set
- Purged-embargoed K-fold cross-validated IC at h=21

---

## 6. Outputs

| Artifact | Path |
|---|---|
| Gauntlet metrics JSON | `research/out/factor_study_results.json` |
| Markdown report | `research/out/factor_study_report.md` |
| Per-window OOS metrics | new section in JSON: `oos_windows_*` |
| Per-factor net NAV CSV | `research/out/net_navs.csv` |
| Phase 4 gate evaluation | `research/out/phase4_gate_result.md` (next session) |

---

## 7. Implementation plan

This memo is Phase 4 session 1 — design + first run. Subsequent
sessions:

- **Session 1 (this):** Write this memo. Add `OOS_WINDOWS` list +
  per-window slicing to `factor_study.py`. Run residualized gauntlet
  end-to-end with `ALPHAFORGE_FACTOR_STUDY_RESIDUALIZE=1` +
  `ALPHAFORGE_REFERENCE_FACTORS=research/out/phase3_reference_staged.csv`.
  Capture results.

- **Session 2 (next):** Write `phase4_gate.py` that reads
  `factor_study_results.json` and applies the gate from §1, producing
  `phase4_gate_result.md`. Decision: any survivors? Hand off to Phase 5
  if yes. If no, document the failure rigorously per the failure-path
  matrix in the Tier 1 plan.

- **Session 3+ (conditional):** Only if survivors exist. Phase 5
  combination work uses them. If no survivors, Phase 4 ends and the
  Tier 1 plan transitions directly to Phase 5's combination phase as
  the last shot.

---

## 8. What this memo does not cover

- Factor combination (Phase 5).
- Capacity analysis (Phase 5).
- The portfolio-level TSMOM and pairs gauntlet runs — those have
  their own scripts and run independently from `factor_study.py`.
  Their gate evaluation in `phase4_gate.py` reads their separate JSON
  outputs.
- Gate threshold sensitivity analysis. The 0.95 DSR + bootstrap-CI-
  excludes-zero gate is the pre-committed test. Sensitivity is a
  separate analysis that doesn't change Phase 4's pass/fail outcome.
