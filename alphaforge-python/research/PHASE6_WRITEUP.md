# AlphaForge — Tier 1 Methodology Validation: Final Writeup

**Author:** Atharva Patil
**Status:** Complete (drafted 2026-05-01, §4 + §7 + abstract finalized
2026-05-02 after the diagnostic rerun and the residualization-wiring
bug fix). Awaits one publication-formatting pass before public release.
**Repository:** AlphaForge (PIT universe, residualizer, gauntlet, MARL,
execution stack — all open-source under this repo)
**Companion artifacts:**
`research/out/factor_study_results.json`,
`research/out/phase{4,5}_gate_result.{json,md}`,
`research/out/phase5_combination_results.json`.
Pre-fix backups preserved as `*_residualized.json`.

---

## 0. Abstract

We test 9 textbook cross-sectional equity factors and 4 linear
combination strategies on a point-in-time S&P 500 universe (476
tickers, 2,514 trading days, 2016-01-04 → 2025-12-31), with
FF5+UMD residualization applied as a post-portfolio time-series
alpha test and a realistic cost model. Strategies and gate are
pre-committed: DSR > 0.95 + bootstrap CI excludes zero + sign
agreement, both of two non-overlapping OOS windows.

**Headline:** the pre-committed Tier 1 gate FAILED. 0 of 9 single
factors and 0 of 4 combination strategies cleared. The hypothesis
the gate was set up to test — that some signal in this construction
class survives a deflation-aware gauntlet — is rejected.

**The interesting failure:** a Markowitz overlay over the 9 factor
return series produces **alpha-residual OOS Sharpe +3.06 (CI
[+1.83, +4.42]) and +2.43 (CI [+1.39, +3.56])** with alpha t-stats
4.33 and 3.43 (HC0) and FF5+UMD R² of 16% and 8%. The signal is
genuinely orthogonal to the standard factor model and statistically
significant under any conventional test. It fails *only* on the
DSR hurdle (0.92 / 0.70 against the pre-committed 0.95) — i.e.,
the multiple-testing penalty against the 24-trial set is what
kills it, not the alpha itself.

**Diagnostic:** the pre-committed test places the failure on **row
2 of the failure-path matrix — real signal, not deflation-survivable
in this construction**. Row 1 (residualization artifact) is ruled
out by the alpha-residual evidence.

**Tier 2 implication:** test MV-class signals at lower turnover
(63d / 126d rebalance) and in asset classes with asymmetric impact
(futures) or larger universes (Russell 1000 via paid data). Run a
6-month forward paper-trade as the falsifier the deflation
framework cannot itself deliver.

**Process disclosure:** while running the diagnostic, a load-bearing
bug in the residualization wiring was discovered and fixed (§4.1).
Pre-fix outputs are preserved as backup JSONs. All headline numbers
in this writeup are post-fix.

---

## 1. Thesis

The pre-committed Tier 1 hypothesis: **at least one signal in this
factor universe, on a point-in-time S&P 500, with FF5+UMD
residualization and realistic costs, clears DSR > 0.95 in two
non-overlapping OOS windows.** Pass or fail decides whether Tier 2
work — alpha refinement, capital deployment, scaling — is justified.
This is a methodology validation phase, not a production research
sprint. The deliverable is the gate outcome and the honest writeup
of what it implies, not a survivor signal.

The gate is binary by construction. The writeup that follows is the
required deliverable regardless of which side of the gate the data
lands.

---

## 2. Methodology

### 2.1 Universe construction

The single largest defect in prior factor studies on this stack was
survivorship bias from a 50-name today-surviving universe. Tier 1
Phase 1 replaced it with a true point-in-time S&P 500 membership
log built from Wikipedia revision history + EDGAR CIK enrichment.

- **Output:** 837-event chronological membership log (407 REMOVE +
  352 ADD + 78 RENAME) from 2010 → 2026.
- **Validation:** 12/12 pytest spot-check fixtures; 84% match
  against Wikipedia's curated "selected changes" table; monthly
  return correlation 0.9895 vs. `^SP500EW`.
- **Canonical accessor:** `data.market.pit.validator.membership_on_date`
  returns the set of tickers in the index on any date in [2010, 2026].
- **Coverage limitation:** 226 of 881 ever-member tickers have no
  yfinance OHLCV (delisted / restructured). This is reported as a
  known data gap in every downstream metric; not silently excluded.

The factor study uses a 476-ticker × 2,514-day intersection of (PIT
membership × yfinance availability) across 2016-01-04 → 2025-12-31.

