# VIX — Substrate #8 Verdict (VIX-baseline-anchored sizing)

_Generated 2026-05-21T13:06:26+00:00_  
_VIX_DESIGN.md SHA-256 (parent): `54e53be92f72e5161a4478cb8e518955d08164bfad0057675278fa2c49367b29`_  
_SUBSTRATE8_DESIGN.md SHA-256: `2194b7b2f2e3723904dd8e5e90016279036a3cfec07128d419684847dd7c84a5`_  

## Summary

- Trial × variant combos evaluated: **28**
- Combos passing all 6 gates: **0**
- Combos passing all 6 gates + §7 residualization (DEPLOY-READY): **0**

**Outcome: SUBSTRATE #8 CLOSED FAILED.** Per §12 decision matrix row 2 — no trial × variant pair clears all six gates at the VIX-baseline-anchored sizing.

Market frame: 9188 rows 1990-01-02 → 2026-05-19

## Sizing rule — what changed vs substrate #7

Substrate #7 §9.1: `max_notional = 0.10 × pv / VIX_t`  → ~0.5% NAV at VIX=20.  
Substrate #8 §9.1: `max_notional = 0.10 × pv × (20 / VIX_t)` → ~10% NAV at VIX=20. Exactly 20× substrate #7 at every VIX level. Auto-deleverage shape preserved.

## Per-trial × variant gate breakdown

Legend: G1 = DSR > 0.95, G2 = bootstrap CI > 0, G3 = sign agreement, G4 = cost-double survival, G5 = max-DD per stress period, G6 = CF-Sharpe > 0.5, R = §7 residualization alpha t > 1.96.

| Trial × variant | OOS-A Sharpe | OOS-B Sharpe | DSR-A | DSR-B | G1 | G2 | G3 | G4 | G5 | G6 | R | DEPLOY |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `vrp_L10_thr2_hold5_A` | -0.01 | +0.53 | 0.019 | 0.150 | · | · | · | · | ✓ | · | · | · |
| `vrp_L10_thr2_hold5_B` | -0.57 | +0.45 | 0.000 | 0.117 | · | · | · | · | ✓ | · | · | · |
| `vrp_L10_thr2_hold21_A` | -0.05 | +0.53 | 0.016 | 0.208 | · | · | · | · | ✓ | · | · | · |
| `vrp_L10_thr2_hold21_B` | -0.56 | +0.48 | 0.000 | 0.178 | · | · | · | · | ✓ | · | · | · |
| `vrp_L10_thr4_hold5_A` | -0.11 | +0.57 | 0.011 | 0.206 | · | · | · | · | ✓ | · | · | · |
| `vrp_L10_thr4_hold5_B` | -0.54 | +0.50 | 0.000 | 0.165 | · | · | · | · | ✓ | · | · | · |
| `vrp_L10_thr4_hold21_A` | -0.02 | +0.01 | 0.018 | 0.022 | · | · | · | · | ✓ | · | · | · |
| `vrp_L10_thr4_hold21_B` | -0.56 | +0.01 | 0.000 | 0.021 | · | · | · | · | ✓ | · | · | · |
| `vrp_L21_thr4_hold5_A` | -0.15 | +0.40 | 0.009 | 0.144 | · | · | · | · | ✓ | · | · | · |
| `vrp_L21_thr4_hold5_B` | -0.76 | +0.34 | 0.000 | 0.112 | · | · | · | · | ✓ | · | · | · |
| `vrp_L21_thr4_hold21_A` | -0.04 | +0.29 | 0.017 | 0.092 | · | · | · | · | ✓ | · | · | · |
| `vrp_L21_thr4_hold21_B` | -0.64 | +0.23 | 0.000 | 0.070 | · | · | · | · | ✓ | · | · | · |
| `vrp_L63_thr2_hold5_A` | +0.01 | +0.40 | 0.021 | 0.073 | · | · | ✓ | · | ✓ | · | · | · |
| `vrp_L63_thr2_hold5_B` | -0.51 | +0.32 | 0.000 | 0.059 | · | · | · | · | ✓ | · | · | · |
| `vrp_L63_thr2_hold21_A` | -0.12 | +0.30 | 0.011 | 0.056 | · | · | · | · | ✓ | · | · | · |
| `vrp_L63_thr2_hold21_B` | -0.62 | +0.21 | 0.000 | 0.042 | · | · | · | · | ✓ | · | · | · |
| `vrp_L63_thr4_hold5_A` | +0.19 | +0.19 | 0.050 | 0.039 | · | · | ✓ | ✓ | ✓ | · | · | · |
| `vrp_L63_thr4_hold5_B` | -0.41 | +0.11 | 0.001 | 0.030 | · | · | · | · | ✓ | · | · | · |
| `vrp_L63_thr4_hold21_A` | +0.06 | +0.22 | 0.028 | 0.044 | · | · | ✓ | ✓ | ✓ | · | · | · |
| `vrp_L63_thr4_hold21_B` | -0.57 | +0.14 | 0.000 | 0.033 | · | · | · | · | ✓ | · | · | · |
| `mr_k1.5_to_MA+1sigma_A` | +0.45 | -0.20 | 0.220 | 0.006 | · | · | · | · | ✓ | · | · | · |
| `mr_k1.5_to_MA+1sigma_B` | +0.40 | -0.19 | 0.171 | 0.006 | · | · | · | · | ✓ | · | · | · |
| `mr_k1.5_to_MA_A` | +0.25 | -0.55 | 0.077 | 0.001 | · | · | · | · | ✓ | · | · | · |
| `mr_k1.5_to_MA_B` | +0.20 | -0.54 | 0.058 | 0.001 | · | · | · | · | ✓ | · | · | · |
| `mr_k2.0_to_MA+1sigma_A` | +0.46 | +0.12 | 0.252 | 0.041 | · | · | ✓ | ✓ | ✓ | · | · | · |
| `mr_k2.0_to_MA+1sigma_B` | +0.41 | +0.12 | 0.193 | 0.042 | · | · | ✓ | ✓ | ✓ | · | · | · |
| `mr_k2.0_to_MA_A` | +0.37 | -0.19 | 0.150 | 0.007 | · | · | · | · | ✓ | · | · | · |
| `mr_k2.0_to_MA_B` | +0.32 | -0.18 | 0.113 | 0.007 | · | · | · | · | ✓ | · | · | · |

