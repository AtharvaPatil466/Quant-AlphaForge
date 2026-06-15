# AlphaForge — Cross-Substrate Meta-Synthesis

*What eight failed substrates, one calibrated gauntlet, and one closed cost loop actually proved.*

**Author:** Atharva Patil
**Date:** 2026-06-15
**Status:** Synthesis across all closed substrates. Supersedes nothing; the per-substrate verdicts stand. This document answers the question the individual verdicts cannot answer on their own.

---

## 0. The question this document settles

Eight substrate investigations have closed FAILED. Each verdict, read alone, says *"this strategy did not clear the gauntlet."* But eight rejections are consistent with **two opposite world-states**, and the per-substrate verdicts cannot distinguish them:

- **World A — the null is real.** At retail data grade, with honest costs and honest deflation, the alpha genuinely is not there. The gauntlet is a correctly-calibrated instrument reporting a true negative.
- **World B — the instrument is blunt.** Tradeable edges existed, but the gauntlet's hurdle (DSR > 0.95 deflated against the pre-committed trial count) is so strict it rejected real signals. The failures are false negatives.

"0 for 8" is identical output in both worlds. **Telling them apart requires calibrating the gauntlet against itself** — measuring what it *would* detect if a known edge were really there. That calibration did not previously exist. It does now, and together with a DSR-consistency audit and a closed cost-feedback loop, it settles the question. The short answer: **predominantly World A, with one important, quantified caveat about economic strictness.**

---

## 1. The substrate ledger

| # | Substrate | Class | Outcome | Failure mode |
|---|---|---|---|---|
| 1 | Equity Tier 1 (PIT S&P 500 cross-section) | predictive | CLOSED FAILED 2026-05-02 | **A** — real signal, deflation + short-horizon |
| 2 | Equity Tier 2 (lower-turnover variant) | predictive | CLOSED FAILED 2026-05-02 | **A** — MV alpha is short-horizon-specific, didn't transport |
| 3 | Crypto Carry (Binance funding) | predictive | CLOSED FAILED 2026-05-15 | **A** — IC~0.5 but costs (36bp) + DSR 0.624 |
| 4 | Microstructure (BTC-USDT L2 + tape) | execution-alpha | IN FLIGHT | — (Phase 0 book accumulation) |
| 5 | PEAD (EDGAR XBRL) | predictive | CLOSED FAILED 2026-05-17 | **B** — "real but weak," DSR ≤ 0.75, OOS-B too short |
| 6 | India (NSE bhavcopy + delivery) | event/flow | CLOSED FAILED 2026-05-20 | **C** — sign inversion, every OOS Sharpe negative |
| 7 | VIX / Variance Risk Premium | premium-harvest | CLOSED FAILED 2026-05-21 | **D** — Phase-1 pass, Phase-3 fail; signal real, too small for DSR |
| 8 | VIX 20× ETP sizing | premium-harvest | CLOSED FAILED 2026-05-21 | **D** — Sharpe invariant to linear scaling |
| 9 | Iron Condor Options (SPY BS) | premium-harvest | CLOSED FAILED 2026-05-26 | **E** — premium real (11/11 yrs +), but VRP doesn't predict cycle P&L |

### The failure-mode taxonomy

