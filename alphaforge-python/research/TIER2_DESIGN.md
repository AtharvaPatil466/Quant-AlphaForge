# Tier 2 Design — Lower-Turnover MV-Class Gauntlet on Free Data + Forward Paper-Trade

**Status:** Design draft 2026-05-02 (path-1, $0-cost version)
**Owner:** Atharva Patil
**Lifecycle:** Implementation must conform to this memo; deviations
require updating this document first.
**Predecessors:** `PHASE6_WRITEUP.md` (Tier 1 final writeup, gate
FAILED on row 2), `TIER1_STATUS.txt` failure-path matrix.
**Inherits from:** `PHASE6_WRITEUP.md` §7 (Tier 2 one-pager).
**Total budget:** ~10 calendar months, ~210 hours alongside coursework.
**Direct cash cost: $0.** Operates on the existing Tier 1 free pipeline
(PIT S&P 500 + yfinance OHLCV + Corwin-Schultz + square-root impact).

---

## 1. Why this memo exists

Tier 1 closed with the binary gate FAILED and the diagnostic
committed to **row 2 of the failure-path matrix**:

> "IC > 0 raw + residualized but net Sharpe ≤ 0 → real signal eaten
> by costs / multiple-testing → EXECUTION PROBLEM — lower turnover,
> futures/FX."

Tier 2 tests the row-2 hypothesis on the same PIT S&P 500 substrate
Tier 1 used. Specifically: **does the MV-class signal that
almost-passed Tier 1 actually survive when (a) deflation pressure is
reduced via a smaller pre-registered trial set, (b) turnover is
structurally lower so the cost charge is less load-bearing, (c)
extra free statistical power is recovered via three explicit
mitigations, and (d) the result has to hold up on genuinely forward
data the deflation framework cannot itself test against?**

The originally-considered Russell 1000 paid-data variant of Tier 2
is deferred. Estimated "loss" from running on free PIT S&P 500 only:
~15-25% test power, mitigable to ~10-15% with the three free moves
in §5. The R1k path remains available as a Tier 2.5 contingency if
the path-1 verdict is borderline.

Tier 2's gate is binary, like Tier 1's. Pass means a real,
replicated, deflation-survivable signal that gets paper-traded as
the falsifier. Fail means transition to the founder-path year-2-4
reset described in §7.

---

## 2. The Tier 2 binary gate (pre-committed)

A strategy passes Tier 2 when **all four** of the following hold:

1. **DSR > 0.95 in both OOS windows**, deflated against a
   pre-registered trial set of size ≤ 8 (vs. Tier 1's 24).
2. **Stationary-bootstrap 95% Sharpe CI excludes zero in both OOS
   windows** (4,000 reps, mean block 21d).
3. **Sign of OOS Sharpe agrees** between the two windows.
4. **Forward paper-trade Sharpe with bootstrap CI excluding zero**
   over a calendar 6-month window of capital that was not part of
   any optimization. The window cannot be compressed.

Conditions 1-3 mirror Tier 1's pre-committed gate; condition 4 is
the addition that addresses Tier 1's central methodological
limitation (DSR is a within-sample multiple-testing correction; it
does not test transport to genuinely new data).

**A strategy that clears 1-3 but fails 4 is not a survivor.** A
strategy that clears 4 but fails 1-3 is also not a survivor. Both
must hold.

---

## 3. The pre-committed strategy set (locked before any new code is written)

The single highest-leverage Tier 2 commitment is to **freeze the
trial set before any new gauntlet is run**. The Tier 1 trial count
of 24 was the binding deflation constraint; the only way row 2 has
a real shot is to test fewer, more targeted strategies.

**The 8 pre-committed strategies (all on PIT S&P 500, all free):**

| # | Strategy | Rebalance | Window start | Construction tweak |
|---:|---|---|---|---|
| 0 | MV-baseline (Tier 1 replication) | 21d | 2016-01-04 | none — sanity replication, *does not count toward the 8* |
| 1 | MV-63 | 63d | 2016-01-04 | quarterly rebalance, vanilla |
| 2 | MV-126 | 126d | 2016-01-04 | semi-annual rebalance, vanilla |
| 3 | MV-63-volcap | 63d | 2016-01-04 | target portfolio vol = 8% annualized |
| 4 | MV-126-volcap | 126d | 2016-01-04 | target portfolio vol = 8% annualized |
| 5 | MV-63-shrunk | 63d | 2016-01-04 | force Ledoit-Wolf δ ≥ 0.5 |
| 6 | MV-126-shrunk | 126d | 2016-01-04 | force Ledoit-Wolf δ ≥ 0.5 |
| 7 | MV-63-ext | 63d | **2010-01-04** | extended history; tests training-data quantity |
| 8 | MV-126-ext | 126d | **2010-01-04** | extended history + lower turnover, the "best prior" combo |

**No other strategies are evaluated.** This is the entire pre-
registered set. No grid search over rebalance horizons, no
exploratory sweeps over shrinkage parameters, no "let me just try
one more variant." The 8 strategies are the trials; the deflation
hurdle is computed against exactly 8.

**OOS windows are inherited from Tier 1, unchanged**:
OOS-A 2022-01-03 → 2023-12-29, OOS-B 2024-01-02 → 2025-12-31.
The "extended history" strategies (7, 8) gain training data, not
test data.

---

## 4. Tier 2 Phase 1 — Free-data sanity + extended-history substrate (months 1-2)

### 4.1 Replicate the Tier 1 MV result on the post-bug-fix stack

Run strategy 0 (MV-21, the Tier 1 baseline, replicated). Compare
OOS Sharpes and alpha metrics against the Tier 1 numbers in
`PHASE6_WRITEUP.md` §4.4. **Acceptance: replicated values within
5% of post-fix Tier 1 numbers.** If they diverge meaningfully, halt
and investigate (most likely cause: residualization-wiring bug
regression or a yfinance restatement of historical OHLCV).

### 4.2 Extended-history substrate (2010-01-04 onward)

The PIT universe stack already covers 2010 onward. The blocker for
Tier 1 was that the manifest's `usable_start` dates for several
tickers were post-2016. Tier 2 lifts that constraint by:

- Running a coverage audit on each ticker for 2010-2015. Drop any
  ticker with > 30 missing trading days in that window.
- Recomputing the cross-sectional usable universe per date as the
  intersection of (PIT membership × non-missing OHLCV).
- Documenting the usable-universe size as a function of date in
  `tier2_universe_audit.json`. Expect ~350-400 names usable in the
  2010-2015 extended window vs. 476 in the 2016-2025 window.

### 4.3 Cost-model sanity check (no recalibration; documented as-is)

Tier 1 used a parametric cost model (1bp commission + 2bp
half-spread + 10bp/turnover linear impact). Tier 2 keeps these
parameters unchanged but adds a comparison of the parametric
half-spread against the Corwin-Schultz estimator from
`research/cost_model.py` over the extended window. Document the
agreement/disagreement; do NOT re-fit parameters mid-Tier-2.

### 4.4 Phase 1 deliverables

- `tier2_phase1_replication.json` — strategy 0 numbers vs Tier 1.
- `tier2_universe_audit.json` — per-date usable universe counts
  for the extended window.
- `tier2_phase1_cost_check.md` — Corwin-Schultz vs parametric
  half-spread comparison.
- Halt-gate decision: if §4.1 or §4.2 surfaces a structural
  problem (e.g., yfinance restatements have invalidated the
  Tier 1 results, or the extended-history coverage is too
  sparse to support strategies 7-8), the offending strategies
  are dropped from the trial set and the trial count is
  reduced accordingly. Otherwise, proceed.

**Phase 1 budget:** ~30 hours / 2 months. Mostly coverage audit +
the replication compare. No new research.

---

## 5. Tier 2 Phase 2 — The lower-turnover gauntlet (months 2-5)

### 5.1 Run the 8 strategies through the Tier 1 gauntlet, with three free power-recovery mitigations

Same gauntlet as Tier 1 (DSR + stationary-bootstrap + Hansen SPA +
White's RC + purged-embargoed CV + post-portfolio FF5+UMD alpha
via `compute_portfolio_alpha`), with three modifications that
recover free statistical power:

1. **Sector-stratified IC computation.** The existing
   `sector_neutralize` helper in `factor_study.py` becomes the
   default path for all 8 strategies, not the secondary variant.
   This boosts cross-sectional dispersion within sectors and
   reduces the effective N penalty from running on the smaller
   S&P 500 vs. R1k.
2. **4,000 bootstrap reps** instead of the Tier 1 default 2,000.
   Doubles bootstrap-CI precision; nearly free in compute (~2x
   wall-clock on a 2s-per-strategy step).
3. **Extended-history strategies (7, 8) explicitly receive the
   2010-2015 training data as additional in-sample**, with the
   same 21-day embargo before OOS-A. This recovers most of the
   power lost from the smaller universe.

The Tier 1 trial set (24 trials) is **not** rolled into Tier 2's
deflation. The pre-commitment is a fresh 8-strategy trial set; the
Tier 1 trial set is what generated the row-2 diagnostic, not a
candidate set for Tier 2.

### 5.2 Phase 2 gate decision

End of month 5: apply conditions 1-3 of the §2 gate to each of the
8 strategies. Three pre-committed outcomes:

- **≥ 1 strategy clears 1-3:** advance the strategy with the
  highest alpha-residual residual Sharpe to Phase 3 (forward
  paper-trade). If multiple clear, advance the *single* strategy
  with the highest DSR — not an ensemble.
- **0 strategies clear 1-3 but at least one has alpha-residual
  Sharpe ≥ +1.5 in both windows:** activate the Tier 2.5
  contingent in §6.3 (NOT a return to grid-searching the equity
  space).
- **0 strategies clear 1-3 and none has alpha-residual Sharpe
  ≥ +1.5 in both windows:** Tier 2 has FAILED. Transition to §7.

### 5.3 Phase 2 deliverables

- `research/out/tier2_phase2_results.json` and
  `tier2_phase2_gate.{json,md}`, same shape as the Tier 1
  phase4_gate / phase5_gate outputs.
- `TIER2_PHASE2_VERDICT.md` memo committing to one of the three
  outcomes above with the data table that supports the commit.

**Phase 2 budget:** ~50 hours / 3 months. The gauntlet kernel
already exists; this is configuration + execution + writeup.

---

## 6. Tier 2 Phase 3 — Forward paper-trade (months 5-11)

### 6.1 The forward window

The single Phase-2 survivor (or the first Tier 2.5 contingent
survivor if §6.3 is activated) is traded forward on **paper capital
that was not part of any Tier-1 or Tier-2 optimization**, for a
calendar 6-month window. The window starts the day after the
Phase 2 gate decision is committed and runs uninterrupted.
**No mid-window changes to weights, parameters, or universe.**

The capital baseline: **$25K notional paper account**. Sized to
match the realistic personal-capital deployment scale at the end
of undergrad (per the founder-path year-0-2 capital target). At
$25K notional, a 21d-rebalance signal trades ~$5K per name at
current S&P 500 prices — small enough to model real round-lot
constraints honestly.

### 6.2 The Phase 3 gate

At the end of the 6-month window, compute:

- Realized annualized Sharpe of the live paper book.
- Stationary-bootstrap 95% CI on the realized Sharpe (4,000 reps).
- Realized vs. expected return decomposition (the part owed to
  the strategy's pre-registered alpha vs. the part owed to
  unmodeled costs / slippage / regime shift).

**Pass:** realized Sharpe with 95% bootstrap CI excluding zero AND
realized Sharpe within 1 standard deviation of the Phase 2
expected Sharpe (i.e., the strategy transports without major
degradation).

**Fail:** realized Sharpe with CI bracketing zero, OR realized
Sharpe more than 1 standard deviation below Phase 2 expected
(strategy degrades on forward data).

### 6.3 The Tier 2.5 contingent

Activated only if §5.2 outcome 2 occurs (Phase 2 has a near-miss
but no formal pass). One additional pre-committed test:

- **MV-126-R1k**: same MV recipe, 126d rebalance, on Russell 1000
  via paid data (Norgate or equivalent, ~$60-80/mo for one
  quarter of subscription = ~$240 cash cost). The single strongest
  combo from the originally-considered paid-data set.

This becomes the 9th and final pre-committed trial; the Tier 2
trial set expands to 9. DSR is recomputed against 9. If
MV-126-R1k clears, it advances to Phase 3 paper-trade. If it does
not, Tier 2 has FAILED and §7 applies.

The Tier 2.5 contingent is one bullet, not a phase. It is a single
pre-registered fallback strategy that costs ~$240 of paid-data
subscription to evaluate. Not an invitation to explore the R1k
space; one shot.

### 6.4 Phase 3 deliverables

- `tier2_phase3_paper_trade.{json,md}`: daily NAV, realized vs
  expected, Sharpe + bootstrap CI.
- `TIER2_VERDICT.md`: the final Tier 2 binary outcome.
- If pass: handoff memo to the founder-path year-2-4 plan
  (real-capital deployment).
- If fail: handoff memo to §7.

**Phase 3 budget:** ~70 hours / 6 months. Most hours are weekly
monitoring + the end-of-window analysis. The trading itself runs
on the existing live-execution stack (currently `.halt`'d) once
re-armed for paper trading only.

---

## 7. The honest pre-commit on Tier 2 failure

If the Tier 2 gate also fails — i.e., 0 of the 8 (or 9 with the
Tier 2.5 contingent) strategies clear conditions 1-3, OR a
Phase 2 survivor fails the Phase 3 forward paper-trade —
**transition to the founder-path year-2-4 reset** rather than
immediately designing Tier 3.

The founder-path year-2-4 reset, per the broader plan, is:

- Stop new gauntlet design for at least 30 days. Avoid
  "rationalize-forward" failure mode.
- Audit which of the parallel-skill-track artifacts (math
  foundations, papers, blog posts, competitions) are
  underdeveloped and rebalance time toward them for one quarter.
- Reassess whether the AlphaForge construction class (cross-
  sectional equity factors + linear combinations + standard
  costs) is the right substrate for the founder path at all,
  or whether a substrate change (futures, crypto, market-making,
  options) is the right Tier 3 question.
- This reassessment is a memo, not a gauntlet. It precedes any
  Tier 3 design.

**Tier 3 does not exist yet and should not be designed before
the §7 reassessment lands.** Designing Tier 3 in advance would be
the same failure mode (rationalizing forward) that Tier 1
§"explicit not-doing list" guarded against.

---

## 8. Tier 2 not-doing list (mirrors Tier 1 §"explicit not-doing list")

- **No strategy beyond the 8 (+ 1 Tier 2.5 contingent) pre-committed
  in §3 and §6.3.** This is the central deflation discipline; any
  expansion silently inflates the trial count and undoes the row-2
  fix's whole rationale.
- **No new factors beyond the 9 from Tier 1.** The MV recipe is
  defined over those 9; adding factors expands the within-strategy
  search space.
- **No new universe substrates** unless the §6.3 contingent
  activates. No Russell 2000, no international, no crypto, no
  futures.
- **No re-tuning of OOS windows.** OOS-A and OOS-B are inherited
  unchanged.
- **No new MARL work.** Same reason as Tier 1 plus row-2 doesn't
  implicate model capacity.
- **No live execution with real capital.** Paper trading only,
  including in Phase 3. Real-capital deployment is a founder-path
  year-2-4 question, not a Tier 2 question.
- **No paid data** unless §6.3 contingent activates. The path-1
  premise is exactly $0 cash cost through Phase 2; the Tier 2.5
  contingent is the single permitted exception.
- **No fund-name brainstorming, LP-courting, or "personal brand"
  work.** Same constraint as Tier 1.
- **No premature engineering polish** (Docker, k8s, framework
  migration). The Tier 1 stack is fit for purpose.
- **No relaxing the Tier 2 gate ex-post.** Conditions 1-4 in §2
  are the gate. If a strategy almost-passes but doesn't, that's
  the same answer as failing badly.

---

## 9. What gets reused vs. extended vs. rebuilt

| | What | Why |
|---|---|---|
| **Reused** | PIT universe stack, gauntlet kernel (DSR / SPA / RC / purged CV / bootstrap), cost-model module, FF5+UMD residualizer (post-fix), `compute_portfolio_alpha`, `phase5_combine.py:mv_weights` | Tier 1 stack is fit for purpose |
| **Extended** | Universe coverage audit for 2010-2015, turnover-penalized portfolio construction (currently 21d only — needs 63d / 126d variants), volcap and shrunk-LW MV variants, forward paper-trade harness | Required by §3 / §4 / §6 |
| **Rebuilt** | Nothing | If something needs a rebuild, that's a Tier 2 design failure |

The execution-stack `.halt` file stays engaged through Tier 2
Phase 1 and Phase 2. It gets removed only at the start of Phase 3
and only for paper trading on the Phase-2 survivor.

---

## 10. Implementation timeline (months from Tier 2 Phase 1 start)

```
Month  1-2:  Phase 1 — replicate Tier 1 MV + extended-history
                       universe audit + cost-model sanity check
Month  2-5:  Phase 2 — run 8 (or 9 with §6.3) strategies through
                       gauntlet + Phase 2 gate decision memo
Month  5-11: Phase 3 — forward paper-trade survivor on $25K notional
                       + Phase 3 gate decision memo + TIER2_VERDICT.md
```

If Phase 2 outcome 3 occurs (clean fail with no near-miss), Phase 3
is skipped; Tier 2 ends at month 5 with the failure writeup and
the §7 reset. Total Tier 2 time in that case: ~5 months, ~80 hours.

---

## 11. What this memo does not cover

- **Tier 3.** Per §7, by design.
- **Tier 2.5 R1k subscription logistics.** If §6.3 activates, the
  paid-data evaluation gets its own one-page memo at activation
  time, not pre-drafted now.
- **The Tier 2 publication artifact.** A short blog post or repo
  writeup is appropriate at the end of Phase 2 regardless of
  outcome (continuing the parallel-skill-track public-artifact
  cadence Tier 1 established). Format and venue decided at that
  point.
- **Real-capital deployment.** Founder-path year-2-4 work, not
  Tier 2.

---

## 12. Dependency on the parallel skill track

Tier 1 plan §"PARALLEL SKILL TRACK" carries forward unchanged. The
non-negotiable 5-8 hrs/week on math foundations + one paper every
two weeks + one blog post per month + competition placement
continues alongside Tier 2 work.

The week of the Phase 2 gate decision and the week of the Phase 3
gate decision are the two natural moments to write a public blog
post. Both should be planned for in advance.

The founder-path capital target ($25K trading capital + 6 months
living expenses by end of undergrad) is also tracked in parallel;
the Phase 3 paper-trade size is set to match that target so Phase 3
results transport directly to year-2-4 real-capital deployment if
the gate clears.
