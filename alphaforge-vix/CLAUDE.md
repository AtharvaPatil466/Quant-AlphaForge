# alphaforge-vix — Sub-Project Context

**Status as of 2026-05-21 (end of session):** Substrate #7 (VIX/VRP at §9.1 0.10/VIX sizing) CLOSED FAILED. **Substrate #8 (VIX/VRP at VIX-baseline-anchored 10% sizing) ALSO CLOSED FAILED**. Both produced 0/28 deploy-ready. Substrate #8 was the project's seventh CLOSED FAILED verdict.

**The substrate #8 result revealed substrate #7's §17.8 diagnosis was partially wrong.** Substrate #8 sizes positions exactly 20× substrate #7 at every VIX level. Sharpes are essentially identical between #7 and #8 (e.g. `vrp_L63_thr4_hold5_A` OOS-A: #7 +0.23 → #8 +0.19). Reason: **Sharpe ratio is invariant to linear scaling of position size** — both mean and std of returns scale by k, the k cancels. §17.8's "sizing too small" diagnosis was an OVERSHOOT; the correct diagnosis (revealed by #8) is **Mode A revisited: the signal has real-but-modest OOS Sharpe (~0.5 best case) that cannot clear DSR > 0.95 against a 28-trial pre-commit at ~5-year OOS sample length regardless of sizing.** §17.8 was still right that cash-carry was inflating substrate #7's first-run pass (carry is additive to position PnL, so it DOES move Sharpe). Full discussion: `research/SUBSTRATE8_VERDICT.md` Discussion section.

**Phase 0 CERTIFIED + Phase 1 COMPLETE (10/18 VRP pass) + Phase 2 STRATEGY SPEC FROZEN + Phase 3 EXECUTED — CLOSED FAILED across BOTH substrate #7 (literal §9.1) AND substrate #8 (20× sizing).** 0 of 28 (trial × variant) combos clear all six gates in either substrate. Diagnosis (per §17.8 ADDENDUM filed pre-rerun and §14.17 known limitation): the literal §9.1 sizing formula `0.10 × pv / VIX` produces ~0.5% NAV exposure at VIX=20, so the strategy holds ~99.5% cash on most days. First run accidentally tested cash carry (18/28 apparently passed); §17.8 zeroed carry; re-run with carry=0 → 0/28 pass. Sharpes are -0.77 to +0.55 across all OOS combos — too small for DSR/bootstrap/CF gates. **Substrate #7 joins the six prior CLOSED-FAILED verdicts.** Pre-commit contract: `research/VIX_DESIGN.md`, SHA-256 `54e53be9... (post §17.8 ADDENDUM 2026-05-21)`. The constraint shift was partially correct: Phase 1 showed the premium exists; Phase 3 showed the pre-committed retail implementation can't extract enough of it to clear deflation. Full verdict: `research/GAUNTLET_VERDICT.md`.

This sub-project is **substrate #7** in the AlphaForge research program. Six prior substrates have been tested (5 CLOSED FAILED, 1 in flight — microstructure). VIX/VRP is the **first deliberate constraint shift of the project.**

The pre-committed contract lives in `research/VIX_DESIGN.md`. **Read it first.** No code in this sub-project may execute against the full Phase 0 data until the design doc is SHA-256 anchored in `VIX_PHASE0_CERTIFIED.md`.

---

## Pre-Commit Anchor

**`research/VIX_DESIGN.md` SHA-256:** `54e53be92f72e5161a4478cb8e518955d08164bfad0057675278fa2c49367b29`

Any edit to `VIX_DESIGN.md` invalidates this hash. The Phase 1 orchestrator (`research/phase1_run.py`) and the Phase 3 master runner (`gauntlet/run_gauntlet.py`) recompute the hash at runtime and refuse to execute if it doesn't match the value recorded in `VIX_PHASE0_CERTIFIED.md` / `vix_phase0_certified.json`. Verified working — Phase 1 + Phase 3 both ran successfully against their anchors on 2026-05-21.

