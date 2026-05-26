# PEAD Phase 2 — Stress + Capacity Contract (Pre-Committed)

**Status:** PRE-COMMITMENT, CONTINGENT. Written 2026-05-17. **Runs only if Phase 1 produces ≥1 SURVIVOR** per `PEAD_DESIGN.md` §6. If Phase 1 closes FAILED, this document is unused and its trial count does not enter any deflation calculation.

**This document is the contract for the second gate.** Every threshold, parameter, and decision rule is frozen before any Phase 2 metric is computed. No edits after the first Phase 2 number is produced.

Pairs with:
- `PEAD_DESIGN.md` — the Phase 1 signal contract.
- `alphaforge-python/research/PHASE6_WRITEUP.md` — equity Tier 1's documented cost-model underestimate (Corwin-Schultz 7-8bp vs parametric 2bp). The Phase 2 cost-doubling gate exists specifically to stress against this known understatement.

---

## 1. Why Phase 2 Exists (the row-2 lesson)

Tier 1 produced a Markowitz overlay with alpha-residual OOS Sharpe +3.06/+2.43 — significant under any conventional test — that failed only on the DSR deflation hurdle. Tier 2 then falsified the "costs eat real signal" interpretation by showing the alpha collapsed at longer rebalance horizons.

The PEAD analogue: a Phase-1-surviving SUE config has cleared the IC/DSR/sign bar at the parametric cost model. Phase 2's job is to find out whether that survival is robust to (a) **realistic costs**, (b) **capacity binding**, and (c) **regime conditioning**. If any of these three knocks out the signal, PEAD joins the four prior verdicts as substrate #5 CLOSED FAILED-AT-PHASE-2. The Phase 1 result alone is not a deploy decision.

---

## 2. The Three Gates (all must clear)

### Gate P2-A — Cost-Sensitivity Stress

Rerun the surviving config's full IS+OOS-A+OOS-B backtest with the cost model doubled:

| Component | Phase 1 (parametric) | Phase 2 (doubled) |
|---|---|---|
| Commission | 1 bp | 2 bp |
| Half-spread | 2 bp | 4 bp |
| Linear impact (× turnover) | 10 bp | 20 bp |

The doubled values are calibrated against the Corwin-Schultz 7-8bp half-spread reality documented in the Tier 2 cost-check artifact. **Configurations whose OOS Sharpe sign flips, or whose DSR drops below 0.95 in either OOS window under doubled costs, fail P2-A.**

Rationale: Tier 2's lesson is that "cheaper than reality" cost models produce strategies that look fine in backtest and bleed in live. The cost-doubling gate enforces robustness to a 2× error in the cost estimate. This is conservative compared to the 3-4× understatement documented for the existing equity cost model.

### Gate P2-B — Capacity Binding

Sweep an AUM grid `{$10M, $50M, $250M, $1B, $5B}` using the square-root impact model from `alphaforge-python/research/cost_model.py::SquareRootImpactModel`:

$$ \text{cost\_bps}(t) = k \cdot \sqrt{\text{ADV\_participation}(t)} $$

with `k` pre-committed at the existing equity gauntlet's calibration value (held constant from Phase 6 of Tier 1; see `capacity_study.py`).

For each AUM point, recompute the OOS Sharpe net of impact. The **capacity curve** must monotonically degrade, and the **minimum deployable AUM** is the AUM at which OOS-A Sharpe falls below the Phase 1 floor (`|Sharpe| ≥ ` whatever the Phase 1 survivor reported).

A config passes P2-B if its capacity at the **minimum credible deployment scale ($50M)** still clears the Phase 1 alpha floor. A config that needs to be deployed at $10M or below is reported as PASSES BUT NOT DEPLOYABLE — the founder track cannot run a hedge fund at $10M AUM. This is not a methodology gate; it is a viability gate that's been on every prior substrate.

### Gate P2-C — Regime Conditioning

The Tier 1 / Tier 2 substrate exhibited regime dependence — MV-21's alpha was concentrated in specific subwindows. PEAD's literature documents similar behavior: the effect is stronger after large surprises, in bear markets, in low-analyst-coverage names.

Phase 2 splits the OOS-A and OOS-B return series by VIX terciles (Tier 1 used this exact split):

| Regime | Definition | Required |
|---|---|---|
| Calm | VIX trailing-21d mean in the bottom tercile of OOS-A+OOS-B | OOS Sharpe sign-consistent with full-OOS sign |
| Normal | Middle tercile | OOS Sharpe sign-consistent |
| Stressed | Top tercile | OOS Sharpe sign-consistent |

