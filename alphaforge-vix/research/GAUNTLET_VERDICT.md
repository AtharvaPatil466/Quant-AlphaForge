# VIX — Phase 3 Gauntlet Verdict

_Generated 2026-05-21T11:39:23+00:00_  
_VIX_DESIGN.md SHA-256: `54e53be92f72e5161a4478cb8e518955d08164bfad0057675278fa2c49367b29`_  
_PHASE2_STRATEGY_SPEC.md SHA-256: `18173b6d79ffa3ae6c47904d3bfedabb63de80e38f0db683de5d11aedaefc352`_

## Summary

- Trial × variant combos evaluated: **28**
- Combos passing all 6 gates: **0**
- Combos passing all 6 gates + §7 residualization (DEPLOY-READY): **0**

**Outcome: CLOSED FAILED at Phase 3.** Per §12 decision matrix row 2 — no trial × variant pair clears all six gates.

Market frame: 9188 rows 1990-01-02 → 2026-05-19

## Per-trial × variant gate breakdown

Legend: G1 = DSR > 0.95 (both OOS), G2 = bootstrap CI > 0 (both OOS), G3 = sign agreement, G4 = cost-double survival, G5 = max-DD per stress period, G6 = CF-Sharpe > 0.5, R = §7 residualization alpha t > 1.96.

| Trial × variant | OOS-A Sharpe | OOS-B Sharpe | DSR-A | DSR-B | G1 | G2 | G3 | G4 | G5 | G6 | R | DEPLOY |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `vrp_L10_thr2_hold5_A` | +0.02 | +0.52 | 0.022 | 0.143 | · | · | ✓ | · | ✓ | · | · | · |
| `vrp_L10_thr2_hold5_B` | -0.56 | +0.44 | 0.000 | 0.112 | · | · | · | · | ✓ | · | · | · |
| `vrp_L10_thr2_hold21_A` | -0.02 | +0.52 | 0.018 | 0.201 | · | · | · | · | ✓ | · | · | · |
| `vrp_L10_thr2_hold21_B` | -0.56 | +0.47 | 0.000 | 0.173 | · | · | · | · | ✓ | · | · | · |
| `vrp_L10_thr4_hold5_A` | -0.08 | +0.55 | 0.013 | 0.198 | · | · | · | · | ✓ | · | · | · |
| `vrp_L10_thr4_hold5_B` | -0.54 | +0.48 | 0.000 | 0.159 | · | · | · | · | ✓ | · | · | · |
| `vrp_L10_thr4_hold21_A` | +0.01 | +0.01 | 0.022 | 0.022 | · | · | ✓ | · | ✓ | · | · | · |
| `vrp_L10_thr4_hold21_B` | -0.55 | +0.00 | 0.000 | 0.021 | · | · | · | · | ✓ | · | · | · |
| `vrp_L21_thr4_hold5_A` | -0.13 | +0.38 | 0.010 | 0.135 | · | · | · | · | ✓ | · | · | · |
| `vrp_L21_thr4_hold5_B` | -0.77 | +0.32 | 0.000 | 0.106 | · | · | · | · | ✓ | · | · | · |
| `vrp_L21_thr4_hold21_A` | -0.02 | +0.28 | 0.018 | 0.086 | · | · | · | · | ✓ | · | · | · |
| `vrp_L21_thr4_hold21_B` | -0.64 | +0.22 | 0.000 | 0.066 | · | · | · | · | ✓ | · | · | · |
| `vrp_L63_thr2_hold5_A` | +0.04 | +0.38 | 0.026 | 0.070 | · | · | ✓ | ✓ | ✓ | · | · | · |
| `vrp_L63_thr2_hold5_B` | -0.51 | +0.31 | 0.000 | 0.056 | · | · | · | · | ✓ | · | · | · |
| `vrp_L63_thr2_hold21_A` | -0.08 | +0.28 | 0.013 | 0.053 | · | · | · | · | ✓ | · | · | · |
| `vrp_L63_thr2_hold21_B` | -0.62 | +0.20 | 0.000 | 0.040 | · | · | · | · | ✓ | · | · | · |
| `vrp_L63_thr4_hold5_A` | +0.23 | +0.17 | 0.060 | 0.037 | · | · | ✓ | ✓ | ✓ | · | · | · |
| `vrp_L63_thr4_hold5_B` | -0.40 | +0.09 | 0.001 | 0.028 | · | · | · | · | ✓ | · | · | · |
| `vrp_L63_thr4_hold21_A` | +0.10 | +0.20 | 0.033 | 0.041 | · | · | ✓ | ✓ | ✓ | · | · | · |
| `vrp_L63_thr4_hold21_B` | -0.56 | +0.12 | 0.000 | 0.031 | · | · | · | · | ✓ | · | · | · |
| `mr_k1.5_to_MA+1sigma_A` | +0.45 | -0.18 | 0.224 | 0.007 | · | · | · | · | ✓ | · | · | · |
| `mr_k1.5_to_MA+1sigma_B` | +0.40 | -0.18 | 0.172 | 0.007 | · | · | · | · | ✓ | · | · | · |
| `mr_k1.5_to_MA_A` | +0.25 | -0.54 | 0.079 | 0.001 | · | · | · | · | ✓ | · | · | · |
| `mr_k1.5_to_MA_B` | +0.20 | -0.52 | 0.059 | 0.001 | · | · | · | · | ✓ | · | · | · |
| `mr_k2.0_to_MA+1sigma_A` | +0.47 | +0.12 | 0.255 | 0.043 | · | · | ✓ | ✓ | ✓ | · | · | · |
| `mr_k2.0_to_MA+1sigma_B` | +0.41 | +0.13 | 0.193 | 0.044 | · | · | ✓ | ✓ | ✓ | · | · | · |
| `mr_k2.0_to_MA_A` | +0.37 | -0.17 | 0.152 | 0.007 | · | · | · | · | ✓ | · | · | · |
| `mr_k2.0_to_MA_B` | +0.32 | -0.17 | 0.113 | 0.008 | · | · | · | · | ✓ | · | · | · |

