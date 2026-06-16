# Phase 1 Calibration Study — Verdict: INCONCLUSIVE  (MVE-only)

**Substrate:** #10 — Kalshi favorite-longshot bias
**Date:** 2026-06-17
**Gauntlet:** afgauntlet v1.0.0 (source_hash `e27753aa7a80…`)
**Design SHA-256 (verified):** `6a747a6291ba8042…`
**N_trials (deflation denominator):** 4

## Pre-registration

| Field | Value |
|---|---|
| Contract hash verified | True |
| Trials committed | 4 |
| Trials evaluated | 4 |

## IS / OOS calendar-midpoint split (§3)

| Half | Boundary | N |
|---|---|---|
| IS (close < midpoint) | < 2026-06-16T06:23:42.000000Z | 170 |
| OOS (close ≥ midpoint) | ≥ 2026-06-16T06:23:42.000000Z | 122 |

## Power analysis — `binary_mde` (run FIRST, §5)

Minimum resolved-event count per bucket to detect a +0.03 calibration gap at 80% power, α=0.05. A cell below this floor in either half is **UNDERPOWERED** and cannot pass.

| Bucket | base rate | MDE floor (events) |
|---|---|---|
| (0,5] | 0.025 | 276 |
| (5,15] | 0.100 | 843 |
| (15,35] | 0.250 | 1672 |
| (35,65] | 0.500 | 2178 |
| (65,85] | 0.750 | 1593 |
| (85,95] | 0.900 | 716 |
| (95,100) | 0.975 | 105 |

## Cells — Non-MVE (classic §4 categories)

_No cells in this group on the available data._

## Cells — MVE / Exotics (reported SEPARATELY — §16)

| Cell | dir | n(IS/OOS) | MDE | powered | edge IS | edge OOS | edge full | fee | net | G1 | G2 | G3 | G4 | G-defl | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| per-category:exotics:(0,5] | ↓longshot | 20/11 | 276 | NO | -0.0202 | -0.0159 | -0.0187 | +0.0100 | +0.0087 | · | PASS | PASS | PASS | PASS | INCONCLUSIVE |
| per-category:exotics:(5,15] | ↓longshot | 24/19 | 843 | NO | -0.1058 | -0.0492 | -0.0808 | +0.0100 | +0.0708 | PASS | PASS | PASS | PASS | PASS | INCONCLUSIVE |
| per-category:exotics:(85,95] | ↑favorite | 5/9 | 716 | NO | +0.0984 | -0.0164 | +0.0246 | +0.0100 | +0.0146 | · | · | · | PASS | · | INCONCLUSIVE |
| per-category:exotics:(95,100) | ↑favorite | 2/2 | 105 | NO | +0.0365 | +0.0130 | +0.0248 | +0.0100 | +0.0148 | · | PASS | PASS | PASS | PASS | INCONCLUSIVE |

## Study classification (§11)

| Group | Verdict |
|---|---|
| Non-MVE (§4 categories) | NO-DATA |
| MVE / Exotics (separate) | INCONCLUSIVE |
| **Headline** | **INCONCLUSIVE**  (MVE-only) |

- Cells evaluated: 4 (0 non-MVE, 4 MVE)
- Powered cells: 0 / 4
- Passing cells: 0 / 4

## Discussion

**INCONCLUSIVE — underpowered.** Per the §16 ADDENDUM, the free read-only Kalshi host yields a recent, MVE-heavy universe; the available resolved-event counts fall below the `binary_mde` floor required to detect the pre-committed +0.03 calibration gap at 80% power. This is the small-N wall flagged in §13 as the central risk, and the expected outcome under §16. Per the §11 decision matrix this routes to **forward-only data accumulation (Phase 2)** as the primary path — which suits the live-track-record goal anyway.

All available cells are **MVE / Exotics** (§16): sub-minute crypto/sports markets structurally unlike the classic FLB sports/racing effect (recreational lottery preference). Per §16 they are reported separately and never pooled with non-MVE data; no classic non-MVE category is present on the free host, so the non-MVE FLB question is not yet testable here.

_Methodology: every statistic is the canonical `afgauntlet` package (`reliability_curve`, `bucket_edge_ci`, `binary_mde`, the calibration gates). The pre-registration (design SHA-256 + trial count) was verified at runtime via `afgauntlet.PreRegistration` before any statistic was read; the run refuses to execute on mismatch (§15)._
