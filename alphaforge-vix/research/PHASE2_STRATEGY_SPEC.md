# VIX — Phase 2 Strategy Spec (Pre-Commit)

**Status:** PRE-COMMITMENT. Filed 2026-05-21 _before any OOS data has been touched._ This document operationalizes `VIX_DESIGN.md` §9 (position sizing, hedge variants, exit rules) into concrete parameters per Phase 1 survivor. All numbers come from `VIX_DESIGN.md` §9 + §17.4; no parameter is searched or chosen post-hoc.

**SHA-256 anchor of `VIX_DESIGN.md` at filing:** `66a6c45a90bdda5879cc37348ac01bc7aea59e5c8403531592c3d9509cdabb0b`

Pairs with `research/PHASE1_VERDICT.md` (which lists the survivor set) and is consumed by the Phase 3 gauntlet (`gauntlet/run_gauntlet.py`).

---

## 1. Survivor inventory

| # | Trial | Lookback | VRP threshold | Holding (days) | Peak IC | Peak horizon |
|---|---|---|---|---|---|---|
| 1 | `vrp_L10_thr2_hold5`  | 10 | 2.0 | 5  | +0.051 | 5  |
| 2 | `vrp_L10_thr2_hold21` | 10 | 2.0 | 21 | +0.051 | 5  |
| 3 | `vrp_L10_thr4_hold5`  | 10 | 4.0 | 5  | +0.070 | 5  |
| 4 | `vrp_L10_thr4_hold21` | 10 | 4.0 | 21 | +0.070 | 5  |
| 5 | `vrp_L21_thr4_hold5`  | 21 | 4.0 | 5  | +0.080 | 5  |
| 6 | `vrp_L21_thr4_hold21` | 21 | 4.0 | 21 | +0.080 | 5  |
| 7 | `vrp_L63_thr2_hold5`  | 63 | 2.0 | 5  | +0.073 | 5  |
| 8 | `vrp_L63_thr2_hold21` | 63 | 2.0 | 21 | +0.073 | 5  |
| 9 | `vrp_L63_thr4_hold5`  | 63 | 4.0 | 5  | +0.180 | 21 |
| 10 | `vrp_L63_thr4_hold21`| 63 | 4.0 | 21 | +0.180 | 21 |

**Plus 4 mean-reversion trials** (per §4.3, not Phase 1 IC-tested):

| # | Trial | Spike entry | Exit |
|---|---|---|---|
| 11 | `mr_k1.5_to_MA+1sigma` | MA63 + 1.5·σ63 | Return to MA63 + 1.0·σ63 |
| 12 | `mr_k1.5_to_MA`        | MA63 + 1.5·σ63 | Return to MA63 |
| 13 | `mr_k2.0_to_MA+1sigma` | MA63 + 2.0·σ63 | Return to MA63 + 1.0·σ63 |
| 14 | `mr_k2.0_to_MA`        | MA63 + 2.0·σ63 | Return to MA63 |

**14 base trials × 2 hedge variants = 28 strategy-trial combos to evaluate at Phase 3.** Matches the §4 pre-committed DSR denominator. The 8 closed slope trials still count in the DSR-28 denominator (errors-count-as-fails per §15 hard rule 1).

---

## 2. Position sizing — per §9.1 (frozen)

For every trial, on every potential entry day `t`:

```
max_notional_t = sizing_constant × portfolio_value_t / VIX_t

where  sizing_constant = 0.10   (per §9.1, no search)
```

Auto-deleverages on elevated VIX. **No volatility-targeting overlay**, no dynamic risk-parity adjustment — the §9.1 formula is the entire sizing rule.

Cash floor: `max_notional_t = min(max_notional_t, 0.99 × cash_t)` to avoid implicit margin lending in the backtest. The backtest is unleveraged at the ETP-share level.

---

## 3. Execution instrument

Per §17.3 (ADDENDUM, 2026-05-21): **SVXY is the execution instrument** for all variants and all trials. VIX futures path is REMOVED. SVXY history is treated as two regimes:

| Regime | Window | SVXY exposure | Effective short-vol per $1 SVXY |
|---|---|---|---|
| pre_restructuring  | 2011-10-04 → 2018-02-26 | −1× VIX-futures | $1 short-vol per $1 SVXY |
| post_restructuring | 2018-02-27 → present     | −0.5× VIX-futures | $0.50 short-vol per $1 SVXY |

