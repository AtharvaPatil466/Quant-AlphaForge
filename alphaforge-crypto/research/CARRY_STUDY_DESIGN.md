# Carry Study Design — Pre-Commit Document

**Status:** DRAFT pending user sign-off. Once signed off this document is committed to git BEFORE any code reads the OOS slice. The commit SHA is the pre-commit moment.

**Project context:** AlphaForge crypto pivot, 2026-05-15. Equity-substrate gauntlet (Tier 1 + Tier 2) failed on 2026-05-02. This study is the first attempt on the crypto substrate. Methodology hygiene (pre-commit gates, DSR, bootstrap CIs, honest costs) carries over unchanged from the equity stack.

**Inputs read for this design:** `research/out/data_inspection/INSPECTION_REPORT.md`, generated 2026-05-14. Numerical observations inlined below.

---

## 1. Hypothesis

**H1 (primary):** On Binance USDT-M perpetuals, the cross-sectional rank of past funding rates predicts the cross-sectional rank of future funding rates over a 21-funding-event (≈ 7 calendar day) horizon. A dollar-neutral basket that **shorts perpetuals in the top quintile of past funding (hedged with long spot)** and **longs perpetuals in the bottom quintile (hedged with short spot)** earns a positive return net of all costs.

**H0 (null):** Net of costs as specified in §6, the strategy's annualized OOS Sharpe is statistically indistinguishable from zero.

**Observed support for H1 in the inspection report (in-sample diagnostic, not OOS):**
- Funding autocorrelation, cross-symbol mean: ρ(lag=1, 8h) = **0.697**, ρ(lag=3, 1d) = **0.536**, ρ(lag=9, 3d) = **0.401**, ρ(lag=21, 7d) = **0.299**.
- Cross-sectional funding std at each event: median = **1.02 bps/8h**, q95 = **5.79 bps/8h**.
- Annualized symbol-level mean funding ranges from **+18.3% (AIGENSYN)** to **−50.4% (KITE)**.

The hypothesis sign is **locked** before the backtest. We do not test both directions and pick the winner.

---

## 2. Universe

- **Source:** `data/binance/_manifest.json` — top 30 USDT-M perpetuals by 24h quote volume as of 2026-05-14, restricted to symbols whose spot pair was also TRADING.
- **Per-event eligibility:** at each funding event `t`, a symbol is eligible if and only if it has at least `K` past funding events on record AND a spot kline with non-NaN close at `t`. Implicit cutoff: symbols with no funding history (e.g. AIGENSYN with 92 rows total) are eligible only in the last weeks of the dataset.
- **Minimum basket size:** at each event, if fewer than **15 symbols** are eligible (half the universe), no position is taken — flat at zero return for that event. The 15 threshold is locked here.
- **Known limitation (logged, not mitigated in v0):** the universe is a current snapshot; Binance-delisted symbols are not in the panel. Survivorship-bias correction is a future project, documented in `CLAUDE.md`.

---

## 3. Time grid and IS/OOS

- **Total available window (per inspection):** 2020-01-01 → 2026-05-14.
- **In-sample (IS):** 2020-01-01 00:00 UTC → 2024-12-31 23:59:59 UTC.
- **Embargo:** 21 funding events (7 days). All eligibility, signal, and position formation occurring during the embargo is discarded.
- **Out-of-sample (OOS):** 2025-01-08 00:00 UTC → 2026-05-14 16:00 UTC (last available funding event). **OOS sample length: ~1480 funding events.**
- **No model is fit on the OOS slice.** Cross-validation for parameter selection happens entirely within IS using purged + embargoed K-fold (5 folds).

---

## 4. Signal construction

Let `f_{i,t}` be the realized funding rate on symbol `i` at funding event `t`. The signal at event `t` for symbol `i` is:

```
signal_{i,t} = median( f_{i, t-K} , f_{i, t-K+1} , ... , f_{i, t-1} )
```

Notes:
- The current event `f_{i,t}` is **excluded** from the lookback — strict no-look-ahead.
- Median, not mean, for robustness against funding spikes (per inspection: |max| can hit 1.9% per 8h for some symbols).
- After per-symbol computation, signals are **cross-sectionally z-scored** at each `t` (mean 0, std 1) before bucket formation.