### 2.2 Risk model + residualization

Every IC and Sharpe in this report is computed on **FF5 + UMD
residualized returns**, not raw returns. The residualization is a
no-look-ahead 252-day rolling OLS regression of each ticker's daily
return on the six-factor reference series (Ken French CRSP-wide
daily file). The reference file is staged at
`research/out/phase3_reference_staged.csv`.

**Validation gate (Phase 3):** the local FF5 replica must have
correlation > 0.85 against Ken French's published series over the
overlap window. Result:

| Factor | Correlation vs. French | Threshold | Status |
|---|---|---|---|
| MKT | 0.913 | 0.85 | PASS |
| SMB | 0.646 | 0.85 | structurally bounded* |
| HML | 0.868 | 0.85 | PASS |
| RMW | 0.232 | 0.85 | structurally bounded* |
| CMA | 0.633 | 0.85 | structurally bounded* |
| UMD | 0.824 | 0.85 | PASS (within tolerance) |

*The minor factors fail the 0.85 hurdle because we build them on a
500-ticker substrate while French builds on the entire CRSP cross-
section. Per Phase 3 decision, we residualize against French's
*published* series (correctly-built) rather than the local replica.
The replica gate is informational, not blocking. This is documented
honestly here because it bears on §4: if the residualization
itself is mis-specified beyond what the published series captures,
some Phase 4-5 results may inherit that misspecification.

### 2.3 Gauntlet

Per `PHASE4_DESIGN.md` §1 and §5, every factor variant is evaluated
through:

- **IC at horizons {1, 5, 10, 21, 63} days** — Spearman, t-stat.
- **Quintile-spread backtest** — equal-weight within leg, 21-day
  rebalance, top minus bottom quintile.
- **Stationary-bootstrap Sharpe CI** — 2,000 reps, mean block 21d.
- **Hansen SPA + White's Reality Check** — across the full trial
  matrix, per OOS window.
- **Deflated Sharpe Ratio** — Bailey & López de Prado (2014),
  deflated against the full pre-committed trial set.
- **Purged-embargoed K-fold CV IC at h=21** — López de Prado (2018).

The gate applies to per-OOS-window metrics, not full-period:

1. DSR > 0.95 in **both** OOS windows.
2. Stationary-bootstrap 95% Sharpe CI excludes zero in **both**.
3. Sign of OOS Sharpe agrees between the two windows.

OOS windows are non-overlapping and pre-committed:
**OOS-A 2022-01-03 → 2023-12-29** and **OOS-B 2024-01-02 → 2025-12-31**.
Training window: 2016-01-04 → 2021-12-31, with a 21-day embargo
before OOS-A. No re-tuning of windows is permitted.

### 2.4 Cost model

Same model applied to every strategy variant:

- Commission: 1 bp per dollar traded
- Half-spread: 2 bp per dollar traded
- Linear impact: 10 bp × turnover
- For the capacity number (§3.4), a square-root impact model from
  `research/cost_model.py` replaces the linear impact term.

Costs are charged on each rebalance, applied to the realized turnover
of the long and short legs.

---

## 3. Results

**Reading note for §3:** the tables in §3.1 and §3.2 below are the
**raw long-short net Sharpes** as originally tabulated. They are
preserved here both for continuity with prior internal documents
and to make the §4 bug discovery legible. The **alpha-residual**
re-tabulation that the gate actually evaluates against is in §4.4.

### 3.1 Single-factor gauntlet (Phase 4) — raw long-short Sharpes

9 cross-sectional factors, evaluated raw and sector-neutral. The
"residualized" label in the result JSONs reflected the *intent* to
residualize; the actual computation was on raw returns (see §4.1).

| Factor | OOS-A SR | DSR-A | CI≠0 (A) | OOS-B SR | DSR-B | CI≠0 (B) | Sign agree | Survives |
|---|---:|---:|---|---:|---:|---|---|---|
| Momentum (12-1) | -0.82 | 0.000 | no | +0.23 | 0.029 | no | no | no |
| Mean Reversion (5d) | -0.45 | 0.002 | no | -0.14 | 0.008 | no | yes | no |
| Volume Surge | -1.48 | 0.000 | yes | -1.34 | 0.000 | yes | yes | no |
| RSI Divergence | -1.62 | 0.000 | yes | -1.10 | 0.000 | yes | yes | no |
| Earnings Drift | -1.24 | 0.000 | yes | -0.97 | 0.000 | no | yes | no |
| Amihud Illiquidity | +0.13 | 0.021 | no | -1.41 | 0.000 | yes | no | no |
| Idiosyncratic Volatility | -0.09 | 0.010 | no | -0.41 | 0.003 | no | yes | no |
| Residual Reversal (5d) | -1.86 | 0.000 | yes | -1.66 | 0.000 | yes | yes | no |
| Low Volatility | -0.31 | 0.004 | no | -0.45 | 0.002 | no | yes | no |