A config passes P2-C if the signal sign agrees across **all three** tercile buckets, in **both** OOS windows. Sign disagreement in any cell = a regime-specific signal, which is the row-3 failure mode (signal exists but only in specific market conditions, not robust to a deployment that crosses regimes).

A regime-specific signal is NOT automatically a fail — it could be deployed as a regime-conditional strategy via the `bandit/` infrastructure in `alphaforge-marl/`. But that's a Phase 3 (deploy-design) decision, not a Phase 1/2 gate-clearing decision, and it would require its own pre-committed design doc covering the regime-detector latency, false-positive rate, and the bandit's prior calibration.

---

## 3. Phase 2 Trial Count and DSR Deflation

Phase 2 does NOT add new signal-design trials. It runs the surviving Phase 1 config(s) through three additional stress tests. The trial-count book is:

- Phase 1a trial count: 10
- Phase 1b trial count (conditional): 20 (counted only if 1b was triggered)
- Phase 2 trial count: **0** new signals — the stress dimensions are not additional hypotheses about the signal, they are robustness diagnostics on a hypothesis that already cleared.

The DSR hurdle in Gate P2-A reuses the same Phase 1 deflation factor. We do NOT re-deflate against `phase1_count + phase2_count` — that would be double-counting.

---

## 4. Decision Matrix (Phase 2 outcomes per surviving config)

| P2-A | P2-B | P2-C | Verdict |
|---|---|---|---|
| Pass | Pass ($50M+) | Pass all three regimes | **DEPLOY-READY** — proceeds to Phase 3 (deploy design + paper-trade certification). |
| Pass | Pass ($50M+) | Sign disagrees in ≥1 regime | **CONDITIONAL** — regime-specific signal, requires Phase 3 design doc covering the regime-detection layer. |
| Pass | Passes only at <$50M | Pass all three | **PASSES-BUT-NOT-DEPLOYABLE** — capacity bound. Document and move on. |
| Pass | Fail at all AUM | — | **PASSES-BUT-NOT-DEPLOYABLE**. |
| Fail (Sharpe sign flip OR DSR<0.95 under doubled costs) | — | — | **CLOSED FAILED at Phase 2.** Substrate #5 final verdict: row-2 (real signal, costs eat it — same failure as equity Tier 1 reinterpreted post-Tier 2). |

If any config reaches DEPLOY-READY or CONDITIONAL, the founder-track decision is whether to allocate to PEAD versus continuing the microstructure track. That is a meta-decision outside this contract.

---

## 5. Methodology Reuse (read-only from frozen modules)

Phase 2 reuses these modules from the frozen equity stack:

- `alphaforge-python/research/cost_model.py` — `SquareRootImpactModel`, `HonestCostModel`.
- `alphaforge-python/research/capacity_study.py` — AUM-grid sweep template.
- `alphaforge-python/research/stats_hygiene.py` — stationary-bootstrap CIs, Hansen SPA.
- `alphaforge-python/research/risk_model.py` — FF5+UMD residualization (same as Phase 1).

None of these are modified. The PEAD sub-project imports them read-only.

---

## 6. Hard Rules (the non-negotiables)

1. **Phase 2 does not run if Phase 1 has zero survivors.** If Phase 1 closes FAILED, this contract is unused and PEAD's verdict document reports only Phase 1.
2. **No tuning of cost parameters between Phase 1 and Phase 2.** The doubled-cost values are pre-committed here; they do NOT get adjusted after seeing Phase 1's exact alpha magnitude.
3. **No tuning of the AUM grid based on Phase 1 results.** The five AUM points are fixed.
4. **No tuning of the regime tercile cutpoints.** They are computed exactly once from the OOS-A+OOS-B VIX series and reused as-is.
5. **No retroactive movement of a config from CLOSED FAILED back to DEPLOY-READY.** If P2-A fails, the verdict is final.

These rules failed exactly zero times across the four prior substrates that produced credible negative verdicts.

---

## 7. Authorship and Pre-Commitment Anchor

- **Author:** Atharva Patil
- **Drafted:** 2026-05-17 (pre-Phase-0-certification, pre-any-Phase-1-result, pre-any-Phase-2-execution)
- **Pre-commitment anchor:** this document's SHA-256 hash is to be included in `PEAD_PHASE1_VERDICT.md` *only if* Phase 1 produces ≥1 survivor and Phase 2 is consequently triggered.

```bash
# After committing this file:
shasum -a 256 alphaforge-pead/research/PHASE2_DESIGN.md
```