**Short-vol position via long SVXY.** To take a short-vol position of notional `N`:
- pre-2018-02-27: long `N / SVXY_price` SVXY shares
- post-2018-02-27: long `2N / SVXY_price` SVXY shares (compensates for the 0.5× exposure)

This keeps the *effective short-vol notional* consistent across the regime boundary. The §14.4 limitation about pre/post being two different instruments is honored by the exposure-multiplier rather than by collapsing the pre-2018 IS evidence.

---

## 4. Hedge variants

### 4.1 Variant A — Unhedged short volatility

Single leg: long SVXY at `effective_short_vol_notional / SVXY_price` per §3. No hedge. Full premium harvest; full tail exposure.

**Evidence window:** 2011-10-04 → present (full SVXY history). Covers all four §5.5 stress periods that overlap with SVXY launch: 2011 debt-ceiling (partial — SVXY launched mid-October 2011 so the September leg of that stress period is uncovered), 2018 Volmageddon (full), 2020 COVID (full). 2008 stress is **pre-SVXY** and CANNOT be evaluated on Variant A — handled per §5.5 of the design ("non-negotiable for short-vol" tightened by §17 evidence-window adjustment; see §6 of this spec).

### 4.2 Variant B — Hedged with VXX (per §17.4)

Long SVXY + long VXX at fixed 10% of SVXY notional:

```
svxy_notional   = max_notional × svxy_exposure_multiplier   # 1× or 2× per §3
hedge_notional  = 0.10 × svxy_notional                       # frozen, no search
vxx_shares      = hedge_notional / VXX_price
```

`0.10` hedge ratio is frozen by §17.4. **No search over hedge ratios.**

**Evidence window:** 2018-01-25 → present (VXX post-relaunch only). Phase 3 verdict reports Variant B against the post-2018 stress periods only (Volmageddon 2018, COVID 2020). 2008 and 2011 cannot be evaluated for Variant B; this is the §14.14 limitation explicitly priced into the verdict.

### 4.3 Variant accounting

For every trial 1-14, BOTH variants are run independently and reported separately. No post-hoc "pick the better one" — Variant A is its own Phase 3 verdict, Variant B is its own. The 28-trial DSR denominator counts each (trial, variant) pair as one.

---

## 5. Entry & exit state machine

### 5.1 Entry rule (per trial 1-10, VRP)

Entry happens on day `t` if and only if:

```
VRP_t = VIX_t − realized_vol_t(L) >= trial.vrp_threshold
AND  no open position exists for the trial
AND  no §5.4 hard-stop has fired in the trailing 21 trading days
```

On entry, size per §2 and execute at the next bar's open (T+1 fill, per the equity event-driven engine's no-same-bar-fill rule).

### 5.2 Entry rule (trials 11-14, mean-reversion)

Entry on day `t` if and only if:

```
VIX_t > MA63_t + k·σ63_t       (k = 1.5 or 2.0 per trial)
AND  no open position exists for the trial
AND  no §5.4 hard-stop in trailing 21 days
```

Position is **long volatility** during the spike (Variant A: short SVXY by going long VXX; Variant B: long VXX + long SVXY as a hedge of the long-vol leg). **Direction-flipped from the VRP trials.** This is per §1.4 + §9.2.

### 5.3 Signal exit (per trial)

- **VRP trials:** exit when `VRP_t < 0` (premium has collapsed).
- **Mean-reversion trials:** exit when VIX returns below the trial-specific exit threshold (`MA63 + 1.0·σ63` or `MA63`).

### 5.4 Hard stop — VIX +40% intraday (per §9.3)

If on any day `t` during which a position is open:

```
(VIX_high_t − VIX_close_{t-1}) / VIX_close_{t-1} > 0.40
```

then ALL positions across ALL trials and variants are closed immediately at next bar's open. The 21-trading-day re-entry cooldown in §5.1 applies after a hard stop. **Backtest implementation:** because daily-bar OHLC for `VIX_high` is available from the CBOE index file, the trigger is checked against `VIX_high_t / VIX_close_{t-1} - 1 > 0.40` on the close-of-day mark. Intraday filling is approximated as the open of `t+1`.

