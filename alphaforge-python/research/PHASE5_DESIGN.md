# Phase 5 Design — Factor Combination, Capacity, and Gauntlet

**Phase:** Tier 1, Phase 5
**Status:** Design draft 2026-05-01, awaiting first-run go-ahead
**Owner:** Atharva Patil
**Lifecycle:** Implementation must conform to this memo; deviations
require updating this document first.
**Predecessor:** `PHASE4_DESIGN.md` + `phase4_gate_result.md`
(0/9 single-factor survivors on residualized PIT returns).

---

## 1. The gate (binary, pre-committed)

The **combined** signal must pass the same three conditions as Phase 4
(`PHASE4_DESIGN.md` §1):

1. **DSR > 0.95** in **both** OOS windows below.
2. **Stationary-bootstrap 95% Sharpe CI excludes zero** in both windows.
3. **Sign of OOS Sharpe agrees** between the two windows.

DSR deflation runs against the **union of all trial Sharpes**: every
single-factor net Sharpe from Phase 4 (currently 20 trials, 34 once the
remote agent's raw-returns variant lands) **plus every combination
strategy evaluated in this phase**. Phase 5 cannot launder its
combination by ignoring the Phase 4 trial count.

Per Tier 1 plan §5: **kill criterion at week 22** — if the combined
signal fails this gate on both OOS, **THE GATE HAS FAILED** and Tier 1
transitions to Phase 6 (honest writeup + failure-path matrix).

---

## 2. The two non-overlapping OOS windows

Identical to Phase 4. **No re-tuning of windows is permitted.**

| Window | Range | Trading days (~) |
|---|---|---:|
| **OOS-A** | 2022-01-03 → 2023-12-29 | ~502 |
| **OOS-B** | 2024-01-02 → 2025-12-31 | ~503 |

Training window: `2016-01-04 → 2021-12-31` minus a 21-day embargo
before OOS-A. Combination weights and portfolio-construction
hyperparameters are calibrated **only on the training window**, frozen
before OOS evaluation.

---

## 3. Honest framing of the prior

Phase 4 Session 3 produced:

| OOS-A SR sign | OOS-B SR sign | Count |
|---|---|---:|
| − / − | (both negative in both windows) | 5 of 9 |
| − / + or + / − | (sign-disagreement across windows) | 2 of 9 |
| − / − but small (|SR| < 0.5) | (essentially noise) | 2 of 9 |
| + / + | 0 of 9 |

No single residualized factor produces a positive OOS Sharpe in both
windows. **A linear combination with non-negative weights cannot
produce a positive aggregate signal from negative components.** The
two combinations below are designed to be honest about this; both are
pre-committed before evaluation.

**Implication for Phase 5 expectations:** the central failure mode is
not "we picked the wrong combination weight scheme," it's "the
universe + cost model + residualization regime leaves no exploitable
linear signal in this factor set." The combination phase exists to
**confirm or refute** that, not to fish for a survivor.

---

## 4. Combination strategies (pre-committed)

Each strategy below is one trial. All four are evaluated on both OOS
windows and contribute to the DSR trial count.

### 4.1 Equal-weight ensemble (EWE)
Equal-weight average of the 9 cross-sectional factor scores at each
date, after sector-neutralization. Then apply the Phase 4 quintile
backtest pipeline. **Null model:** if any factor structure remains
after residualization, EWE captures the average direction.

### 4.2 IC-weighted ensemble (ICW)
Weight each factor by its in-sample (training-window only) 21-day
Spearman IC, sign included. Frozen at end of training window. Then
sector-neutralize and run the quintile pipeline. **Null model:** the
"obvious" supervised combination; rewards factors with stable
in-sample direction.

### 4.3 Markowitz overlay over factor returns (MV)
Treat each of the 9 factor-quintile-spread net return series as an
asset. Run mean-variance optimization (Ledoit-Wolf shrinkage,
long-short allowed, gross-leverage cap = 1) on the **training-window
returns only**. Frozen weights applied to OOS factor return series.
**Null model:** allows shorting negative-Sharpe factors, which is the
cleanest way to exploit a factor that's reliably *anti*-predictive.

### 4.4 Sign-corrected IC-weighted ensemble (ICW-flip)
Identical to ICW except weights are |IC|-weighted with sign forced to
match training-window direction. Distinct from MV in that it doesn't
solve a covariance-aware optimization; it's a pure signed-vote.
**Null model:** captures sign-direction edge without covariance
estimation, which is fragile on 9 series × 1500 days.

---

## 5. Portfolio construction & costs

Identical cost model to Phase 4 (`PHASE4_DESIGN.md` §5):
commission 1bp + half-spread 2bp + 10bp/turnover impact.

Two new constraints layered on top of every combination strategy:

- **Turnover penalty.** At each rebalance, add `λ · turnover²` to the
  optimization objective (or, for the non-MV strategies, post-trade
  shrinkage of weight changes by `1 / (1 + λ_t · |Δw|)`). `λ` and
  `λ_t` calibrated on the training window only; held constant OOS.
- **Sector neutralization at the portfolio level.** The combined
  long-short book is constrained to zero net exposure within each
  GICS sector (using the static `data.market.pit.sector_map` cache).
  Net beta against the equal-weight market is residualized against
  the same FF5+UMD reference factors used in Phase 3.

---

## 6. Capacity number

For each combination strategy that reaches the OOS evaluation:

- Run the square-root impact model from `research/cost_model.py`
  across an AUM grid `[$1M, $10M, $100M, $1B, $10B]`.
- Report the **AUM at which the OOS net Sharpe — averaged across the
  two windows — falls to zero**, plus the AUM at which it falls to
  half its $1M value.
- Report the median 21-day participation rate at $100M for the names
  in the long and short legs.

If even the strongest combination's capacity number is below **$10M**,
the result is "proof of methodology only" per the Phase 6 failure
matrix; flag it explicitly in the writeup.

---

## 7. Gauntlet (per combination per OOS window)

Same statistical hygiene as Phase 4:

- Annualized Sharpe + stationary-bootstrap 95% CI (2,000 reps,
  mean block 21d).
- Hansen SPA + White's Reality Check on the 4-strategy matrix
  (per OOS window).
- DSR per strategy per window, deflated against the **expanded**
  trial set: Phase 4 trials (20 / 34) ∪ the 4 combination Sharpes.
- Purged-embargoed K-fold CV IC at h=21 on the training window only,
  reported as a calibration check (not a gate condition).

---

## 8. Outputs

| Artifact | Path |
|---|---|
| Combination metrics JSON | `research/out/phase5_combination_results.json` |
| Combination markdown report | `research/out/phase5_combination_report.md` |
| Capacity curves (one per strategy) | `research/out/phase5_capacity_<strategy>.csv` |
| Phase 5 gate evaluation | `research/out/phase5_gate_result.{json,md}` |

---

## 9. Implementation plan

This memo is Phase 5 session 1 — design only. Subsequent sessions:

- **Session 2:** Implement `research/phase5_combine.py`. Reuse
  `factor_study.build_factor_panels`, `prepare_analysis_returns`,
  and `quintile_backtest_from_returns`. Wire the four combination
  strategies. Emit `phase5_combination_results.json`.
- **Session 3:** Implement `research/phase5_gate.py` (analog of
  `phase4_gate.py`). Apply the §1 gate to each combination's per-OOS
  metrics; emit `phase5_gate_result.{json,md}`.
- **Session 4:** Capacity sweep via `research/cost_model.py`; produce
  per-strategy capacity CSVs and update the combination report with
  the capacity table.
- **Session 5:** Tier 1 verdict. If any survivor: hand off to Phase 6
  pass writeup. If none: hand off to Phase 6 failure writeup with
  the diagnostic row from the failure-path matrix (§Tier 1 plan
  Phase 6).

---

## 10. What this memo does not cover

- Non-linear combinations (gradient boosting, neural ensembles).
  Out of scope for Tier 1; the linear gauntlet is the
  pre-committed test. If linear combinations all fail, the Tier 1
  conclusion is structural, not "we needed more model capacity."
- Regime-conditional combinations. Phase 4 already showed only 2 of 9
  factors disagree on sign across windows; routing on a HMM regime
  would be a Tier 2 question (per the failure-path matrix).
- Adding new factors beyond the 9. Tier 1 plan §"explicit not-doing
  list" forbids it.
- Adding new universes. Same constraint.

---

## 11. Honest pre-commitment

If all 4 combination strategies fail the §1 gate on both OOS windows,
**Tier 1 is failed** and Phase 6 writes the failure honestly. The
diagnostic from the Tier 1 plan Phase 6 matrix that fits Phase 4 +
Phase 5 of this design is:

> **"Raw IC > 0 but residualized IC ≈ 0 → WRONG SIGNAL CLASS"**

…or, if the raw-returns variant from the scheduled remote agent shows
positive raw IC that survives Phase 4 deflation but the combination
fails after costs:

> **"IC > 0 raw + residualized but net Sharpe ≤ 0 → EXECUTION PROBLEM"**

The Tier 2 pivot is determined by which row applies; that decision is
made in Phase 6, not here.