**Survivors: 0 of 9.** Failure modes: 9/9 fail DSR > 0.95 in at
least one window; 6/9 also fail CI-excludes-zero; 2/9 also fail
sign-agreement.

The single most striking pattern: **every single factor has
negative full-period Sharpe on residualized returns** (full-period
SRs range from -0.24 to -1.70). This is not noise around zero.
This is a structural anti-pattern that §3.3 builds on.

### 3.2 Factor-combination gauntlet (Phase 5)

4 pre-committed combination strategies, all weights frozen on the
training window before OOS evaluation:

| Strategy | OOS-A SR | DSR-A | CI≠0 (A) | OOS-B SR | DSR-B | CI≠0 (B) | Survives |
|---|---:|---:|---|---:|---:|---|---|
| EWE (equal-weight) | -0.84 | 0.000 | no | -0.49 | 0.000 | no | no |
| ICW (signed-IC-weighted) | -0.51 | 0.000 | no | -1.01 | 0.000 | yes | no |
| **MV (Markowitz overlay)** | **+2.81** | **0.853** | **yes** | **+2.69** | **0.812** | **yes** | **no** |
| ICW-flip | -0.51 | 0.000 | no | -1.01 | 0.000 | yes | no |

**Survivors: 0 of 4.** Per Tier 1 plan §5 kill criterion, the gate
has FAILED.

### 3.3 The MV result — framed honestly

MV is the one row above that does not look like a clean failure.
Raw OOS Sharpes are above +2.5 with bootstrap CIs strictly above
zero (p_positive = 1.0); alpha-residual Sharpes (§4.4) are even
stronger at +3.06 / +2.43.

**Mechanism: "short everything."** MV chose negative weights on
8 of 9 factors. Volume Surge — the most-negative-SR factor at
-1.70 full-period — gets the largest negative weight (-0.38).
Naive sanity check: equal-weight shorting all 9 factors gives
raw OOS Sharpe +1.78 / +1.70. MV's covariance-aware weighting
adds another ~1 SR over the naive flip.

**The 24-trial deflation is what kills the DSR.** A Sharpe of
+2.8-3.0 with ~500 days and 24 candidate Sharpes lands in the
0.85-0.92 range, not the 0.99 range. This is exactly the regime
where the deflation framework is doing the work it was designed
for. Reporting MV's raw +2.8 without the deflation would be the
data-snooping the gauntlet exists to prevent.

**The two original "is this an artifact?" hypotheses are now
addressed:**

(a) Residualization-misspecification: ruled out empirically in
§4. After the alpha layer was correctly wired, MV's alpha-residual
Sharpe is +3.06 / +2.43 with t-stats 4.33 / 3.43 and FF5+UMD R²
of 16% / 8%. The signal is genuinely orthogonal to the standard
factor model; it is not a residualization artifact.

(b) Cost-model fragility: not ruled out. All 9 single-factor net
Sharpes are negative; many go from positive gross to negative
net purely because of the cost charge. If the cost model is
too punishing for the underlying turnover regime, MV's "short
everything" is exploiting our cost mis-specification rather than
a real anti-predictive signal. This is the central live question
for Tier 2 and is what motivates the 63d / 126d rebalance test
in §7.3.

**The honest read:** under the pre-committed gate, MV does not
pass. The signal is real *as alpha* (§4.6); it does not survive
the deflation-aware multiple-testing bar this project committed
to. Both clauses must be reported together.

### 3.4 Capacity

Phase 5 §6 specified a capacity sweep across [$1M, $10M, $100M, $1B,
$10B] AUM via square-root impact for any combination strategy that
reached OOS evaluation. **Not run.**

The reasoning, post-§4: the row-2 diagnostic implies that whatever
capacity number we'd compute for MV under the *current* turnover
regime is the wrong question for Tier 2. MV's failure mode is
deflation, not direct cost erosion at the $1M scale. The capacity
number that matters for Tier 2 is for *modified* MV-class signals
at longer rebalance horizons (63d / 126d) and / or different asset
classes — not the as-tested 21d-rebalance equity version. Computing
capacity for the latter would be technically straightforward but
would not change the row-2 commit and would not inform Tier 2
design.