- **Mode A — real-but-deflated.** Positive in-sample signal; OOS Sharpe positive but below the DSR-deflated hurdle. (Tier 1, Tier 2, crypto.)
- **Mode B — real-but-weak / sample-starved.** Signal present and OOS-positive, but the OOS window is too short for any test to tighten around it. (PEAD.)
- **Mode C — sign inversion.** In-sample signal reverses out-of-sample; OOS Sharpe actively negative. Costs are not the binding constraint. (India.)
- **Mode D — too-small-at-honest-sizing.** Premium demonstrably exists (Phase 1 passes), but the pre-committed retail implementation extracts too little to clear DSR after deflation; invariant to linear leverage. (VIX #7/#8.)
- **Mode E — binary-filter-works-continuous-predictor-absent.** The premium is real and harvestable (every year positive), but the conditioning variable has no continuous predictive relationship to outcome. (Iron condor.)

All five modes are variants of one structural fact, made precise in §3: **the edges that survive to retail data grade are smaller than the gauntlet's detection floor.**

---

## 2. Is the verdict machinery itself trustworthy?

Before drawing conclusions *from* eight verdicts, the machinery that produced them must be audited. Two integrity questions, both now answered with code and tests (`alphaforge-gauntlet/`).

### 2.1 Were all eight verdicts computed with the same statistics?

**No — and that is now measured rather than assumed.** The substrates shipped **four different Deflated Sharpe Ratio implementations** against one shared 0.95 hurdle:

| Substrate | σ̂(SR) estimate | E[max] form | tail moments |
|---|---|---|---|
| VIX | analytic (Lo 2002) | exact two-quantile | live skew/kurt |
| crypto | analytic (Lo 2002) | exact two-quantile | live skew/kurt |
| India | analytic (Lo 2002) | **Euler-asymptotic** | live skew/kurt |
| PEAD | **empirical cross-trial variance** | exact two-quantile | hardcoded Gaussian |

These are all defensible Bailey–López de Prado / Lo variants, but they are **not interchangeable**, and India's source even claimed (incorrectly) to match crypto's "exactly." The canonical package (`afgauntlet`) now consolidates all of them, and `reports/dsr_variant_divergence.py` quantifies the disagreement across an sr × N × n_obs grid:

- Max |ΔDSR| vs the canonical exact form: **VIX 0.0 (bit-identical), crypto 0.0066, India 0.0260, PEAD 1.7e-10.**
- **Verdict flips across all four variants near the 0.95 hurdle: 0 of 96 grid points.**

**Conclusion:** the DSR inconsistency was real but immaterial — no historical verdict was an artifact of which DSR estimator happened to be in that substrate's tree. Future verdicts run one audited implementation, version-pinned via `source_hash()`, with golden + reconciliation tests proving it reproduces the published numbers to float equality.

### 2.2 Were the verdicts cost-bound?

Backtests *assumed* costs; the live paper-trading loop *recorded* them. Closing that loop (`alphaforge-execution/research/cost_calibration.py`): of the orders on disk, only **12 are genuine live Alpaca fills** (the rest are paper-broker fills where realized ≡ assumed by construction). On those 12, median realized slippage was **13.1 bp vs 5 bp assumed → ~2.6× multiplier** (central estimate ~3×, corroborated independently by PEAD's documented Corwin–Schultz 7–8 bp vs 2 bp assumed ≈ 3–4×). N=12 and stale-close drift contamination make this an **upper bound**, and the impact coefficient *k* is not identifiable from the recorded fields — stated honestly in the artifact.

Applying ~3× costs to the cost-diagnosed substrates:

| Substrate | Binding gate | Effect of 3× costs | Cost-bound? |
|---|---|---|---|
| Equity Tier 1 | DSR 0.92/0.70; MV alpha collapsed at lower turnover | DSR drops further | **No** — deflation / short-horizon |
| Crypto Carry | DSR 0.624; turnover 1701%; CI brackets 0 | all worsen | **Partially** — jointly cost + deflation |
| PEAD | DSR ≤ 0.75; OOS-B CI brackets 0 (2.4y) | DSR drops; sample issue untouched | **No** — deflation / short-OOS |
| India (control) | negative OOS Sharpe | −4.80 → −4.88 (negligible) | **No** — sign inversion |

**Conclusion:** higher realized costs are strictly *unfavorable* to already-failed strategies, so **no verdict flips**. Only crypto carry was plausibly cost-bound, and even there jointly with deflation. The cost diagnoses in the original verdicts were directionally honest but slightly over-attributed failure to costs; the dominant binding constraint was **deflation (DSR < 0.95)**, not execution.

---

## 3. The keystone: what the gauntlet can actually detect

The power calibration (`alphaforge-gauntlet/power/`) injects synthetic alpha of *known* true annualized Sharpe onto block-bootstrapped **real SPY return noise** (preserving realistic vol, fat tails, autocorrelation), then Monte-Carlos how often the canonical detection gauntlet (DSR > 0.95 + bootstrap-CI-excludes-zero + sign agreement, both OOS windows) detects it. The crossover Sharpe where detection power crosses a threshold is the **Minimum Detectable Effect (MDE)** — the gauntlet's sensitivity floor.

### Minimum detectable true annualized Sharpe

| Config | N trials | OOS length (each) | MDE @ 50% power | MDE @ 80% power |
|---|---|---|---|---|
| Generous (no deflation) | 1 | 10y | 0.69 | **0.93** |
| VIX-like | 28 | 5y | 1.91 | **2.40** |
| VIX-long | 28 | 10y | 1.36 | **1.66** |
| PEAD-like | 10 | ~1.2y | >3.5 | **>3.5** |

Two facts fall straight out:

1. **Overall detection power equals the DSR-gate pass rate at every grid point** (e.g. true Sharpe 2.0 → power 0.57 → DSR-gate 0.57). Sign agreement and the bootstrap CI clear far earlier. **The DSR deflation gate is the sole binding constraint of the entire apparatus** — confirming §2.2's cost finding from a completely independent direction.

2. **Two knobs move the floor enormously:** deflation breadth (N=1 → N=28 lifts MDE@80 from 0.93 to 2.40 at 5y) and sample length (5y → 10y drops it from 2.40 to 1.66). A short OOS window (PEAD's ~1.2y) pushes the floor above 3.5 — **structurally undetectable regardless of true signal strength.**

### Reading the eight failures against the floor

| Substrate | Observed OOS Sharpe | Relevant MDE@80 | Verdict |
|---|---|---|---|
| VIX (#7/#8) | −0.77 … +0.55 | 2.40 (5y) / 1.66 (10y) | below even the **generous 0.93** floor → **real null** |
| PEAD (#5) | +2.29 … +2.87 (point, 80–127d) | >3.5 at that length | **undetectable by sample length**, not signal absence |
| India (#6) | negative | n/a (wrong sign) | sign inversion — no floor applies |
| crypto (#3) | IC~0.5, DSR 0.624 | ~1.9 (its N/length) | below floor, jointly with costs |

This is the resolution of §0:

- **VIX is World A — a genuine null.** Its best OOS Sharpe (+0.55) sits below *even the generous, zero-deflation, 10-year floor of 0.93*. Even with no multiple-testing penalty and maximum data, that signal would not be reliably detectable. The premium is real (Phase 1 caught it) but too small to extract at retail scale — exactly Mode D, now quantified.
- **PEAD is a sample-length artifact, not "real but weak" in the pejorative sense.** Its point Sharpes of +2.3–2.9 look strong, but at 80–127 OOS days the detection floor exceeds 3.5; *nothing* of plausible strength clears at that window length. The honest restatement: PEAD was **under-powered**, not clearly null.
- **The deflation price is real and steep.** Testing 28 pre-committed trials instead of 1 raises the bar from a Sharpe of ~0.9 to ~2.4 (at 5y). This is the correct, intended cost of honest multiple-testing — but it means the gauntlet is calibrated for *standalone, full-conviction deployability*, not for *tradeable-with-leverage*.

### The one caveat that matters: economic vs statistical strictness

An MDE@80 of **2.40 annualized Sharpe** is far above what a real fund needs. Levered, risk-managed books are run profitably at true Sharpe 0.5–1.0. The gauntlet, as pre-committed, asks: *"is this a deployable standalone retail strategy at full conviction, net of honest costs, after deflating against everything we tried?"* — **not** *"is there a tradeable edge a desk could lever?"*

So the precise, honest two-part finding is:

> **The signals were genuinely weak (World A): the strongest, VIX's +0.55, is below even a generous no-deflation floor. AND the gauntlet is economically strict (a shade of World B): its 0.95-DSR-against-N hurdle sets a detection floor (~2.4 at 5y) well above the Sharpe a leveraged fund would happily trade.**

These are not contradictory. The substrates failed because the edges are small; *and* the bar is set for "deploy a standalone strategy," which is the right bar for the project's stated goal (a retail-origin systematic book) and the wrong bar for "find any leverageable signal." The number — 2.40, now measured — is what lets this be stated as fact instead of intuition.

---

## 4. What is now true that wasn't before

1. **The 0-for-8 record is predominantly a real null, not a blunt instrument** — proven by the observed Sharpes sitting below even the generous detection floor, not merely below the deflated one.
2. **The binding constraint is DSR deflation**, established three independent ways: the cost loop (costs don't flip verdicts), the power curve (overall power ≡ DSR-gate rate), and the substrate ledger (Modes A/B/D all gate on DSR).
3. **No verdict was a statistical artifact** — neither of the inconsistent DSR implementations (0 flips / 96 points) nor of optimistic cost assumptions (realized costs are higher, strictly unfavorable, 0 flips).
4. **Two failures are reclassified honestly:** PEAD from "real but weak" to **under-powered** (sample length, not signal); the cost diagnoses from "eaten by costs" to **"eaten by deflation, mildly worsened by costs."**
5. **The methodology is now self-aware and reusable:** one audited, version-pinned gauntlet (`afgauntlet`) with a power calibrator and a programmatic pre-registration gate, so every future substrate reports not just *pass/fail* but *was this even detectable, and was the pre-commit honored.*

---

## 5. What this implies for the next move

The discipline is vindicated and the instrument is now characterized. The unproductive move is a ninth retail-shaped predictive substrate — §3 predicts its outcome. The informative moves change a **structural input**, and the MDE table says which inputs matter most:

- **Lengthen OOS, or accept fewer pre-committed trials.** The floor is dominated by `n_obs` and `N`. A substrate with a 15–20 year clean OOS and a tight ≤6-trial pre-commit has a floor near ~1.0–1.3 — within reach of a real edge. PEAD's reclassification is the proof that sample length, not signal, killed it.
- **Decide the bar deliberately.** If the goal is a *leverageable* signal rather than a *standalone* one, the pre-commit should say so — a Sharpe-0.6 edge with a CI excluding zero is a legitimate target the current 0.95-DSR gate is designed to reject. That is a founder decision about *what business is being built*, now quantified by the MDE so it is made with eyes open.
- **Microstructure (#4) is the live test of a genuinely different input** (execution-alpha at retail latency, not prediction). It should be run through this same calibrated gauntlet, and its verdict should report its MDE alongside its Sharpe.
- **Paid data / market-making remain the structural escalations** if microstructure also lands in World A.

---

## 6. Honest limitations of this synthesis

- The MDE is calibrated on **SPY-like noise** (~1.17%/day, equity fat tails). Because Sharpe is scale-free the (Sharpe, N, n_obs) → power mapping is largely substrate-agnostic, but the higher-moment penalties depend on each substrate's skew/kurtosis; a crisis-tail substrate like unhedged short-vol would have a somewhat higher floor than the table shows.
- The cost multiplier rests on **12 live fills** with stale-close drift contamination — an upper bound, with *k* unidentifiable. It is corroborated but not precise; treat ~3× as a working figure, not a measurement.
- This synthesis reasons about the closed substrates from their **documented numbers**, not by re-running their full backtests. Where a claim could not be pinned to a recorded figure it is flagged as such.
- "World A vs World B" is a useful dichotomy, not a dichotomy of nature: the truthful finding is "small real edges below a deliberately high bar," which contains elements of both.

---

*Artifacts behind this document:*
- `alphaforge-gauntlet/` — canonical gauntlet, 54 tests (golden + reconciliation + DSR-variant + power + pre-registration).
- `alphaforge-gauntlet/reports/out/dsr_variant_divergence.{md,json}` — the 4-implementation DSR audit.
- `alphaforge-gauntlet/power/out/mde_calibration.{md,json}` — the power / MDE calibration.
- `alphaforge-execution/research/out/cost_calibration.{md,json}` + `COST_BOUNDEDNESS_RESTATEMENT.md` — the closed cost loop.