## Discussion

**Phase 3 outcome: CLOSED FAILED. Substrate #7 joins the six prior CLOSED-FAILED verdicts.**

This is the *first* verdict the project has produced after a clean Phase 1 pass — every prior substrate either closed FAILED at Phase 1 (PEAD, equity Tier 2) or was killed at Phase 3 (Tier 1, crypto carry, India). Substrate #7 cleared Phase 1 (10/18 VRP trials pass signed-positive IC; strongest +0.180 at h=21), survived the Phase 2 strategy-spec pre-commit, and now fails Phase 3 across all 28 (trial × variant) combinations.

**Diagnostic — three honest findings from this Phase 3 run:**

1. **The §9.1 sizing formula produces ~0.5% NAV exposure at VIX=20.** A $1M portfolio takes a $5,000 short-vol position. Combined with §17.3 SVXY-only execution (cash-funded, no margin), the strategy holds ~99.5% of NAV in cash and ~0.5% in SVXY/VXX on most days. At this sizing, the VRP signal — even when correctly directional — produces dollar PnL too small to clear DSR or bootstrap-CI gates after deflation against the 28-trial pre-commit. Per §14.17 (filed in §17.8 ADDENDUM): "the strategy as specified can only generate small dollar gains and losses; a passing verdict at §9.1 sizing implies the SIGNAL exists; whether it scales to deployment size is a Phase 4 / capacity question beyond the §10 gauntlet's scope."

2. **The first Phase 3 run accidentally tested cash carry, not VRP.** The original NAV included T-bill carry on free cash via the §6 / §14.7 carry table. Result: 18/28 apparent deploy-ready combos with OOS Sharpes of +2.8 to +11.6. Diagnosis: the strategy is 99.5% cash; the carry alone produces low-variance steady drift; Sharpe explodes. §17.8 ADDENDUM (filed pre-rerun) zeros out cash carry — per the §6 design intent which was for *posted margin on futures*, not *free cash on an ETP account*. Strict direction-of-effect: makes the gauntlet harder. Re-run with carry=0 → 0/28 pass.