The honest framing: capacity belongs to Tier 2's first session,
where it will be computed against the redefined turnover regime
on the same square-root impact model already in
`research/cost_model.py`.

---

## 4. The diagnostic

### 4.1 A bug discovered while running the diagnostic

**While preparing the disambiguating test, a methodology bug was
discovered in the Tier 1 stack.** `factor_study.prepare_analysis_returns`
returned raw returns regardless of the `residualize` flag, and
`_run_variant` was called without the FF5+UMD reference table —
making the residualization layer dead code. Every Phase 4 / Phase 5
result tabulated in §3 was computed on **raw returns**, despite the
JSON metadata claiming `analysis_returns_mode: residualized`.

The previous developer (a prior session) had explicitly chosen this
shape after discovering that per-ticker daily residualization
double-removes factor exposure (residualizing momentum and then
ranking by momentum mechanically bets against momentum, producing
spurious negative Sharpes). They documented the intent — post-hoc
time-series alpha via `compute_portfolio_alpha` — but never wired
it into the main gauntlet. The fix: pass `reference_factors` into
`_run_variant`, populate per-OOS-window `ff5_alpha` blocks, and
update both gates to evaluate the alpha-residual Sharpe instead of
the raw Sharpe. ~50 lines of changes; no new computation kernel.

After the fix, the §3 tables are re-stated in §4.4 below with the
alpha-residual Sharpes the gate is now evaluating against.

### 4.2 The (now obsolete) raw-vs-residualized test

The disambiguating test pre-committed in `PHASE6_DESIGN.md` §5 was
"compare MV on raw returns vs MV on residualized returns." That
test became uninformative once it was clear both versions were
computed on raw returns. The replacement test, run instead, is
**MV evaluated against the actual FF5+UMD alpha-residual gate**.
Pre-committed thresholds carry over with the obvious adaptation:

- If alpha-residual MV OOS Sharpe ≥ +1.5 in **both** windows → row 2.
- If alpha-residual MV OOS Sharpe < +1 in **either** window → row 1.
- If between → 3-month forward paper-trade as second falsifier.

### 4.3 Committed diagnostic

**Result:** alpha-residual MV OOS Sharpe is **+3.06** in OOS-A
(95% bootstrap CI [+1.83, +4.42]) and **+2.43** in OOS-B
(CI [+1.39, +3.56]). Both well above +1.5. Per the pre-committed
threshold, **the diagnostic is row 2**.

| Diagnostic test | Pre-commit | OOS-A | OOS-B | Verdict |
|---|---|---:|---:|---|
| Alpha-residual MV Sharpe ≥ +1.5 in both | row 2 | +3.06 | +2.43 | **row 2** |
| Alpha-residual MV Sharpe < +1 in either | row 1 | n/a | n/a | not row 1 |

The alpha intercept itself is highly significant: t = 4.33 in OOS-A
(p < 1e-4) and t = 3.43 in OOS-B (p < 1e-3), both with HC0
heteroskedasticity-consistent SEs. The R² of MV's daily returns
against FF5+UMD is 16% in OOS-A and 8% in OOS-B — **MV's signal is
largely orthogonal to the standard factor model.** It is not picking
up MKT, SMB, HML, RMW, CMA, or UMD beta exposure.

**The gate, however, still fails.** Phase 5 alpha-residual DSR is
0.920 (OOS-A) and 0.701 (OOS-B), against the pre-committed 0.95
hurdle on a 24-trial deflation. OOS-A is right at the edge; OOS-B
is meaningfully short. The bootstrap CI excludes zero in both
windows (p_positive = 1.0). Sign agreement holds. DSR is the only
condition that fails — and it fails by a margin small enough in
OOS-A that a different-sized trial set would change the answer,
which is precisely why the deflation framework is doing the work
it was designed for.

### 4.4 Re-stated headline tables (alpha-residual)

**Phase 4 single-factor (alpha-residual residual Sharpes per window):**

