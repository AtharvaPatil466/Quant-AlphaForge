# Carry Study Verdict — CLOSED FAILED

**Date:** 2026-05-15
**Pre-commit anchors:** `dbd77ad` (design doc) + `4277eba` (trial log)
**OOS commit:** `0d35e41`
**OOS window:** 2025-01-08 → 2026-05-14 (1.35 years, 2952 funding events)
**K_primary:** 63 (≈21-day rebalance)

## Verdict

**CLOSED FAILED — 3 of 5 pre-committed gates failed.** No re-running, no relaxing thresholds, no rebranding as basis study. Failure per design doc §9.

| Gate | Threshold | Realized | Passed |
|---|---|---|---|
| 1 — Net annualized Sharpe | > 0.5 | +1.48 | ✓ |
| 2 — Bootstrap 95% CI excludes 0 | excludes 0 | [-1.39, +4.33] | ✗ |
| 3 — DSR | > 0.95 | 0.624 (N=32) | ✗ |
| 4 — Annualized turnover | < 800% | 1701% | ✗ |
| 5 — Sign agreement IS vs OOS | same sign | IS +3.55 / OOS +1.48 | ✓ |

## What worked

- **The signal is real.** IS cross-sectional rank correlation between past-funding lookback and forward funding was 0.46–0.59 depending on K, stable across 5 purged CV folds (per-fold range 0.42–0.61 at K=21). This is an order of magnitude larger than equity-factor ICs (typically 0.02–0.05).
- **The methodology held.** Pre-commit gates fired correctly. Trial log captured 32 trials including 14 considered-but-not-run alternatives. DSR penalty was the binding constraint — exactly what it was designed to be.
- **Sign agreement passed.** Both IS and OOS produced positive Sharpe; the strategy isn't a coin flip.
- **Cost economics were correctly diagnosed in advance.** Design doc §11 predicted "DSR-implied minimum observed Sharpe ≈ 1.5-1.8 annualized". Realized OOS Sharpe of 1.48 sits exactly below that range. The math worked.

## What failed and why