## Discussion — the load-bearing methodological lesson

**The verdict is CLOSED FAILED. But the REASON it failed is the most important finding of this entire VIX/VRP investigation.**

Compare a few rows between substrate #7 and substrate #8 (at the same anchor dates and trials):

| Trial × variant | Substrate #7 OOS-A | Substrate #8 OOS-A | Substrate #7 OOS-B | Substrate #8 OOS-B |
|---|---|---|---|---|
| `vrp_L10_thr2_hold5_A` | +0.02 | -0.01 | +0.52 | +0.53 |
| `vrp_L63_thr4_hold5_A` | +0.23 | +0.19 | +0.17 | +0.19 |
| `mr_k2.0_to_MA+1sigma_A` | +0.47 | +0.46 | +0.12 | +0.12 |

The Sharpes are **essentially identical** despite substrate #8 sizing being exactly 20× substrate #7. This is not a numerical coincidence — it is a fundamental property:

> **Sharpe ratio is invariant to linear scaling of position size.**
>
> Sharpe = mean(returns) / std(returns) × √252.  
> If positions scale by `k`, both `mean` and `std` of strategy returns scale by `k`.  
> The `k` cancels. Sharpe is unchanged.

Position sizing affects:
1. **Absolute dollar PnL** — yes, substrate #8's dollar gains and losses are 20× substrate #7.
2. **Drawdown magnitude** — yes, gate 5's max-DD scales with size (but substrate #7 had tiny DDs, so substrate #8 is still well under 30%).
3. **Costs as fraction of NAV** — no; costs are bp of fill notional which scales WITH position. Cost drag percentage stays the same.

Position sizing does NOT affect:
- **Sharpe ratio** (G1, G2, G3 — all Sharpe-based) → invariant.
- **DSR** (function of Sharpe) → invariant.
- **Bootstrap CI on Sharpe** → invariant.
- **Cornish-Fisher Sharpe** (scaled Sharpe) → invariant.
- **Sign agreement** → invariant.

**This means the substrate #7 §17.8 ADDENDUM diagnosis was partially wrong.** §17.8 correctly identified that the substrate #7 first-run pass was driven by cash carry on 99.5% of NAV. That part is right — carry is *additive* to position PnL, so removing it does shift Sharpe. But §17.8's *secondary* diagnosis — "sizing was too small to be measurable" — was an OVERSHOOT. The signal Sharpe is what it is; making positions 20× larger doesn't move it.