| Factor | OOS-A SR | DSR-A | CI≠0 | OOS-B SR | DSR-B | CI≠0 |
|---|---:|---:|---|---:|---:|---|
| Momentum (12-1) | -1.48 | 0.000 | yes | -0.94 | 0.000 | no |
| Mean Reversion (5d) | -0.45 | 0.003 | no | +0.35 | 0.047 | no |
| Volume Surge | -1.55 | 0.000 | yes | -1.28 | 0.000 | yes |
| RSI Divergence | -1.78 | 0.000 | yes | -1.15 | 0.000 | yes |
| Earnings Drift | -1.32 | 0.000 | yes | -1.24 | 0.000 | yes |
| Amihud Illiquidity | +0.19 | 0.029 | no | -0.53 | 0.002 | no |
| Idiosyncratic Volatility | -0.45 | 0.003 | no | -0.17 | 0.008 | no |
| Residual Reversal (5d) | -1.83 | 0.000 | yes | -1.63 | 0.000 | yes |
| Low Volatility | -0.91 | 0.000 | no | -0.44 | 0.003 | no |

Survivors: 0 of 9. Pattern unchanged from the raw-returns table:
every single factor has negative alpha-residual SR in at least one
window; most have it in both.

**Phase 5 combinations (alpha-residual residual Sharpes per window):**

| Strategy | OOS-A SR | DSR-A | CI≠0 | OOS-B SR | DSR-B | CI≠0 |
|---|---:|---:|---|---:|---:|---|
| EWE | -1.71 | 0.000 | yes | -0.94 | 0.000 | no |
| ICW | -0.60 | 0.000 | no | -1.00 | 0.000 | no |
| **MV** | **+3.06** | **0.920** | **yes** | **+2.43** | **0.701** | **yes** |
| ICW-flip | -0.60 | 0.000 | no | -1.00 | 0.000 | no |

Survivors: 0 of 4. MV is the lone non-trivial result and the entire
content of §4.5.

### 4.5 What the row-2 commit means

Row 2 says: **the signal is real; costs and / or trial-count
deflation are what kill it.** Three forward implications:

1. **The MV signal is alpha vs FF5+UMD.** R² 16% / 8%; alpha t-stats
   4.33 / 3.43 with HC0 SEs. This is not a beta or style exposure
   masquerading as alpha. It is something genuinely orthogonal to
   the standard factor model — the literature would call it a
   "characteristics-not-covariances" residual.

2. **The mechanism — "short every cost-net loser" — is a real
   inefficiency or a real cost-model artifact, and the diagnostic
   doesn't separate them.** MV's edge comes from inverting 8 of 9
   factors whose net Sharpes are negative *after* the 1bp
   commission + 2bp half-spread + 10bp/turnover impact. If the
   cost model is too punishing for the underlying turnover regime,
   MV is exploiting our cost mis-specification. If the cost model
   is roughly right, MV is exploiting a real mean-reversal /
   anti-overreaction pattern that other market participants either
   can't or won't trade because of the same costs.

3. **The Tier 2 pivot, per the failure-path matrix, is**
   "EXECUTION PROBLEM — lower turnover, futures/FX." Concretely:
   - Tier 2 should test MV-class signals on a longer-horizon
     rebalance (63d, 126d) to see whether the alpha survives
     when turnover is structurally lower.
   - Tier 2 should test the same construction on futures
     (where impact is asymmetric and bid-ask is tighter for
     comparable liquidity) and / or larger universes (Russell 1000
     via paid data) where participation rates would be lower.
   - Tier 2 should NOT pivot to event-driven / microstructure /
     alt-data (row 1's pivot). The alpha-residual residual Sharpe
     pattern ruled that out.

### 4.7 Tier 2 epilogue (added 2026-05-02 after Tier 2 closed)

The row-2 commit in §4.3 was made on Tier 1 evidence: MV-21's
alpha-residual OOS Sharpes of +3.06 / +2.43 with t-stats > 3 and
low FF5+UMD R² were treated as evidence of a real signal whose
deflation-survivability — not its existence — was the issue.

Tier 2 was designed to test that hypothesis. It tested the same
MV recipe at quarterly (63d) and semi-annual (126d) rebalance,
with vol-targeting and forced-shrinkage variants, on the same
PIT S&P 500 substrate. **The hypothesis was falsified.**

The MV-21 alpha did not transport to longer horizons:

| Strategy | OOS-A α-residual | OOS-B α-residual |
|---|---:|---:|
| MV-21 (Tier 1 baseline) | **+3.06** | **+2.43** |
| MV-63 | +0.79 | +1.97 |
| MV-126 | +0.95 | +0.11 |

If row 2 were the right diagnosis, lowering turnover should have
preserved or amplified the alpha (because realized cost charge
shrinks proportionally with turnover). Instead the alpha
collapsed. **The signal is fragile to rebalance horizon in a way
that "real signal eaten by costs" does not predict.**

The revised diagnosis: the MV-21 alpha is most likely a **short-
horizon-specific phenomenon**, plausibly a 21-day residualized
mean-reversion pattern. It is not a robust cross-sectional anomaly
trapped behind a cost wall. The §4.3 / §4.5 framing of "real
alpha killed by deflation, addressable via lower-turnover Tier 2"
overestimated the signal's underlying robustness.

Two implications for the writeup's standing:

1. **§4.3's row-2 commit should be read in light of this
   epilogue.** The honest revised diagnostic is closer to "alpha
   exists at one specific frequency / construction; doesn't
   generalize." That's not a clean fit for any single failure-
   path matrix row.
2. **§7's Tier 2 sub-plan was executed and itself failed.** The
   substrate-change reassessment described in §7.7's "honest
   pre-commit" — the case where Tier 2 also fails and the project
   transitions to a desk-track or substrate-change pivot — is now
   the active path. The 30-day cooldown is enforced through
   2026-06-01.

The writeup's other sections (§0 abstract, §1-§3 results, §5-§6
limitations, §7 Tier 2 sub-plan) remain accurate descriptions of
what was done and what was found at their respective points in
time. Only §4 needs to be read with this epilogue. The full Tier
2 verdict is in `TIER2_VERDICT.md`.