**Prior anchors:** `22d468ce...` (initial, 2026-05-20), `56d745e7...` (post §17 ADDENDUM data-source discovery, 2026-05-21), `66a6c45a...` (post §17.7 ADDENDUM VRP forward-return proxy, 2026-05-21), `54e53be9...` (post §17.8 ADDENDUM cash-carry zeroing, 2026-05-21).

Pre-commit discipline: do not edit `VIX_DESIGN.md` after Phase 1 begins. ADDENDUM sections (§2-style, like PEAD's §2.2 and India's §17 addenda) are permitted only for in-place engineering discoveries that don't change the substantive contract. Document them explicitly.

---

## Why This Substrate is Structurally Different

**Substrates 1-6 all asked the same kind of question: "does this signal predict future returns?"** Cross-sectional rank on US equity (Tier 1, Tier 2). Carry on crypto perps. Post-earnings drift on EDGAR. Cross-sectional rank on Indian equity. The methodology produced six honest verdicts — each correctly identified the prediction-based signal as not robust enough to deploy. The unifying truth across six attempts: **at retail-data-grade, predictive anomalies are post-arbitrage.**

**Substrate #7 is the first to break the predictive assumption.**

The variance risk premium is not a prediction. It is a structural premium that exists because portfolio managers systematically overpay for insurance against tail events. The edge is being the insurance writer — accepting a known, catastrophic risk in exchange for a steady premium. Bondarenko (2004) and Carr & Wu (2009) document the premium's existence. The question is whether a retail implementation survives:

- **Honest costs** (Gate 4 doubled-cost stress)
- **Tail risk accounting** (Gate 6 Cornish-Fisher Sharpe, new gate)
- **Max-drawdown bound** (Gate 5 — 30% per stress period, 4-of-4 required; replaces prior substrates' Sharpe-positive Gate 5)
- **DSR deflation** (Gate 1 across 28 trials)
- **Disguised factor exposure** (§7 four-factor residualization: SPY, ΔVIX, ST-Reversal, Carry)

If VIX passes, it is the first deployable signal in the project. If it fails, the failure mode tells you something specific (premium arbitraged away, tail risk too severe at retail sizing, or disguised factor exposure) and informs whether the next substrate-class search is worth attempting at the current constraint set.

---

## Strategy Class

- **Edge type:** structural premium harvest (NOT predictive).
- **Counterparty:** insurance writer to portfolio managers buying protection.
- **Capacity:** large at institutional level; retail-tradeable via VXX/SVXY ETPs.
- **Holding profile:** 5-21 days for VRP, monthly for term-structure, event-driven for mean reversion.
- **Tail risk:** catastrophic. Known historical 1-day losses of 90%+ (Volmageddon 2018) for unhedged variants.

---

## Phase 0 Architecture (per VIX_DESIGN.md §2)

```
data/                          ← raw downloads + processed Parquet
  vix_futures/                 ← REMOVED per §17 ADDENDUM (CBOE paid-only)
  vix_indices/                 ← VIX/VIX1D/9D/3M/6M term structure (CSV; live)
  spy_returns/                 ← (unused — SPY parquet lives in etps/)
  etps/                        ← SPY/^VIX/SVXY/VXX parquets
  processed/                   ← (unused — products consumed direct from etps/+ vix_indices/)

ingest/                        ← (BUILT — Phase 0 layer)
  cboe.py                      ← CBOE 5-index downloader (atomic writes, panel builder, CLI)
  yfinance_loader.py           ← SPY/^VIX/SVXY/VXX loader with SVXY regime tag
  realized_vol.py              ← daily log-returns + 10/21/63d realized vol (VIX-percent units)
  fred.py                      ← DGS3MO downloader with fallback constants per §14.7
  validator.py                 ← Phase 0 exit-criteria checks (5 active, 2 SKIP)

signals/                       ← (BUILT — Phase 1 layer)
  vrp.py                       ← VRP = VIX − realized_vol; 18 trials; signed-positive IC
  term_structure.py            ← slope_3M/slope_6M/slope_diff; 6 trials; contango sanity
  regime.py                    ← VIX-bucket characterization for Phase 2 sizing

gauntlet/                      ← Phase 3 gauntlet kernel — BUILT and EXECUTED
  strategy.py                  ← §9 + §17.4 — sizing, hedge variants, exit-rule state machine
  costs.py                     ← §6 — ETP cost stack (baseline+gate4) + stress widening + CarryTable
  backtest.py                  ← single-instrument event-driven kernel (no look-ahead, T+1 fill)
  stats.py                     ← DSR, stationary-bootstrap CI, Cornish-Fisher (pure numpy)
  tail_risk.py                 ← Gate 5 max-drawdown + Gate 6 CF-Sharpe wrappers
  residualization.py           ← §7 four-factor OLS with HC0 SEs
  run_gauntlet.py              ← master runner — SHA-anchored; 28 combos × 6 gates + residualization

tests/                         ← 237 tests passing + 4 network-skipped (Phase 0 + Phase 1 + Phase 2 + Phase 3)

research/
  VIX_DESIGN.md                ← THE CONTRACT (locked, SHA `54e53be9... (post §17.8 ADDENDUM 2026-05-21)`)
  VIX_PHASE0_CERTIFIED.md      ← filed; 5 PASS / 2 SKIP; re-anchored 2026-05-21 post-§17.8
  PHASE2_STRATEGY_SPEC.md      ← Phase 2 per-survivor frozen spec (SHA `18173b6d...`)
  vix_phase2_spec.json         ← SHA pin + survivor inventory machine output
  phase0_certify.py            ← Phase 0 orchestrator (SHA-anchors current design doc)
  phase1_run.py                ← Phase 1 orchestrator (refuses to run on SHA mismatch)
  PHASE1_RESULTS.json          ← Phase 1 machine output (24 trials, per-horizon IC, yearly IC)
  PHASE1_VERDICT.md            ← Phase 1 human verdict — Phase 2 OPEN
  GAUNTLET_RESULTS.json        ← Phase 3 machine output (28 × 6 gates + residualization detail)
  GAUNTLET_VERDICT.md          ← Phase 3 human verdict — CLOSED FAILED
```

---

## Key Pre-Committed Decisions (frozen in VIX_DESIGN.md)

1. **28 trials** (18 VRP + 6 term-structure + 4 mean-reversion). DSR deflation against 28.
2. **Two hedge variants** (unhedged + OTM-call hedged) for each trial = 56 total strategy-trial combos evaluated. Effective search ≈ 2× the 28-denominator (documented §14.9).
3. **Substrate window:** 2004-03-26 → present. IS = 2004-2014 (10.7y), OOS-A = 2015-2019 (5y), OOS-B = 2020-present (5.4y). 21-day embargo.
4. **Six gates** (Gate 5 is max-drawdown ≤ 30% per stress period 4-of-4; Gate 6 is new Cornish-Fisher Sharpe > 0.5).
5. **Position sizing:** `max_notional = 0.10 × portfolio_value / VIX_level`. Auto-deleverages on elevated VIX.
6. **Hard stop:** VIX +40% intraday → kill all positions.
7. **Signal exit:** VRP < 0 → exit short. Other signals per their pre-commit.
8. **Four-factor residualization:** SPY, ΔVIX, ST-Reversal, Carry. HC0 SEs. Alpha t-stat > 1.96 required.

---

## What Touches What

- **READ-ONLY** consumers from this sub-project: none yet. Phase 0 data lives here only.
- **READ-ONLY consumers OF this sub-project:** none yet. The gauntlet will reuse the equity event-driven engine (`alphaforge-python/backtest/event_driven/`) read-only, adapted for futures instruments.
- **Frozen modules NOT touched:** `alphaforge-python/factors/`, `alphaforge-marl/`, `alphaforge-execution/`. VIX does NOT unfreeze these. `.halt` stays engaged regardless of outcome.
- **Independent data flow.** CBOE for VIX, yfinance for SPY + ETPs, FRED for risk-free. No equity-stack dependencies.

---

## Reading Order for New Sessions

1. `research/GAUNTLET_VERDICT.md` — Phase 3 outcome: CLOSED FAILED. Read the Discussion section for diagnosis.
2. `research/VIX_DESIGN.md` — the contract (SHA `54e53be9... (post §17.8 ADDENDUM 2026-05-21)`). §17.8 is the load-bearing finding.
3. `research/PHASE1_VERDICT.md` — Phase 1 outcome: 10 VRP survivors (signed-positive IC). Important context: Phase 1 succeeded, Phase 3 failed at honest sizing.
4. `research/PHASE2_STRATEGY_SPEC.md` — per-survivor frozen execution spec (SHA `18173b6d...`).
5. This `CLAUDE.md`.
6. Top-level `/CLAUDE.md` for the broader substrate landscape.
7. For prior-substrate context informing the constraint shift: `alphaforge-india/research/GAUNTLET_VERDICT.md` + `alphaforge-pead/research/PHASE1_VERDICT.md`.

---

## Commands

```bash
# Run the test suite (179 tests + 4 network-skipped as of 2026-05-21)
cd alphaforge-vix
python3.13 -m pytest tests/ -v --tb=short

# Phase 0 downloaders (already executed; rerun to refresh data)
python3.13 -m ingest.cboe --output-root data -v
python3.13 -m ingest.yfinance_loader --output-root data -v

# Phase 0 certification (refuses to certify if SHA-anchor mismatches)
python3.13 -m research.phase0_certify

# Phase 1 — VRP + slope IC analysis + regime characterization
# Reads from data/, writes research/PHASE1_RESULTS.json + research/PHASE1_VERDICT.md
python3.13 -m research.phase1_run -v

# Phase 2 deliverables are static (research/PHASE2_STRATEGY_SPEC.md +
# gauntlet/strategy.py + gauntlet/costs.py). No orchestrator — the spec
# is consumed at Phase 3 run time.
```

---

## Recent Changes

- **2026-05-20** (scaffold):
  - `research/VIX_DESIGN.md` written (16 sections, 501 lines). SHA-256 anchored at `22d468ce...`.
  - Directory tree scaffolded with .gitkeep placeholders. No code yet (per pre-commit discipline).
  - Top-level CLAUDE.md updated to add VIX as substrate #7 / component #9.
  - Memory entry filed.
  - Substrate framed as the project's first **constraint shift**: from predictive alpha to structural premium harvest. Fourth §7-cooldown override.

- **2026-05-21 — Phase 0 spike test + §17 ADDENDUM:**
  - Two-round spike test across 22 candidate URLs (`/tmp/vix_spike/spike.py`, `spike2.py`).
  - **Working:** VIX spot + VIX1D/9D/3M/6M via `cdn.cboe.com`; SPY/^VIX via yfinance with full history (1990+); SVXY 2011-10-04+; VXX 2018-01-25+ (post-relaunch only).
  - **BLOCKED:** CBOE VIX futures historical settlements — all 5 URL patterns return 403 (migrated to paid DataShop). FRED CSV timed out twice from sandbox (worth retrying from Mumbai machine).
  - **§17 ADDENDUM filed** (2026-05-21). Substrate window UNCHANGED. Trial set UNCHANGED. Gates UNCHANGED. Re-scoped: §1.3 slope signal uses VIX3M/VIX index ratio (not futures); §2.1 futures settlement download REMOVED from Phase 0; §9.2 hedge instrument changed from "long OTM VIX calls" → "long VXX at fixed 10% notional ratio" (post-2018 only — pre-2018 VXX unavailable); Variant B has roughly half the OOS evidence of Variant A (documented §14.14).
  - **New SHA-256: `56d745e7...`** (was `22d468ce...`).

- **2026-05-21 — Phase 3 EXECUTED — CLOSED FAILED (substrate #7 verdict):**
  - **`gauntlet/backtest.py`** (~320 LOC) — single-instrument event-driven backtest kernel (no look-ahead, T+1 fill, per-fill cash costs); MarketData wrapper, TrialSpec, BacktestResult; vrp_entry_signal + mean_reversion_entry_signal; trade log + daily NAV.
  - **`gauntlet/stats.py`** (~230 LOC) — `annualized_sharpe`, `sample_skewness`, `sample_excess_kurtosis`, `cornish_fisher_sharpe` (= Sharpe / |z_CF/z| per §5.6 design), `deflated_sharpe_ratio` (Bailey-LdP with σ̂(SR)-scaled E[SR_max] per eq. 6 + 9), `stationary_bootstrap_sharpe_ci` (Politis-Romano geometric blocks).
  - **`gauntlet/tail_risk.py`** (~190 LOC) — Gate 5 max-drawdown per stress period (per-period coverage classification: COVERED/PARTIAL/NO_DATA per Phase 2 §6), Gate 6 CF-Sharpe wrapper.
  - **`gauntlet/residualization.py`** (~170 LOC) — §7 4-factor OLS with HC0 SEs; alpha t-stat > 1.96 gate; provisional flag for missing factors per §7 falloff.
  - **`gauntlet/run_gauntlet.py`** (~360 LOC) — master runner: SHA-anchored refusal on design-doc OR Phase-2-spec mismatch; enumerates 28 (trial × variant) combos; runs baseline + Gate-4 doubled-cost backtests; evaluates all 6 gates + residualization; writes GAUNTLET_RESULTS.json + GAUNTLET_VERDICT.md with discussion.
  - **§17.8 ADDENDUM filed** (2026-05-21) BEFORE re-running. Locks cash-carry to 0 in the Phase 3 implementation. Rationale: §6 carry was designed for posted-margin on FUTURES (removed by §17.2); under §17.3 SVXY-only execution there is no margin to post. First gauntlet run with default carry produced 18/28 apparent passes — all driven by ~99.5%-cash NAV earning T-bill carry. §17.8 corrects this; direction-of-effect makes Phase 3 strictly harder. New design-doc SHA `54e53be9...`. VIX_PHASE0_CERTIFIED.md re-anchored.
  - **§14.17 + §14.18 (new known limitations).** §14.17: the §9.1 sizing formula `0.10 × pv / VIX` produces ~0.5% NAV exposure at VIX=20; verdict at this sizing tests "does the signal exist?" not "can it scale?". §14.18: Gate 5 coverage check uses NAV-existence not tradeable-instrument-existence; inflates Variant A's G5 pass rate but doesn't change the verdict (every trial fails G1/G2/G6 regardless).
  - **45 new tests** (test_stats.py 25, test_backtest.py 14, test_tail_risk.py 8, test_residualization.py 8). 237 total pass + 4 network-skipped.
  - **Phase 3 outcome — CLOSED FAILED (0/28 deploy-ready):**
    - VRP path: OOS-A Sharpes -0.77 to +0.23, OOS-B Sharpes -0.18 to +0.55. DSR universally < 0.95 (max 0.255). 6 trials pass G3 (sign agreement), 5 pass G4 (cost survival), 0 pass G1 / G2 / G6.
    - Variant B (VXX hedge) universally worse than Variant A in OOS-A — VXX contango drag exceeds the protection it provides during calm.
    - Mean-reversion path: similar pattern. Strongest near-miss `mr_k2.0_to_MA+1sigma_A` with OOS-A Sharpe +0.47, OOS-B +0.12 — but DSR 0.255/0.043.
    - **Diagnosis:** at §9.1's 0.5% NAV sizing, the VRP/MR signal — even when directionally correct — produces dollar PnL too small to clear DSR after deflation against 28 trials. Phase 1 evidence of premium existence remains valid; Phase 3 evidence of pre-committed retail implementation being insufficient is also valid. Not contradictory.
  - **First Phase-3-CLOSED-FAILED post-Phase-1-PASS in the project.** Substrate #7 joins the six prior CLOSED-FAILED verdicts. Full verdict + Discussion section: `research/GAUNTLET_VERDICT.md`.

- **2026-05-21 — Phase 2 STRATEGY SPEC + gauntlet strategy/cost layer BUILT:**
  - **`research/PHASE2_STRATEGY_SPEC.md`** (SHA `18173b6d...`) — per-survivor frozen execution spec. Operationalizes §9 + §17.4 into concrete parameters for each of the 10 VRP survivors + 4 mean-reversion trials × 2 variants = 28 strategy-trial combos. Two pieces of audit-friendly operationalization: §5.6 `holding_period` = minimum-hold before signal exit; §6 Gate 5 effective denominator = covered-stress-periods-only (necessary consequence of §17 SVXY-only). Both filed before Phase 3 runs.
  - **`gauntlet/strategy.py`** (380 LOC) — pure-function operationalization: position sizing (§9.1), SVXY exposure multiplier (§17.3 regime split at 2018-02-27), hedge variant builder for Variant A (unhedged) + Variant B (SVXY + 10% VXX hedge per §17.4), exit-rule state machine (hard stop on VIX +40% intraday, signal exit on VRP<0 for short-vol or VIX threshold for mean-reversion, 60-day time-based force-close). HedgeUnavailableError for Variant B pre-2018 + LONG_VOL pre-VXX. All frozen constants exposed at module scope.
  - **`gauntlet/costs.py`** (200 LOC) — ETP cost stack: baseline 10bp round-trip, gate4 20bp variant, 3× widening during pre-committed stress periods. `CarryTable` class for margin financing carry via FRED DGS3MO with §14.7 fallback constants (tiered by year window — ZIRP era 30bp, current 450bp). Stress periods frozen at 4 windows (2008/2011/2018/2020).
  - **Tests: 45 new** (test_strategy.py 26, test_costs.py 19). **179 total tests pass + 4 network-skipped.**
  - **Phase 3 unblocked.** Next session builds the backtest kernel (adapts equity event-driven engine), DSR/bootstrap/CF-Sharpe stats, 4-factor residualization, and `gauntlet/run_gauntlet.py` master runner.

- **2026-05-21 — §17.7 ADDENDUM + Phase 1 EXECUTED — Phase 2 OPEN:**
  - **§17.7 ADDENDUM filed** before any Phase 1 code ran against the data. Locks the VRP forward-return proxy as `-log(VIX_{t+h}/VIX_t)` (pure spot-VIX, no futures, no inferred terms). Founder-approved 2026-05-21. Direction-of-effect note: spot proxy underestimates IC vs the contracted-but-unavailable VIX-futures proxy → makes Phase 1 harder, not easier.
  - **VIX_DESIGN.md SHA → `66a6c45a...`** (was `56d745e7...`). VIX_PHASE0_CERTIFIED.md + vix_phase0_certified.json re-anchored. Phase 0 PASS/SKIP set unchanged (Phase 0 validates data availability, not signal definitions).
  - **`signals/vrp.py`** (286 LOC) — 18-trial enumeration, VRP series, forward-return proxy, signed-positive Pearson IC, yearly-sign analysis, per-trial pass/fail with §8.1 three-test rule.
  - **`signals/term_structure.py`** (255 LOC) — 6-trial enumeration (slope_3M, slope_6M, slope_diff × 2 thresholds), contango sanity check (§8.2 block-if-broken), evaluate_all.
  - **`signals/regime.py`** (110 LOC) — Phase 1C VIX-bucket characterization (low_vol < 15, normal 15-25, elevated 25-35, crisis ≥ 35) with per-year crisis fraction.
  - **`research/phase1_run.py`** (340 LOC) — orchestrator with hard SHA-anchor refusal; loads Phase 0 products; runs 1A/1B/1C; emits PHASE1_RESULTS.json + PHASE1_VERDICT.md with discussion section.
  - **Tests: 40 new tests** (test_vrp.py 17, test_term_structure.py 12, test_regime.py 5, test_phase1_run.py 6). 134 total pass + 4 network-skipped.
  - **Phase 1 outcome — Phase 2 OPEN:**
    - VRP: **10/18 trials pass** signed-positive IC. Strongest: `vrp_L63_thr4_hold5` peak IC `+0.180` at h=21 (9/11 years, 8/9 ex-2008/09). Pass rate by threshold: thr=0 → 0/6, thr=2 → 4/6, thr=4 → 6/6 — higher VRP entry threshold (richer premium) passes more reliably, consistent with §1.2 mean-reversion story.
    - Slope: **0/6 trials pass** — all six trials produce *negative* peak IC under the spot-VIX proxy. Contango sanity check FAILED: contango days (n=1227) average +0.012 21-day Δlog VIX (i.e., spot VIX drifts UP slightly in contango), not down. Empirical realization of §17.7 limitation — futures-roll-yield mechanism does NOT translate to spot-VIX index changes.
    - Mean-reversion: 4 trials deferred to Phase 3 per §4.3 (event-driven, not IC-tested).
  - **First substrate of seven not to close FAILED at Phase 1.** Slope path closed; VRP path lives. 10 survivors + 4 deferred mean-reversion = 14 of 28 trials reach Phase 3 evaluation eventually. DSR denominator stays at 28.

- **2026-05-21 — Phase 0 ingest layer built + CERTIFIED:**
  - `ingest/cboe.py` (256 LOC) — 5-index downloader, atomic writes, parser, panel builder, CLI. 25 unit tests + 1 live network smoke. 5/5 CBOE indices downloaded (1.17 MB).
  - `ingest/yfinance_loader.py` (210 LOC) — SPY/^VIX/SVXY/VXX downloader with SVXY regime tag (-1× vs -0.5× boundary 2018-02-27). 18 unit tests. 4/4 tickers downloaded.
  - `ingest/realized_vol.py` (170 LOC) — daily-log-return + 10/21/63-day rolling realized vol IN PERCENT (VIX units, so `VRP = VIX − realized_vol` units-consistent). 5-spike validator for 2008/2010/2015/2018/2020 events. 14 tests.
  - `ingest/fred.py` (175 LOC) — DGS3MO downloader with retry + fallback constants per §14.7. 12 tests. (Live FRED times out from sandbox; fallback covers Phase 0.)
  - `ingest/validator.py` (260 LOC) — 5 active checks + 2 documented SKIPs (futures, FRED) per §17 ADDENDUM. Markdown + JSON output. 19 tests.
  - `research/phase0_certify.py` (140 LOC) — orchestrator. SHA anchor, loads all products, runs validator, writes cert. 6 tests.
  - **Total: 94/94 tests pass + 4 network-skipped.**
  - **`research/VIX_PHASE0_CERTIFIED.md` filed:** 5 PASS / 0 WARN / 0 FAIL / 2 SKIP. Substrate is CERTIFIED, anchored to SHA `56d745e7...`.
  - **Live data products on disk (real, downloaded today):**
    - CBOE: 5 indices, 9188 dates union, 1990-01-02 → 2026-05-19.
    - yfinance: SPY (8384 rows), ^VIX (9163), SVXY (3678 with regime tags), VXX (2091 post-relaunch).
    - Cross-checks: CBOE-VIX vs yfinance-^VIX correlation = 1.0000 over 9158 dates; VIX3M ≥ VIX on 92.3% of overlapping days (strong contango bias — the structural premium the strategy is meant to harvest).
  - **Phase 1 is now unblocked.** Per §15 hard rules, `VIX_DESIGN.md` is frozen from this point. The Phase 1 orchestrator (when built) will SHA-check `56d745e7...` at runtime.