**The correct diagnosis (revealed by substrate #8) is Mode A revisited:**

> **The VRP / mean-reversion signal has real but modest OOS Sharpe (range −0.77 to +0.55 across the 28 combos). DSR > 0.95 against a 28-trial pre-commit + ~5-year OOS sample requires Sharpe roughly in the 1.5-2.5 range. The signal can't clear the deflation hurdle regardless of position sizing because sizing is irrelevant to Sharpe.**

This is the same Mode A that closed substrates 1, 3, 5: "real signal eaten by deflation against honest multiple-testing."

**Most interesting near-miss** is `mr_k2.0_to_MA+1sigma_A`: OOS-A Sharpe +0.46, OOS-B Sharpe +0.12, passes G3 + G4 + G5. DSR_A = 0.252 (vs 0.95 hurdle). For this trial to clear DSR_A, its raw Sharpe would need to roughly double — to ~+0.9 in OOS-A. That's the magnitude of the gap, and it's a Sharpe-magnitude gap, not a position-sizing gap.

**Six positive ticks survive: G3 (sign agreement) is achieved by `vrp_L63_thr4_hold5_A`, `vrp_L63_thr4_hold21_A`, `mr_k2.0_to_MA+1sigma_A`, `mr_k2.0_to_MA+1sigma_B`.** These trials produce positive Sharpe in BOTH OOS windows — small but consistent. The signal direction is right; the magnitude is just not enough.

**What this verdict means for the project's research program.**

- **Two substrates closed in one calendar day from one design — that's a methodology stress test.** Phase 1 PASS + Phase 3 FAIL on substrate #7 → §17.8 diagnosis → substrate #8 PRE-COMMIT → substrate #8 also FAILS, and reveals the diagnosis was partly wrong. The methodology surfaced its own error in the substrate #7 §17.8 reasoning. That's the discipline working — it caught the false-pass from cash carry, and it caught the false-fix from sizing.

- **The signal's modest Sharpe is structural, not implementation-fixable within the current constraint set.** Substrates #7 + #8 both used the same retail-data path (yfinance + CBOE indices), same parametric cost model, same DSR-28 pre-commit. The signal exists; it just doesn't generate Sharpe high enough to clear deflation against these constraints.

- **What's actually pre-arbitraged at the constraint set:** any signal whose OOS Sharpe is below ~1.5-2.0 against 28-trial deflation. That's the bound. Any substrate #9+ that produces sub-1.5 Sharpe will fail the same way.

- **The premium itself is not refuted.** Bondarenko 2004 / Carr-Wu 2009 documented the variance risk premium with strategies producing reported Sharpes of 1.0-1.5 BEFORE multiple-testing deflation. After DSR-28 deflation, those reported Sharpes would also fail the gate. The gauntlet correctly identifies that *publishable* alpha and *deployable* alpha are not the same thing.

- **Next moves that COULD change the verdict:**
  1. **Larger pre-commit window** — 10-year OOS instead of 5-year, lower DSR variance correction. Requires waiting OR using paid pre-2004 data.
  2. **Fewer pre-committed trials** — 10 trial DSR denominator instead of 28. Substrate #9 would need to drop search-space from the start; can't subset post-hoc.
  3. **Different signal class** — vol-surface arbitrage, dispersion trading, etc. — none of which substrate #7/#8 tested.
  4. **Accept paid data** — VIX futures + Kenneth French + FRED would close the §17 gaps and the §7 residualization gaps simultaneously.
  5. **Abandon systematic alpha at retail constraints.** Move to market-making or non-systematic.

The pattern across all seven CLOSED-FAILED substrates is now consistent: free-public-data + parametric-retail-cost + multiple-testing-deflation = no DSR-clearing signal. The methodology continues to work as designed.

---

## §7 residualization note

Substrate #8 inherits the §7 falloff from substrate #7 — only SPY + ΔVIX are wired into the OLS (2/4 factors). ST-Reversal and Carry factors are not staged. Per-trial `provisional=True` flag in the machine output.

## §15 hard-rule reminder

This verdict is reported on the *pre-committed* trial set frozen in `VIX_DESIGN.md` (SHA `54e53be92f72e5161a4478cb8e518955d08164bfad0057675278fa2c49367b29`) and the *substrate-#8* sizing rule frozen in `SUBSTRATE8_DESIGN.md` (SHA `2194b7b2f2e3723904dd8e5e90016279036a3cfec07128d419684847dd7c84a5`). The substrate-#8 runner refuses to execute if either SHA mismatches its anchor.