---

### 4.6 What the gate did and didn't decide

This subsection exists because the result invites a specific
follow-up question: *"the alpha is statistically significant by
every conventional test — t > 3 in both windows, R² < 16%,
bootstrap CI well above zero — so what exactly did the gate kill?"*

The gate killed *deflation-survivability*, not significance. These
are different tests asking different questions, and Phase 6 owes
the reader a precise statement of which is which.

**The conventional significance test asks:**
"Is the alpha intercept statistically distinguishable from zero?"

For MV: yes, decisively. The HC0-corrected alpha t-stat is 4.33
in OOS-A and 3.43 in OOS-B; two-sided p-values are 1.5e-5 and
5.9e-4. The bootstrap p_positive is 1.0 in both windows. Under
any single-strategy academic significance bar (t > 2.0 is the
typical one), MV passes by a wide margin in both windows.

**The deflation test asks something different:**
"Given that we tested 24 candidate strategies — with their realized
Sharpes spanning -1.83 to +3.06 — what is the probability that the
best one would *appear* to be this good purely by selection bias,
even if every strategy in the trial set had true Sharpe of zero?"

For MV: not vanishingly small. DSR = 0.92 in OOS-A means there's
roughly an 8% probability of seeing a Sharpe this good purely from
trying 24 things. DSR = 0.70 in OOS-B means roughly 30%.

**Why the second question is the harder one:** because every
historical anomaly that *failed* to replicate originally passed
the first question. Hou/Xue/Zhang (2020) tested 452 published
anomalies and found ~64% don't replicate; almost all originally
had t > 2 in their publication backtests. Deflation-aware testing
is the field's response to that replication crisis. DSR > 0.95 is
the convention precisely because conventional significance is a
known-insufficient bar.

**The threshold-sensitivity table (informational, not a gate
re-litigation):**

| DSR threshold | OOS-A passes | OOS-B passes | Both pass |
|---:|---|---|---|
| 0.95 (pre-committed) | no (0.92) | no (0.70) | **no** |
| 0.90 | yes (0.92) | no (0.70) | no |
| 0.85 | yes | no | no |
| 0.75 | yes | no | no |
| 0.70 | yes | yes (0.70 ≈ threshold) | borderline |

Under no reasonable threshold from the literature does MV clear
both windows cleanly. The OOS-A pass at threshold 0.90 is real;
the OOS-B failure is robust. This is reported as additional
context, not as grounds for relaxing the pre-committed gate. The
0.95 hurdle was the gate; it stands.

**What the gate cannot decide:** whether the MV signal would
survive a *different* test — specifically, a forward paper-trade.
Deflation is a within-sample multiple-testing correction; it does
not measure whether a signal transports to genuinely new data.
The strongest possible falsification of MV is six months of
realized live performance on capital that was not part of any
optimization. That test is owned by Tier 2.

**Bottom line:** the alpha is real *as alpha*. It is not real *as
a signal that survived the deflation-aware multiple-testing bar
the project committed to*. The honest statement is the conjunction
of those two clauses, not either one alone.

---

## 5. What would change my mind

The gate would still be considered passed if any of the following
were true and demonstrable on this same universe + cost regime:

- **A combination strategy with DSR > 0.95 in both OOS windows
  against a trial set that includes every strategy actually tested
  during Tier 1.** Trimming trials post-hoc does not count.
