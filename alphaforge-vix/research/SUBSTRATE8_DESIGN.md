# Substrate #8 — VIX/VRP at VIX-Baseline-Anchored Sizing — Pre-Committed Design

**Status:** PRE-COMMITMENT. Written 2026-05-21 _after substrate #7 closed FAILED at Phase 3_ but BEFORE any substrate-#8 backtest has been run. No SHA-anchored gauntlet result exists for substrate #8 at the time this document is filed.

**This document is the substrate #8 contract.** It inherits everything from `VIX_DESIGN.md` (SHA `54e53be92f72e5161a4478cb8e518955d08164bfad0057675278fa2c49367b29`, post-§17.8 ADDENDUM) EXCEPT §9.1 sizing, which is replaced below.

Pairs with `alphaforge-vix/CLAUDE.md`, the substrate #7 `VIX_DESIGN.md`, and the substrate #7 `GAUNTLET_VERDICT.md` (which informs the existence of this substrate but not its design).

---

## 0. Why Substrate #8

Substrate #7 (VIX/VRP) closed FAILED at Phase 3 on 2026-05-21 with 0/28 deploy-ready combos. The Phase 3 Discussion section identified the failure mode as **Mode D: signal real, pre-committed §9.1 sizing too small to clear DSR after deflation.** Phase 1 found genuine positive-IC evidence for the VRP signal (peak IC +0.180 at h=21, monotonic threshold response thr=0→0/6, thr=2→4/6, thr=4→6/6). Phase 3 found the strategy's NAV PnL too small to be statistically distinguishable from noise once cash carry was honestly zeroed (§17.8 ADDENDUM).

Substrate #8 tests **one** hypothesis: **if the §9.1 sizing rule is changed so that the strategy has measurable dollar exposure to the VRP signal, does it clear the same six-gate gauntlet against the same 28-trial DSR denominator?**

This is NOT a re-running of substrate #7. Substrate #7's verdict (CLOSED FAILED) is final under §15 hard rules. Substrate #8 is a separate pre-commit with its own gates, its own SHA, its own verdict file. Code reuse is high (~95%); pre-commit discipline is maintained by the new SHA anchor on this document.

**Why this isn't peeking.** The decision to change sizing was made on the **principle** "the pre-committed signal must produce a *measurable* dollar exposure relative to NAV" — a principle that was implicit in the original §9.1 ("Implicit leverage acknowledgement. VIX futures are notionally leveraged...") but produced a degenerate 0.5%-of-NAV exposure when literally implemented under the §17 SVXY-only path. The new rule is anchored to the long-run VIX mean (20), a non-strategy-specific number, and the constant (0.10) is preserved from substrate #7 to avoid free-parameter introduction. The specific Phase 3 numbers from substrate #7 (which trial passed which gate) did NOT inform any choice in this design. The sizing rule was chosen BEFORE running any substrate-#8 backtest.

**Direction of effect.** Larger sizing increases both potential Sharpe AND potential drawdown. Substrate #8 makes Phase 3 EASIER on DSR/bootstrap/CF gates (larger dollar PnL relative to its standard deviation) but HARDER on Gate 5 (max-drawdown ≤ 30% per stress period 4-of-4 — uncovered handling per Phase 2 §6). Whether the strategy clears Gate 5 at the new sizing is **genuinely uncertain** before running. The verdict could be PASS (signal scales to meaningful size), CLOSED FAILED at Gate 5 (signal exists but tail risk too severe at meaningful size), or CLOSED FAILED at G1/G2/G6 (signal too small to matter even at 20× the substrate-#7 sizing). All three outcomes are pre-commit-honest.

---

## 1. What Changes vs Substrate #7

**The ONLY change is §9.1 — position sizing.** Everything else is inherited from `VIX_DESIGN.md` (SHA `54e53be9...`):

- Substrate window — §3 — UNCHANGED (2004-03-26 → present; IS = 2004-2014, OOS-A = 2015-2019, OOS-B = 2020-present, 21-day embargo).
- Trial set — §4 — UNCHANGED (28 trials: 18 VRP + 6 slope + 4 mean-reversion). The 8 closed slope trials still count in the DSR denominator. The 10 VRP survivors + 4 mean-reversion = 14 base trials × 2 hedge variants = 28 strategy-trial combos to evaluate.
- Six gates — §5 — UNCHANGED.
- Cost model — §6 — UNCHANGED. Carry on free cash = 0 per §17.8.
- Four-factor residualization — §7 — UNCHANGED.
- Hedge variants — §9.2 + §17.4 — UNCHANGED.
- Exit rules — §9.3 — UNCHANGED.
- §10 Phase 3 gauntlet — UNCHANGED.
- §11 Phase 4 conditional — UNCHANGED.
- §12 Decision matrix — UNCHANGED.
- §15 Hard rules — UNCHANGED. Substrate #8 has the same no-edit-after-Phase-1 discipline as substrate #7.

