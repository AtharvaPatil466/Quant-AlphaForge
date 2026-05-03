# Tier 2 — Final Verdict

**Status:** CLOSED FAILED — 2026-05-02
**Author:** Atharva Patil
**Predecessors:** `TIER2_DESIGN.md` (path-1, $0-cost version),
`PHASE6_WRITEUP.md` (Tier 1 final writeup, gate FAILED on row 2).
**Companion artifacts:**
`research/out/tier2/tier2_phase2_results.json`,
`research/out/tier2/tier2_phase2_gate.{json,md}`,
`research/out/tier2/tier2_phase1_replication.json`,
`research/out/tier2/tier2_universe_audit.json`,
`research/out/tier2/tier2_phase1_cost_check.json`.

---

## 1. The binary verdict

The pre-committed Tier 2 gate (`TIER2_DESIGN.md` §2 conditions 1-4)
required:

1. DSR > 0.95 in both OOS windows
2. Bootstrap CI excludes zero in both
3. Sign agreement
4. 6-month forward paper-trade with realized Sharpe CI excluding zero

**0 of 8 strategies cleared conditions 1-3** (the gate to enter
Phase 3 forward paper-trade). **Phase 3 was not entered.** Per the
pre-committed §5.2 outcome 3, Tier 2 has FAILED.

---

## 2. The per-strategy table

Alpha-residual residual Sharpes per OOS window, post-FF5+UMD time-
series alpha decomposition (`compute_portfolio_alpha`), with
4,000-rep stationary-bootstrap CIs and DSR deflated against a
unique 4-trial set (volcap and ext variants reduced to the same
underlying strategies — see §4 below):

| Strategy | OOS-A α-SR | DSR-A | CI≠0 | OOS-B α-SR | DSR-B | CI≠0 |
|---|---:|---:|---|---:|---:|---|
| MV-63 | +0.79 | 0.726 | no | +1.97 | 0.988 | yes |
| MV-126 | +0.95 | 0.793 | no | +0.11 | 0.360 | no |
| MV-63-volcap | +0.79 | 0.726 | no | +1.97 | 0.988 | yes |
| MV-126-volcap | +0.95 | 0.793 | no | +0.11 | 0.360 | no |
| MV-63-shrunk | +0.62 | 0.641 | no | +1.85 | 0.982 | yes |
| MV-126-shrunk | +0.87 | 0.759 | no | -0.31 | 0.172 | no |
| MV-63-ext | +0.79 | 0.726 | no | +1.97 | 0.988 | yes |
| MV-126-ext | +0.95 | 0.793 | no | +0.11 | 0.360 | no |

Failure-mode summary: 8/8 fail DSR-A (the OOS-A bootstrap CI
brackets zero and the deflation finishes the job); the 63d
strategies pass DSR-B but fail DSR-A, so they cannot clear both
windows; the 126d strategies fail DSR-B as well, with MV-126-shrunk
also failing sign agreement.

**Near-miss criterion** (alpha-residual SR ≥ +1.5 in BOTH windows,
which would have activated the §6.3 Tier 2.5 R1k contingent): 0
strategies meet this bar. The R1k contingent is NOT activated.

---

## 3. The headline finding — row 2 is wrong

Phase 6 §4 (the Tier 1 writeup) committed the failure-path
diagnostic to **row 2: "real signal eaten by costs/multiple-testing
→ EXECUTION PROBLEM."** That commit was made on the basis of
MV-21's alpha-residual OOS Sharpes (+3.06 / +2.43): the assumption
was that the signal existed but cost erosion or deflation killed
its survivability.

Tier 2's evidence falsifies that diagnosis directly:

```
MV-21  (Tier 1 baseline)  alpha-residual OOS-A = +3.06
MV-63                    alpha-residual OOS-A = +0.79
MV-126                   alpha-residual OOS-A = +0.95
```

If the row-2 hypothesis were correct — "real signal, killed by
costs at high turnover" — then *lowering* turnover should preserve
or amplify the alpha, because the realized cost charge per trading
day shrinks proportionally. Instead, lowering turnover **destroyed
the alpha**. The MV-21 OOS-A signal of +3.06 collapses to +0.79 at
quarterly rebalance and +0.95 at semi-annual rebalance.

**The revised reading:** the MV-21 alpha is not a real cross-
sectional anomaly trapped behind a cost wall. It is more likely a
**short-horizon-specific phenomenon** — most plausibly a 21-day
residualized mean-reversion pattern that lives at high frequency
and does not transport to longer horizons. Mean reversion in
residualized returns is a well-documented short-frequency
phenomenon (Da/Liu/Schaumburg 2014); the MV combination on
sector-neutralized residualized factors at 21d rebalance is
mechanically very close to a residualized-reversal portfolio.

This pushes the failure diagnosis closer to a *combination* of
failure-path matrix rows that Tier 1 didn't have a clean fit for:
the alpha exists at one specific frequency / construction, doesn't
generalize, and the OOS-A vs OOS-B asymmetry under the longer
horizons (OOS-B routinely collapsing to ~0 while OOS-A stays
modestly positive) suggests a regime-dependent component as well.