---

## 5. Portfolio construction

- **Ranking:** at each rebalance event, eligible symbols are sorted by `signal_{i,t}` z-score.
- **Buckets:** **quintiles** (n_buckets = 5). With a ~25-eligible universe, quintile = ~5 symbols per side.
- **Position per H1:** short perp + long spot on top-quintile (highest-funding) symbols; long perp + short spot on bottom-quintile (lowest-funding) symbols.
- **Sizing:** equal-weight within each basket. Long-short dollar-neutral at portfolio level. No leverage.
- **Holding:** position is held for exactly K funding events (≈ 8h × K). At the next rebalance event, the basket is recomputed and the difference is traded.

---

## 6. Cost model

Per `research/cost_model.py`, locked here:

| Component | Value | Notes |
|---|---|---|
| Perp taker fee | 4.0 bps per side | Binance VIP-0 retail tier |
| Spot taker fee | 10.0 bps per side | Binance VIP-0 retail tier |
| Slippage | 2.0 bps per leg | Flat in v0; upgrade to sqrt-impact when L2 lands |
| Spot short borrow | 30 bps annualized | Applied to long-perp / short-spot leg only |
| Funding cash flow | actual realized rate | Booked at each funding event, not amortized |

**Round-trip combined cost per symbol per rebalance: 36 bps.** (12 bps perp round-trip + 24 bps spot round-trip.)

Charged on the **changed portion of the basket** only — if a symbol stays in the top quintile across two consecutive rebalances, no cost is incurred for it.

---

## 7. Statistical hygiene

- **Stationary bootstrap** (Politis-Romano 1994) Sharpe CI, n_resamples = 5000, mean block length = **12** (≈ T_OOS ^ {1/3} with T_OOS ≈ 1480).
- **Deflated Sharpe Ratio** (López de Prado 2018), inputs: observed Sharpe, OOS skew, OOS kurtosis, OOS sample length, and `N_trials` from §8 below.
- **Purged + embargoed 5-fold CV** within IS for selecting the primary `K`. Embargo = 21 funding events on each side of the test fold.
- **Sign discipline:** direction locked in §1; not re-tested.

---

## 8. Trial set (counted honestly for DSR adjustment)

The equity-gauntlet failure showed that under-counting trials makes DSR ≈ vibes. A 4-trial deflation is too forgiving — a Sharpe of 0.6 clears DSR > 0.95 at N=4. We don't get that loophole.

**Rule:** *every parameter touched during IS work is a trial.* Not just the K sweep — every threshold tried during implementation, every cost-sensitivity variant, every universe filter that was considered, every quintile cutoff. The floor is **N_trials ≥ 15**; the actual number is whatever the trial log says.

**Enumerated commitments (these alone exceed 15):**

| # | Parameter | Locked value (this doc) | Counts as trial because… |
|---|---|---|---|
| 1-4 | Lookback K | {3, 9, 21, 63} | Multi-value IS sweep |
| 5 | Signal aggregator | median | Mean was also considered; pick justified pre-IS |
| 6 | Bucket count | quintile (5) | Tercile and decile were on the table |
| 7 | Bucket count alternative | tercile (3) | Logged as a trial even if not run, since it was an option |
| 8 | Bucket count alternative | decile (10) | Same |
| 9 | Direction | short top-funding | Long top-funding is the alternative null this rules out |
| 10 | Min basket eligibility | ≥15 symbols | ≥10 and ≥20 were on the table |
| 11 | Universe filter alt | ≥10 symbols | Trial |
| 12 | Universe filter alt | ≥20 symbols | Trial |
| 13 | Embargo length | 21 funding events (7d) | 14 and 42 were on the table |
| 14 | Embargo alt | 42 funding events | Trial |
| 15 | CV fold count | 5 | 3 and 10 were on the table |

That's the floor 15 *before any IS implementation begins*. The actual N_trials goes up from there; it does not go down.

**Trial log mechanism.** Before any code reads the OOS slice, `research/out/carry_study/trial_log.json` is committed to git. Schema:

```json
[
  {
    "trial_id": 1,
    "ts_utc": "2026-05-15T...",
    "parameter": "lookback_K",
    "value": 3,
    "rationale": "...",
    "scope": "IS-only",
    "is_metric": {"sharpe_mean": 0.0, "sharpe_std": 0.0}
  },
  ...
]
```

Every IS evaluation appends an entry. Every parameter discussed-but-not-run still appends an entry with `is_metric: null` (we tried, we counted, we didn't run it — still a trial because the option was on the table). The committed `trial_log.json` SHA goes in §12 alongside the design-doc SHA. No edits-after-OOS are tolerated; the log is append-only and frozen by the git commit.

**Selection rule.** `K_primary` is the K that maximizes CV-mean Sharpe within IS, with a tie-break toward larger K (lower cost). Only `K_primary` is evaluated on OOS. All other trials contribute to deflation; none get a second OOS look.

---

## 9. Pre-commit gates (binary, fixed before OOS evaluation)

The study is declared **PASS** if and only if **ALL** of the following hold on the OOS slice using `K_primary`:

1. Net annualized Sharpe (after all costs in §6) > **0.5**
2. Stationary-bootstrap 95% CI on annualized Sharpe excludes zero
3. Deflated Sharpe Ratio > **0.95**, deflated against the `N_trials` recorded in the committed `trial_log.json` (floor 15, actual number whatever the log says — see §8)
4. Realized annualized turnover < **800%** (≈ 2 round-trips/week-per-symbol ceiling; sanity-check against the cost model)
5. Sign agreement: IS-mean Sharpe and OOS-mean Sharpe share the same sign

If any one gate fails: **CLOSED FAILED**. No expanding the trial set, no relaxing cost assumptions, no silently rebranding as the basis study. Failure triggers a structured retrospective in the style of `PHASE6_WRITEUP.md`.

---

## 10. Out of scope (v0)

- Liquidation buffers, maintenance margin (positions are dollar-neutral, no leverage — defensible).
- Funding-rate forecasting beyond simple lookback median.
- Intra-period rebalances.
- L2 market-making, MARL, execution scheduling.
- Basis study (separate stub in `basis_study.py`; only activated if carry study passes, or definitively closed).

---

## 11. Cost-vs-signal sanity check (back-of-envelope, IS-only)

Realistic expectation under the assumed economics:
- Carry premium captured at K=21: cross-sectional `q95 spread × ρ_lag21 ≈ 5.79 × 0.30 ≈ 1.74 bps per 8h per side` (top vs bottom) ⇒ at 3 events/day × 365 = **1900 bps/year ≈ 19% gross annualized** under favorable conditions. Median-regime: smaller.
- Annual cost at weekly rebalance with ~30% turnover/rebalance: 52 × 0.30 × 36 ≈ **560 bps ≈ 5.6%**.
- Net annualized return target under favorable conditions: **~10-14%**. With ~8-10% realized vol, **observed annualized Sharpe target ≈ 1.0-1.5**.

**With N_trials ≥ 15, the DSR-implied minimum observed Sharpe is roughly 1.5–1.8 annualized** (depends on OOS skew and kurtosis; computed at evaluation time, not estimated here). That bar sits at the upper end of the favorable-case envelope above. The honest read: this is a tight gate. If the IS-inferred cross-sectional carry weakens even modestly in OOS, the strategy will miss DSR. That's a feature of the gate, not a flaw.

This is a *target*, not a guarantee. The strategy can plausibly clear the §9 gates if the inspection-implied cross-sectional persistence holds out-of-sample. It can plausibly miss if persistence decays, costs are mismodeled, or selection effects across symbols are larger than inspection suggests. A CLOSED FAILED outcome here is not a bug; it's the gate working.

---

## 12. Sign-off

This document is committed to git in its filled-in form BEFORE any code reads from the OOS slice. The commit SHA is the pre-commit timestamp. The `trial_log.json` SHA is the second pre-commit anchor — both must exist before `carry_study.py` runs OOS.

- User sign-off (commit author): _pending_
- Design-doc commit SHA (pre-commit moment): _pending_
- `trial_log.json` commit SHA (post-IS, pre-OOS): _pending — appended at IS completion_
- Implementation file: `research/carry_study.py` (currently stub; will be implemented after sign-off)