3. **Variant B (VXX hedge) is universally worse than Variant A in OOS-A.** The VXX contango drag eats more than the protection it provides during calm periods. OOS-B (which contains COVID) brings them closer together but neither passes. The hedge is "buying insurance for an event that didn't happen at scale during this OOS window."

**The G3 (sign agreement) ticks are real — but small.** Six trials pass sign agreement (positive Sharpe in BOTH OOS) with the VRP path: `vrp_L10_thr2_hold5_A`, `vrp_L10_thr4_hold21_A`, `vrp_L63_thr2_hold5_A`, `vrp_L63_thr4_hold5_A`, `vrp_L63_thr4_hold21_A`, and 3 mean-reversion variants (`mr_k2.0_to_MA+1sigma_A/B`, `vrp_L63_thr2_hold5_A`). Cost-doubling survives in 5 trials. But every single one fails DSR (G1), bootstrap CI (G2), and CF-Sharpe (G6) — the Sharpes are too small for the gates designed to detect a real edge under multiple-testing.

**This is consistent with the constraint-shift hypothesis being partially correct.** Phase 1 evidence that VRP has a structural positive IC remains valid. Phase 3 evidence that the §9.1-sized strategy can't extract enough of it to clear the deflation gates is also valid. These are not contradictory — they say: "yes the premium exists; no the pre-committed implementation does not capture it at retail-data + ETP-execution + 0.5%-NAV sizing."

**What the verdict does NOT say:** it does NOT say the variance risk premium is post-arbitrage. It says the strategy AS SPECIFIED in §9 + §17.3 + §17.4 doesn't clear the gauntlet. A larger sizing rule (e.g., 5% NAV) might. A futures-based execution path (if VIX futures data were obtainable) might. Both would be different strategies requiring different pre-commits.

**Per §15 hard rule discipline, no sizing change or instrument change is permitted post-Phase-3.** The verdict is CLOSED FAILED on the pre-committed strategy. Any "what if we sized larger" exploration would be a SEPARATE substrate (#8) requiring its own pre-commit. The founder decision is whether to attempt that #8, paid-data substrate, or step outside systematic alpha entirely.

**Known limitation §14.18 (acknowledged but not gate-changing):** Gate 5 max-drawdown evaluation reports the 2008 and 2011 stress periods as "covered" with 0.00% drawdown — but the SVXY-only execution path can't have traded those periods (SVXY launched 2011-10-04). The NAV is flat in those windows because the strategy is sitting in cash. The PHASE2_STRATEGY_SPEC.md §6 intent was that pre-SVXY periods report NO_DATA. The implementation needs a coverage check on tradeable-instrument-availability, not just NAV-series-availability. This bug INFLATES Variant A's Gate 5 pass rate (more pre-committed stress periods showing as "passed" when they're really inapplicable). Fixing the bug would not change the verdict — every trial fails G1/G2/G6 regardless of G5.

---

## §7 residualization note

Per §7 falloff — ST-Reversal (Kenneth French daily) and Carry (FRED 3M change) factors are NOT included in this substrate's residualization (data not staged). The OLS is run on SPY + ΔVIX only (2/4 factors), and per-trial `provisional=True` is set in the machine output. The verdict is provisional pending the full 4-factor set; a passing alpha t-stat is necessary but not sufficient. The §14.6 / §14.10 limitations also apply.

## §15 hard-rule reminder

This verdict is reported on the *pre-committed* trial set frozen in `VIX_DESIGN.md` (SHA `54e53be92f72e5161a4478cb8e518955d08164bfad0057675278fa2c49367b29`) and per the `PHASE2_STRATEGY_SPEC.md` (SHA `18173b6d79ffa3ae6c47904d3bfedabb63de80e38f0db683de5d11aedaefc352`). The master runner refuses to execute if either SHA mismatches its anchor. The DSR denominator is fixed at 28 regardless of how many trial × variant combos errored out. Errors count as fails.