---

## 2. §9.1 — Substrate-#8 Sizing Rule (Replaces VIX_DESIGN.md §9.1)

**Substrate-#8 §9.1 — VIX-baseline-anchored 10%.**

On each potential entry day `t`:

```
max_notional = SIZING_CONSTANT × portfolio_value × (VIX_BASELINE / VIX_t)

where:
    SIZING_CONSTANT = 0.10        (unchanged from substrate #7 §9.1)
    VIX_BASELINE    = 20.0         (long-run VIX mean, frozen, no search)
```

**Auto-deleverage preserved.** Higher VIX → smaller notional, in the same inverse-VIX shape as substrate #7 §9.1. The only change is the baseline anchor.

**Concrete sizes on $1M portfolio:**

| VIX level | max_notional (% NAV) | Substrate #7 size at same VIX |
|---|---|---|
| 10 | 20.0% | 1.0% |
| 15 | 13.3% | 0.67% |
| 20 (baseline) | 10.0% | 0.50% |
| 30 | 6.67% | 0.33% |
| 40 (Volmageddon-like) | 5.0% | 0.25% |
| 80 (COVID-peak-like) | 2.5% | 0.125% |

Substrate #8 is exactly 20× substrate #7 at every VIX level. The relative shape is identical; only the absolute scale changes.

**Cash floor.** Same as substrate #7 spec §2: `max_notional = min(max_notional, 0.99 × cash_available)`.

**§17.3 SVXY exposure multiplier.** UNCHANGED. Pre-2018-02-27 SVXY is -1× (multiplier = 1.0); post is -0.5× (multiplier = 2.0). At post-2018, a 10%-NAV short-vol target = 20% SVXY notional.

**§9.1 implicit leverage.** Substrate #8's max SVXY notional at low VIX (e.g., VIX=10 post-2018) is 40% of NAV. This is unleveraged at the ETP-share level (long SVXY is paid for outright) but is meaningfully larger exposure than substrate #7. The §14.3 limitation ("implicit leverage in short-vol") still applies and is, if anything, more material at the new sizing.

---

## 3. Pre-Commit Anchor

**`SUBSTRATE8_DESIGN.md` SHA-256:** recorded at file time in `research/substrate8_spec.json`.

**`VIX_DESIGN.md` parent anchor:** `54e53be92f72e5161a4478cb8e518955d08164bfad0057675278fa2c49367b29`.

The substrate #8 runner (`gauntlet/run_substrate8.py`) refuses to execute if EITHER SHA does not match its anchor. Edits to this document after the runner first executes invalidate the substrate #8 verdict.

---

## 4. Expected Outcomes — Pre-Run Framing (Anti-Peek)

Before running, the three pre-committed outcomes are:

1. **DEPLOY-READY** at any (trial × variant) combo — substrate #8 succeeds. Phase 4 paper trading would follow, per the §11 conditional. This would be the project's first DEPLOY-READY verdict across seven substrates.

2. **CLOSED FAILED at G1/G2/G6 (signal-too-small variants)** — 20× larger sizing was insufficient. Mode D failure persists. Diagnosis: the VRP signal magnitude is structurally too small for retail-data extraction at any reasonable sizing within the §15 hard-rule constraint set.

3. **CLOSED FAILED at Gate 5 (tail-risk-too-severe)** — strategy clears DSR/bootstrap/CF but is killed by the 30%-max-drawdown bound on at least one covered stress period. This is the most interesting failure mode for the project's research program: it would say "premium exists at this size but is paid for by catastrophic stress losses" — a real economic finding, not a methodology artifact.

Each outcome implies a different "what next?" path:
- Outcome 1 → Phase 4 / deploy.
- Outcome 2 → systematic alpha at retail-data + parametric-cost may be exhausted; move to paid data, different signal class outside vol, or non-systematic.
- Outcome 3 → consider position sizing tied to a tail-risk budget instead of a notional cap (this would be a substrate #9 if pursued).

The verdict is genuinely uncertain. The pre-commit is honest precisely because there is no a-priori expectation of which outcome the data will produce.

---

## 5. Hard Rule Reminder

This document is FROZEN at the moment the substrate #8 runner first executes. The §15 hard rules of `VIX_DESIGN.md` apply to substrate #8 with identical strength: no edits to the trial set, gates, residualization, cost model, exit rules, or this §9.1 sizing post-Phase-1.

Errors count as fails. Trials that fail to fill (e.g., Variant B pre-2018, mean-reversion LONG_VOL pre-2018) count as fails for the (trial × variant) pair.

**Date:** 2026-05-21.