### 5.5 Time-based exit (per §9.3)

Any position open > 60 calendar days without a signal exit is force-closed at the next bar's open. Prevents stuck positions.

### 5.6 Hold-period parameter (trials with `hold5` vs `hold21`)

**For Phase 3, the `holding_period` parameter (5 or 21 days) is the** ***minimum hold*** **before signal-exit can fire.** Specifically:
- `hold5` trials: signal-exit checks begin on entry-day + 5.
- `hold21` trials: signal-exit checks begin on entry-day + 21.
- Hard stop (§5.4) and time-based exit (§5.5) fire regardless of the minimum hold.

This makes `hold5` vs `hold21` a meaningful Phase 3 differentiator (premium-decay capture vs full-cycle hold) even though they produced identical Phase 1 IC by construction. **Disclosure:** this is a Phase-2 operationalization of an ambiguity in the design doc — §9 does not explicitly say what `holding_period` means at strategy execution. The choice above is the most natural reading and is filed BEFORE Phase 3 runs.

---

## 6. Stress-period evaluation per Gate 5 — §5.5 ADDENDUM

§5.5 of the design specifies four stress periods. With the §17 SVXY-only constraint, evidence coverage per variant per stress period is:

| Stress period | Window | Variant A coverage | Variant B coverage |
|---|---|---|---|
| 2008 financial crisis | 2008-09-01 → 2009-03-31 | NONE (pre-SVXY) | NONE (pre-SVXY + pre-VXX) |
| 2011 debt ceiling     | 2011-07-01 → 2011-10-31 | PARTIAL (SVXY launches 2011-10-04, covers final ~3 weeks of stress) | NONE (pre-VXX) |
| 2018 Volmageddon      | 2018-02-01 → 2018-03-31 | FULL | FULL (VXX from 2018-01-25) |
| 2020 COVID crash      | 2020-02-01 → 2020-04-30 | FULL | FULL |

**Gate 5 evaluation rule (frozen by this spec):** 4-of-4 max-drawdown ≤ 30% requirement applies to *covered* stress periods only. Uncovered periods are reported as "NO DATA — gate inapplicable" rather than counted as PASS or FAIL. **For Variant A:** Gate 5 effective denominator = 2.5-of-2.5 (2018 + 2020 full, 2011 partial counted as 0.5). **For Variant B:** Gate 5 effective denominator = 2-of-2 (2018 + 2020 full).

This is a **strict tightening** of the design doc's 4-of-4 — Variant A loses some 4-of-4 robustness by having less stress evidence, Variant B loses more. The deflated read is: a passing Gate 5 verdict on Variant B has roughly *half* the stress-period evidence of the original §5.5 design. **§14.16 (new known limitation):** Variant B's Gate 5 evidence is weaker than originally specified due to VXX availability. Borderline passes should be discounted accordingly.

---

## 7. Backtest engine choice

The Phase 3 gauntlet reuses the equity event-driven engine (`alphaforge-python/backtest/event_driven/`) read-only, adapted for:

- **Single-instrument** universe (SVXY, optionally + VXX) instead of the equity cross-section.
- **§3 SVXY regime-aware exposure multiplier** in the strategy-level fill logic.
- **§9 cost model** wired through the existing `SlippageModel` ABC.
- **Custom Strategy subclass** implementing the §5 entry/exit state machine.

The engine's architectural guarantees (no look-ahead, no same-bar fills, per-fill cash costs) carry over. No engine modifications are permitted.

---

## 8. What's frozen by this spec (the §15 ADDENDUM clause)

This document **operationalizes** §9 of the design doc. No threshold, parameter, instrument, hedge ratio, exit rule, or evaluation scope is introduced post-hoc. The two pieces this spec adds beyond §9 (which were ambiguous in the design):

1. **§5.6 — `holding_period` meaning** = minimum-hold before signal exit (most natural reading).
2. **§6 — Gate 5 effective denominator** = covered-stress-periods only (necessary consequence of §17 SVXY-only).

Both are filed BEFORE Phase 3 runs. The §17.7 SHA-anchor on `VIX_DESIGN.md` remains valid — this spec is a Phase-2 derivative, not an edit to the design contract.

**SHA-256 of this spec at filing:** _self-referential; computed and recorded in `vix_phase2_spec.json` once the file is written._