### Gate 3 (DSR 0.624) — the binding rigor constraint
With per-event Sharpe = 0.045 and N_trials = 32, the multiple-testing-corrected null threshold is approximately a Sharpe of 1.6 annualized (from the design doc's §11 estimate). The realized 1.48 sits just below. **The strategy had real edge but not enough margin over the deflation penalty.** This is the standard "decent signal eaten by methodology hygiene" outcome — the same shape as equity Tier 1's MV-21 combination (alpha-residual OOS Sharpe +3.06 / +2.43 with DSR 0.92 / 0.70).

### Gate 4 (Turnover 1701%) — costs were under-modeled
IS realized turnover proxy was 1251%. OOS realized turnover was 1701% — 36% higher than IS. The gate at 800% was set in the design doc based on the IS economics analysis ("turnover ceiling = ~2 round-trips/week-per-symbol = sanity-check against the cost model"); reality blew through it. **The basket composition was less stable in 2025-2026 than in 2020-2024**, likely because the universe in OOS included more freshly-onboarded volatile alts (TRUMP, KITE, AIGENSYN, PUMP, etc.) whose funding regimes flipped more often than the older majors.

### Gate 2 (CI straddles zero) — vol was too high relative to mean
The bootstrap CI [-1.39, +4.33] is wide. Mean Sharpe of 1.48 with a spread of 5.7 across the bootstrap means we cannot confidently distinguish the strategy from a coin flip at 95% confidence. Higher costs (gate 4) ate into the mean; persistent dispersion did not translate cleanly into per-event PnL. Even pre-DSR, this gate would fail.

### IS-to-OOS decay (3.55 → 1.48, 58% Sharpe loss)
A loss this size is what the DSR is built to detect. The OOS Sharpe is not bad — it's just not large enough to clear an honest multiple-testing penalty over 32 trials.

## Comparison to the equity gauntlet

| Aspect | Equity Tier 1 | Equity Tier 2 | Crypto Carry |
|---|---|---|---|
| Substrate | PIT S&P 500 returns | PIT S&P 500 returns (lower turnover) | Binance USDT-M perp funding |
| Hypothesis class | Cross-sectional equity factors | Cross-sectional equity factors + volcap | Cross-sectional funding carry |
| Best signal IC (IS) | ~0.04 (MV-21 best) | similar | **+0.46 to +0.59** |
| Best IS Sharpe | +3.06 (MV-21) | +0.95 (MV-126) | +3.55 (K=63) |
| OOS Sharpe at best | +2.43 / +3.06 | ~+0.79 to +0.95 | +1.48 |
| DSR | 0.92 / 0.70 | < 0.95 | 0.624 |
| Verdict | FAILED | FAILED | **FAILED** |

The crypto substrate had a **much stronger raw signal** (IC ~0.5 vs ~0.04) than equities. It still failed because:
1. The signal is more crowded — at modest dispersion (~1 bp per 8h median), even a 50% IC translates to small absolute PnL.
2. Costs (36 bps round-trip combined) are extreme relative to per-event funding (1-5 bps).
3. The "carry on crypto perps" trade is famously well-known — DSR honestly priced this in via 32 trial penalty.

## Diagnosis on the failure-path matrix

Borrowing the matrix from equity Phase 6 §4:

| Failure path | Equity Tier 1 | Crypto Carry |
|---|---|---|
| 1. No real signal | — | ✗ (IC 0.5+ is real) |
| 2. Real signal eaten by costs / multiple-testing | ✓ | ✓ |
| 3. Overfit to IS regime | — | partial (35% Sharpe decay; not catastrophic) |
| 4. Implementation bug | — | — |
| 5. Sample-period contingent | — | possibly (1.35y OOS is short) |

**Row 2 (signal eaten by costs / multiple-testing) is the diagnosis for both Tier 1 and Crypto Carry.** Same root cause across substrates. The crypto pivot did NOT change the failure mode — it just changed which specific signals get screened.

## What this means for the next substrate decision

The substrate pivot from equities to crypto explicitly bet that the equity-factor failure was substrate-specific. It wasn't. Both:
- Cross-sectional equity factors over PIT S&P 500
- Cross-sectional funding carry over Binance USDT-M perpetuals

are linear, cross-sectional, rank-based strategies that get screened by the same combination of (a) honest costs and (b) deflation against trial counts that reflect the breadth of the search.

**The honest question is no longer "what substrate?" It's "what strategy class?"**

The remaining unexplored options from the original 2026-06-01 substrate-change memo are:
- **Futures (term-structure / roll-yield)** — different signal class (term structure vs cross-section)
- **Options (vol surface)** — different signal class, different cost structure
- **Market-making** — execution alpha, not signal alpha; needs L2 data
- **Away from systematic alpha entirely** — discretionary, fundamental, advisory, employment

This is a founder-track question, not a code question. The next move should be deliberate.

## Followups not in scope of this verdict

- A basis study (`research/basis_study.py` stub) was deferred pending carry verdict. Carry has now CLOSED FAILED — the basis stub stays a stub unless there's a specific reason to revive it. Per §10 of the design doc: "Basis study activated only if carry passes, or definitively closed." Definitively closed → basis is NOT auto-activated.
- The `_assert_is_only()` guard worked correctly throughout IS. OOS guard equivalent (`_filter_to_oos`) is now in place. Both should stay in the codebase as discipline scaffolding even though the study is closed.
- The DSR-formula bug fix (commit `0d35e41`) is a methodology infrastructure improvement that applies retroactively if anyone wants to recompute Tier 1/2 DSR numbers. Out of scope here.

## What does NOT get done in this commit

- No "let me try a few more K values"
- No "let me relax the cost model"
- No "let me re-run with a longer holding period"
- No re-opening of `carry_study.py` to fit
- No basis study auto-activation

Failure is failure. The verdict is the verdict.