---

## 4. Honest limitations of this Tier 2 verdict

Three issues worth flagging — none of them invalidate the verdict,
but all of them shape what Tier 3 (or its successor) should do
differently:

1. **Vol-cap variants are no-ops for Sharpe.** Vol-targeting linearly
   scales the daily return series; Sharpe is scale-invariant; DSR is
   scale-invariant. The MV-{63,126}-volcap rows are mathematically
   identical to MV-{63,126}. They were included as separate trials
   in the pre-commit because the design memo treated vol-targeting
   as a meaningful construction tweak; in retrospect this was an
   error in the pre-commit. The verdict stands either way (the
   trial set is effectively 4 unique strategies, not 8, which is
   a *less* punishing deflation, not more).

2. **Extended-history variants are no-ops given the panel start.**
   The factor study's `analysis_returns` panel starts in 2016, so
   the per-factor LS net return series only begins in 2016. Slicing
   `train_start=2010` vs `train_start=2016` produces identical
   training data. To genuinely test the "more training data"
   hypothesis, the close panel itself would need to extend to
   2010 — which would mean training on the smaller 296-ticker
   2010-2015 universe per Phase 1.2. That's a meaningfully
   different test that Tier 2's plumbing didn't run. Acknowledged
   as a limitation; not material to the verdict because none of
   the *as-run* variants cleared the gate either.

3. **Cost-model under-estimation (Phase 1.3).** Tier 1's parametric
   2bp half-spread is ~3-4× lower than the Corwin-Schultz median
   (~7-8 bps) across all windows. Per pre-commit, Tier 2 kept the
   parametric value. If Tier 2 had used realistic costs, the
   single-factor net Sharpes would have been more negative, and the
   MV combination's gross-leverage = 1 weighting would have
   amplified the cost amplification. Net effect on the verdict:
   most likely the row-2 hypothesis would have looked LESS viable,
   not more — which is consistent with the verdict.

---

## 5. The §7 reset commitment

Per `TIER2_DESIGN.md` §7, with Tier 2 closed FAILED:

- **Stop all new gauntlet design for 30 calendar days.**
  Window: 2026-05-02 → 2026-06-01.
- **No Tier 3 design before 2026-06-01.** Designing Tier 3 inside
  the cooldown is the rationalize-forward failure mode the
  not-doing list was set up to prevent.
- **No new strategies, MARL revival, live re-arming, or paid-data
  subscriptions inside the cooldown.**
- **Parallel skill track absorbs the time:** Hou/Xue/Zhang (2020)
  + Bailey/López de Prado (2014) + math foundations + the PIT
  universe blog post + the MARL rigor blog post.
- **Substrate-change reassessment memo lands 2026-06-01.** That
  memo asks: is the cross-sectional equity factor + linear
  combination + parametric cost construction class the right
  substrate at all, or should the founder path pivot to futures,
  market-making, options, crypto, or away from systematic alpha
  entirely?

The substrate-change memo IS the unblock for the next decision.
It is the only AlphaForge artifact that should land before
2026-06-01.

---

## 6. What this means for the founder path

The founder-trader path described in our 4-8 year plan does NOT
collapse on a Tier 1 + Tier 2 double failure. Three honest reads:

1. **The first signal class tested didn't pan out.** That's
   information about the construction class, not about the
   founder path. Most signal classes don't pan out; the
   replication literature (Hou/Xue/Zhang, Harvey/Liu/Zhu) puts
   the failure rate at ~64%. Tier 1 + Tier 2 are one data point
   in that distribution, not a personal verdict.

2. **The infrastructure built during Tier 1 + Tier 2 is reusable.**
   The PIT universe stack, the gauntlet kernel, the alpha layer,
   the cost model module, the bootstrap CI machinery — all of it
   transports to a substrate-change pivot. The work was not wasted.

3. **The honest negative result is itself a credibility-generating
   artifact.** A first-year non-target undergrad who shipped a
   PIT universe + ran a deflation-aware gauntlet + correctly
   diagnosed the failure mode + paused the project rather than
   rationalizing forward is doing something most quant
   undergrads can't articulate, let alone execute. That's the
   public artifact from Phase 6 + this verdict + the substrate-
   change memo, taken together.

The founder-trader path's year-0-2 work was: ship one signal that
passes the gate. It didn't happen on equity factor combinations.
The right next question (asked on 2026-06-01, not before) is:
**what substrate has higher prior probability of producing such a
signal at the founder-trader scale?** Possible answers include
asset class pivots, microstructure pivots, or a different research
methodology entirely. None of those are decided here.

---

## 7. The closing pre-commit

If, during the 2026-05-02 → 2026-06-01 cooldown, the impulse to
"just try one more thing on AlphaForge" arises, the pre-committed
answer is **no**. The cooldown is not a punishment; it is the
discipline that lets the substrate-change memo be a real reset
rather than another rationalization. The cooldown rule is
absolute. Re-engagement happens 2026-06-01 with the memo, not
sooner with a new strategy idea.