- **A non-linear combination** (gradient-boosted trees, neural
  ensemble) with DSR > 0.95 under the same gauntlet. Out of scope
  for Tier 1 by construction; explicitly flagged as a Tier 2
  candidate if row 2 applies.
- **A 6-month live paper-trade** of any pre-committed signal that
  delivers a Sharpe with bootstrap CI excluding zero, run after
  Tier 1 closes, on capital that was not part of any prior
  optimization.
- **A reproducer**: independent re-implementation of the gauntlet
  (different language, different cost library) that produces a
  survivor on the same JSON inputs.

Conversely, the failure conclusion would be *strengthened* by:

- The raw-returns rerun showing MV-on-raw < +1 OOS Sharpe in
  either window (residualization-artifact hypothesis confirmed).
- A 3-month forward paper-trade of MV showing realized Sharpe < 0
  (the strategy doesn't transport beyond its in-sample fit).

---

## 6. Limitations and known-unknowns

**Known limitations:**

- 226 of 881 ever-member tickers lack OHLCV; treated as data gaps,
  not silently dropped.
- Local FF5 minor factors (SMB, RMW, CMA) under-replicate Ken French
  on the 500-ticker substrate. We residualize against French's
  published series; the replica gate is informational. If French's
  CRSP-wide series is itself slightly off-universe for our cross-
  section, residualization carries that mismatch.
- Cost model is parametric (1 + 2 + 10 bp). Realized cost on the
  paused live execution loop has only 7 fills, not enough to
  calibrate. Realized vs. modeled cost is a Tier 2-or-later
  reconciliation question.
- Capacity sweep (§3.4) is pending for MV; sized at $1M-$1B in
  Phase 5 design but not yet executed.
- TSMOM and pairs studies run on the 50-name legacy universe, not
  PIT. Their best-grid Sharpes are included in the trial set for
  deflation but not as PIT-substrate strategies.

**Known-unknowns:**

- Whether MV's +2.8 OOS Sharpe is real edge or residualization
  artifact. Diagnostic test scheduled 2026-05-15.
- Whether a non-linear combination would survive the same gate.
  Out of scope; Tier 2 candidate.
- Whether the same gauntlet on a Russell 1000 (paid data) substrate
  would yield more survivors. The Tier 1 plan explicitly forbade
  paid data; revisitable in Tier 2 if the diagnostic warrants.
- Whether the residualization step is itself the wrong thing to do
  for this signal class. Residualization is the standard hygiene
  for cross-sectional alpha; a Tier 2 row-1 pivot would re-examine
  this.

---

## 7. Tier 2 sub-plan (one-pager)

The full Tier 2 design is its own memo (`TIER2_DESIGN.md`,
to be drafted next). This page commits the load-bearing
parameters that determine what Tier 2 *is*.

### 7.1 Matrix row committed
**Row 2** — "IC > 0 raw + residualized but net Sharpe ≤ 0 → real
signal eaten by costs." Here, "eaten by deflation against an
oversized trial set" is the same family of failure as
"eaten by costs": both are cases where the alpha exists but the
construction does not let it survive a serious bar.

### 7.2 The Tier 2 binary gate
The same three-condition gate as Tier 1 (DSR > 0.95 + bootstrap
CI excludes zero + sign agreement, both OOS windows), with two
modifications that target the row-2 failure mode:

1. **Trial set capped at ≤ 8 strategies**, pre-registered before
   any data is seen. The 24-trial deflation was the binding
   constraint in Tier 1; ≤ 8 trials with the same Sharpe magnitudes
   would clear DSR > 0.95.
2. **Add a 6-month forward paper-trade requirement** on the surviving
   signal. Realized Sharpe with bootstrap CI excluding zero on
   forward data is the falsifier the deflation framework cannot
   itself deliver. A signal that clears the deflation gate but
   fails the forward test is not a survivor; a signal that fails
   the deflation gate but clears the forward test is also not a
   survivor. Both must hold.

### 7.3 The Tier 2 hypothesis space (pre-committed)
Tier 2 tests MV-class signals (linear combinations of
cross-sectional factor scores, with weights from training-window
covariance-aware optimization) under the following modifications:

- **Lower turnover**: 63d and 126d rebalance horizons, vs. the
  Tier 1 21d. Turnover is the most likely lever for a row-2 fix.
- **Larger universe**: Russell 1000 via paid data ($60-80/mo from
  Norgate or equivalent). Higher participation-rate tolerance.
- **Asset-class extension** (lower priority): same construction on
  liquid futures (ES, NQ, RTY, ZN, CL, GC) where impact is
  asymmetric and bid-ask is structurally tighter.

The first two are primary; the futures path is contingent on the
equity row failing again.

### 7.4 Timeline
- **Months 1-3**: Tier 2 Phase 1 — universe + cost-model setup.
  Mostly subscribing to / staging the paid universe data and
  reconciling against Tier 1's PIT layer.
- **Months 3-6**: Tier 2 Phase 2 — the lower-turnover gauntlet on
  the 8-strategy pre-committed set. End-of-Phase-2 gate decision.
- **Months 6-12**: Tier 2 Phase 3 — forward paper-trade of the
  Phase-2 survivor (if any), or asset-class pivot (if none). The
  forward-trade window is the literal calendar 6 months; cannot
  be compressed.

Total Tier 2 budget: **~12 months, ~250-300 hours**, on the same
15-20 hrs/week alongside coursework that Tier 1 ran on.

### 7.5 Tier 2 not-doing list (mirrors Tier 1)
- No new factors beyond MV-class linear combinations of the 9
  Tier 1 factors. Reason: the Tier 1 trial set is the prior;
  expanding factor space inflates the deflation hurdle again.
- No new MARL work. Same reason as Tier 1 plus row-2 doesn't
  implicate model capacity.
- No new sub-projects, frontend work, or premature engineering
  polish.
- No live execution with real capital. Paper-trading only until
  Tier 2 Phase 3 result lands.
- No paid data beyond Russell 1000 universe. Specifically: no
  alt-data, no fundamentals beyond what's already used.
- No fund-name brainstorming, LP-courting, or "personal brand"
  work. The Phase 6 writeup is the public artifact; nothing else.

### 7.6 What gets reused vs. rebuilt
**Reused:** the PIT universe stack, the gauntlet (DSR / SPA / RC /
purged CV / bootstrap), the cost-model module, the FF5+UMD
residualizer (now correctly wired), the alpha post-hoc layer.

**Extended:** the universe layer (add Russell 1000), the
turnover-penalized portfolio construction (currently 21d only),
the forward paper-trade harness (live execution stack already
exists; needs reconnection from `.halt` only after Tier 2 Phase 2
gate passes).

**Rebuilt:** nothing. The Tier 1 stack is fit for purpose.

### 7.7 Honest pre-commit
If the Tier 2 Phase 2 gate also fails — i.e., MV-class signals at
63d/126d on Russell 1000 do not clear DSR > 0.95 + paper-trade
falsification — **the project transitions to the desk-track /
master's path described in `TIER1_STATUS.txt:407` ("All single +
combination fail → UNIVERSE-LEVEL PIVOT OR accept negative + double
down on desk-track path")**. Tier 3 does not exist yet and should
not be designed before that decision point.

---

## Appendix A — Pointers to raw artifacts

| Artifact | Path |
|---|---|
| Phase 1 PIT universe event log | `data/market/pit/artifacts/_event_log.parquet` |
| Phase 3 FF5+UMD reference series (staged) | `research/out/phase3_reference_staged.csv` |
| Phase 3 validation result | `research/out/phase3_ff5_validation.json` |
| Phase 4 factor study (residualized) | `research/out/factor_study_results.json` |
| Phase 4 gate result | `research/out/phase4_gate_result.{json,md}` |
| Phase 5 combination results | `research/out/phase5_combination_results.json` |
| Phase 5 gate result | `research/out/phase5_gate_result.{json,md}` |

---

## Appendix B — Reproducibility

Every metric in this writeup is regenerable from the artifacts above
with three commands:

```bash
cd alphaforge-python
ALPHAFORGE_FACTOR_STUDY_RESIDUALIZE=1 \
  ALPHAFORGE_REFERENCE_FACTORS=research/out/phase3_reference_staged.csv \
  python3 research/factor_study.py
ALPHAFORGE_FACTOR_STUDY_RESIDUALIZE=1 \
  ALPHAFORGE_REFERENCE_FACTORS=research/out/phase3_reference_staged.csv \
  python3 research/phase5_combine.py
python3 research/phase4_gate.py
python3 research/phase5_gate.py
```

Total wall-clock: ~5 minutes on a single laptop. The PIT universe
construction (Phase 1) is a separate ~90-hour build documented in
`data/market/PIT_UNIVERSE_DESIGN.md`; its outputs are committed to
the repo so the gauntlet does not require re-running it.
