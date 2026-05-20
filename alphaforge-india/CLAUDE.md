# alphaforge-india — Sub-Project Context

**Status as of 2026-05-18:** Phase 0 INGEST + VALIDATOR + EXPIRY-CALENDAR LAYERS BUILT. 101 unit tests + end-to-end smoke against real NSE data (legacy 2008-04-01, unified 2024-01-08) all green. Full-history download not yet run. No signal computed. No backtest run.

This sub-project is **substrate #6** in the AlphaForge research program. Five prior substrates have closed FAILED (equity Tier 1, Tier 2, crypto carry, PEAD), one is in flight (microstructure #4, Phase 0 book-data accumulation through ≈ 2026-06-17). India is **parallel substrate work** alongside microstructure.

The pre-committed contract for the entire research arc lives in `research/INDIA_DESIGN.md`. **Read it first.** No code in this sub-project may execute against full historical data until the design doc has been SHA-256 anchored and Phase 0 has been certified.

---

## Pre-Commit Anchor

**`research/INDIA_DESIGN.md` SHA-256:** `3b397262d5799f7fe6b583b9c97d8eee6d07852611ec8c046a7c717ca1b031b9`

Any edit to `INDIA_DESIGN.md` invalidates this hash. The Phase 1 orchestrator (when built) will recompute the hash at runtime and refuse to execute if it doesn't match the value recorded in `research/INDIA_PHASE0_CERTIFIED.md` (filed at Phase 0 close).

Pre-commit discipline: do not edit `INDIA_DESIGN.md` after Phase 1 begins. ADDENDUM sections (§2-style, like PEAD's §2.2 addendum) are permitted only for in-place engineering discoveries that don't change the substantive contract. Document them explicitly.

---

## Strategy Class

**Event-driven and flow-based, not cross-sectional rank-based.** This distinction is load-bearing. Every prior substrate failed as a cross-sectional rank study under the same row-2 mechanism (real signal, eaten by costs + multiple-testing deflation). This substrate explicitly chooses signals that are NOT in that class:

1. **Delivery percentage anomaly** (primary) — within-stock z-score of NSE-published daily delivery %. Conviction accumulation vs speculative distribution.
2. **FII/DII flow imbalance** (secondary) — market-level signal on SEBI-mandated daily institutional flow disclosure.
3. **F&O expiry effect** (tertiary) — event study around monthly NSE F&O expiry.

All three signals exploit data structures that do not exist in US equity datasets.

---

## Phase 0 Architecture (per INDIA_DESIGN.md §2)

```
data/                          ← raw downloads + processed Parquet
  bhavcopy/                    ← legacy bhavcopy CSV zips (2004 → ~2020)
  mto/                         ← MTO .DAT delivery files (2004 → ~2020)
  unified/                     ← sec_bhavdata_full CSV (~2020 → present)
  processed/                   ← unified-schema Parquet output
  fii_dii/                     ← FII + DII daily files
  fo_expiry/                   ← F&O bhavcopy + validated expiry calendar
  universe/                    ← Nifty 500 PIT membership log

ingest/
  __init__.py                  ← package init
  schema.py                    ← unified Parquet schema (15 columns)
  downloader.py                ← BUILT — checkpointed two-era downloader + CLI
  parser_legacy.py             ← BUILT — pre-2020 bhavcopy + MTO join, TOTTRDQTY cross-check
  parser_unified.py            ← BUILT — post-2020 unified format
  validator.py                 ← BUILT — Phase 0 exit-criteria checks (5 active + 4 skipped/blocked)
  expiry_calendar.py           ← BUILT — F&O monthly expiry generator + 50-date spot-check validator

universe/                      ← (NOT YET BUILT)
  isin_master.py               ← NSE ISIN master loader + rename graph
  pit.py                       ← PIT membership accessor

signals/                       ← (Phase 1, not built)
  delivery_pct.py
  fii_dii_flow.py
  fo_expiry.py

gauntlet/                      ← (Phase 3, not built)
  backtest.py
  costs.py
  stats.py
  run_gauntlet.py

tests/
  conftest.py                  ← shared NSE-format fixtures
  test_downloader.py           ← 30 tests, fake-session, no live network
  test_parser_legacy.py        ← 17 tests
  test_parser_unified.py       ← 12 tests
  test_validator.py            ← 22 tests
  test_expiry_calendar.py      ← 20 tests

research/
  INDIA_DESIGN.md              ← THE CONTRACT (locked, SHA-256 anchored)
  INDIA_PHASE0_CERTIFIED.md    ← (filed at Phase 0 close)
  PHASE1_RESULTS.json          ← (Phase 1 output)
  GAUNTLET_VERDICT.md          ← (Phase 3 output)
```

---

## Three Spike-Test Findings Baked Into Phase 0

Found 2026-05-18 in the 30-date spike test (`/tmp/nse_spike/`); now frozen as engineering pre-commits in `INDIA_DESIGN.md` §2.2-2.4:

1. **Two-era loader.** Pre-2020 = `legacy bhavcopy + MTO` joined on `(date, SYMBOL, SERIES)`. Post-2020 = `sec_bhavdata_full` directly. Cross-check `TOTTRDQTY == QUANTITY_TRADED`; mismatches quarantined.
2. **SERIES=EQ filter at ingestion.** Non-EQ rows have `DELIV_PER == "-"`; they're dropped at ingest, never enter signal compute. The "DELIV_PER 100% coverage" figure is only valid after this filter.
3. **ISIN absent from bhavcopy.** Symbol-continuity via a separate ISIN master file + circular-archive rename graph. Structurally more fragile than the CIK-based equity differ — documented in §14.

## Two Operational Pre-Commits

1. **Checkpointing downloader is mandatory.** Full pull is ≈ 16,500 requests / ~5 hours. Per-(date, source) checkpoint to `data/processed/_download_checkpoint.jsonl`.
2. **Holiday calendar built empirically.** Any weekday where all three sources return 404 is logged. Validation pass cross-checks against 5 calendar years of major Indian holidays.

---

## Five Locked Design Decisions

From the 2026-05-18 gap-closure pre-commit exchange:

1. **Spike-first.** Done. PASSED 2026-05-18. 0/30 IP bans.
2. **Delivery percentage IS = 2004-2014** with mandatory dual-window IC report in Phase 1A (full IS + 2010-onward sub-window separately; sign agreement required).
3. **Cost model = full Indian regulatory stack.** ≈ 13.7bp buy + 22.2bp sell + STT + impact. Gate 4 doubles the full stack.
4. **Gate 5 = 4-of-4 stress periods + 60% positive months within each.** Tightened from the 3-of-4 default.
5. **Four-factor residualization** — market, risk-free, size (free-float-mcap mimicking), liquidity (Amihud mimicking). HC0 SEs on alpha intercept.

---

## What Touches What

- **READ-ONLY** consumers from this sub-project: none yet. The PIT universe layer (when built) will be analogous to `alphaforge-python/data/market/pit/` but India-specific.
- **READ-ONLY consumers OF this sub-project:** none yet. The gauntlet (when built) will reuse the equity event-driven engine (`alphaforge-python/backtest/event_driven/`) read-only.
- **Frozen modules NOT touched:** `alphaforge-python/factors/`, `alphaforge-marl/`, `alphaforge-execution/`. India does NOT unfreeze these. `.halt` stays engaged regardless of India outcome.

---

## Reading Order for New Sessions

1. `research/INDIA_DESIGN.md` — the contract (SHA: `3b397262...`, post-§17 ADDENDUM dropping FII/DII).
2. This `CLAUDE.md`.
3. Top-level `/CLAUDE.md` for the broader substrate landscape.
4. `/tmp/nse_spike/results.json` — the bhavcopy spike artifact that unblocked Phase 0.
5. `/tmp/nse_spike/fii_dii_probe.json` — the FII/DII spike that blocked §1.2 / led to §17 ADDENDUM.

---

## Commands

```bash
# Run the test suite (294 tests as of 2026-05-20 session 4)
cd alphaforge-india
python3.13 -m pytest tests/ -v --tb=short
# Note: tests need pandas + scipy + xlrd + openpyxl. The local Homebrew
# python3.14 has a broken pyexpat; use python3.13.

# Phase 0 download (idempotent on restart; resume just by re-running)
python3 -m ingest.downloader --start 2004-01-01 --end 2026-05-17 \
    --output-root data --verbose

# Smaller test pull
python3 -m ingest.downloader --start 2024-01-08 --end 2024-01-12 \
    --output-root data --verbose

# Phase 0 validator — markdown + JSON report
python3 -m ingest.validator --data-root data \
    --start 2004-01-01 --end 2026-05-17 \
    --universe-file path/to/nifty500_ever_members.txt \
    --report-md research/PHASE0_VALIDATION.md \
    --report-json research/phase0_validation.json

# F&O monthly expiry calendar (reads empirical holiday log)
python3 -m ingest.expiry_calendar \
    --holiday-log data/processed/_holidays.jsonl \
    --start 2004-01 --end 2026-12 \
    --out data/processed/fo_expiry_calendar.parquet

# Phase 0 certification report (markdown). Delegates to validator +
# expiry_calendar so SKIPs flip to PASS when data is present.
python3 -m research.phase0_certify

# Phase 1 orchestrator — 22 trials (18 deliv-pct + 4 F&O expiry).
# IS-only; produces PHASE1_RESULTS.json + PHASE1_VERDICT.md.
python3 -m research.run_phase1 \
    --processed-dir data/processed/bhavcopy \
    --expiry-calendar data/processed/fo_expiry_calendar.parquet \
    --results-json research/PHASE1_RESULTS.json \
    --verdict-md research/PHASE1_VERDICT.md

# Phase 3 orchestrator — runs 5-gate gauntlet on Phase 1 survivors.
# OOS-A + OOS-B; produces PHASE3_RESULTS.json + GAUNTLET_VERDICT.md.
# Verdict: DEPLOY-READY / CONDITIONAL / CLOSED FAILED per §12.
# Pass --factor-matrix CSV to enable §7 four-factor residualization;
# without it the verdict is provisional.
python3 -m research.run_phase3 \
    --phase1-results research/PHASE1_RESULTS.json \
    --processed-dir data/processed/bhavcopy \
    --results-json research/PHASE3_RESULTS.json \
    --verdict-md research/GAUNTLET_VERDICT.md
```

Operational notes:
- Downloader checkpoint: `data/processed/_download_checkpoint.jsonl` (append-only; resume-safe).
- Empirical holiday log: `data/processed/_holidays.jsonl` (any weekday where all sources 404).
- TOTTRDQTY-vs-MTO disagreement log: `data/processed/_disagreements.parquet` (legacy era only).
- Validator exit code is nonzero on any blocking FAIL.

## Recent Changes

- **2026-05-18 session 1** (substrate scaffold):
  - Spike test on 30-date NSE bhavcopy sample → PASSED. 0/30 IP bans. All three file formats (legacy, MTO, unified) reachable. DELIV_PER 100% within SERIES=EQ rows.
  - `research/INDIA_DESIGN.md` written (16 sections, ~750 lines). SHA-256 anchored.
  - Directory tree scaffolded with .gitkeep placeholders. No code yet (per pre-commit discipline).
  - Top-level CLAUDE.md updated to add India as substrate #6 and fix the prior CLAUDE.md self-contradiction on PEAD status.
  - Memory updated.

- **2026-05-18 session 2** (ingest layer):
  - `ingest/downloader.py` — checkpointed two-era downloader with 3-retry exponential backoff, 403/429 halt protocol, empirical holiday detection, atomic writes, CLI driver. 30 unit tests against a fake session (zero live-network calls in tests).
  - `ingest/schema.py` — 15-column unified Parquet schema shared by both eras.
  - `ingest/parser_legacy.py` — pre-2020 bhavcopy + MTO join with TOTTRDQTY cross-check (mismatches quarantined to `_disagreements.parquet`). 17 tests.
  - `ingest/parser_unified.py` — post-2020 unified format → same schema. 12 tests.
  - **End-to-end smoke against real NSE data:** legacy 2008-04-01 (1202 EQ rows, 0 cross-check mismatches, deliv_pct mean 62.35) and unified 2024-01-08 (1815 EQ rows, 100% deliv_pct coverage, mean 53.84) both parsed cleanly with the canonical schema.
  - Total: 59/59 unit tests passing, real-data smoke green.

- **2026-05-18 session 3** (validator + expiry calendar):
  - `ingest/validator.py` — Phase 0 exit-criteria validator. Five active checks (`bhavcopy_coverage`, `eq_only`, `holiday_log_cross_check`, `deliv_pct_coverage`, `disagreements_rate`) + four skipped on upstream-module blockers (PIT universe, ISIN master, FII/DII, F&O expiry validation). Markdown + JSON report. CLI exits nonzero on any blocking FAIL. Includes fixed + variable-date known-holiday reference table for 5 reference years (2010, 2014, 2018, 2022, 2024). 22 tests.
  - `ingest/expiry_calendar.py` — Last-Thursday-of-month generator with backward holiday shift (Thu → Wed → Tue → ...). Defensive guard raises if shift escapes the calendar month. `validate_expiry_calendar` is the 50-date spot-check validator for §2.8.6. 20 tests.
  - **CLI smoke verified:** validator produces clean markdown report against empty data; expiry calendar correctly generates Jan-Jun 2024 expiries (no shifts in that window).
  - Total: 101/101 unit tests passing.

- **2026-05-19** (user-led; §17 ADDENDUM):
  - FII/DII spike test (`/tmp/nse_spike/fii_dii_spike*.py`) found `/api/fiidiiTradeReact` ignores all date parameters and all historical archive paths 404 / SSL-fail. Historical daily FII/DII data is not freely available.
  - User chose Option A (drop signal family) and filed §17 ADDENDUM: trial set reduced from 31 → 22, §1.2/§2.5/§4.2/§8.2/§14.5 marked CANCELLED, §14.12 added documenting the drop.
  - INDIA_DESIGN.md SHA updated: `81153990...` → `3b397262d5799f7fe6b583b9c97d8eee6d07852611ec8c046a7c717ca1b031b9`.

- **2026-05-19/20** (user-led; substrate stack):
  - `universe/isin_master.py` — NSE ISIN master loader + symbol rename graph.
  - `universe/pit.py` — Nifty 500 PIT membership log (~1068 lines), parses IndexInclExcl.xls, multi-layer scrip-name resolution.
  - `signals/cost_model.py` — full Indian regulatory cost stack (brokerage + GST + STT + exchange + SEBI + stamp duty + impact) + Corwin-Schultz spread estimator for §6 calibration check.
  - `signals/delivery_pct.py` — primary signal: rolling-mean delivery-pct z-score, bucket assignment, IC computation. `enumerate_trials()` returns the 18 pre-committed trials.
  - `signals/fo_expiry.py` — tertiary signal: event-study runner, 4 trials, §8.3 pass criteria built in.
  - `gauntlet/gates.py` — Five gates (DSR > 0.95, stationary-bootstrap CI, sign agreement, cost survival, regime stress) + `run_gauntlet()` orchestrator.
  - `gauntlet/residualization.py` — four-factor model (market, risk-free, SMB, Amihud-liquidity), HC0 SEs on alpha intercept per §7.
  - `research/phase0_certify.py` — Phase 0 certification report generator. Now delegates to validator + expiry_calendar (this session) so SKIPs flip to PASS once data is present.
  - `ingest/build_parquet.py` — orchestrator that drives parsers over downloaded raw files into the unified Parquet schema.

- **2026-05-20 session 4** (Phase 1 orchestrator + cert wiring):
  - `research/run_phase1.py` — Phase 1 orchestrator. Loads bhavcopy parquet, runs all 22 trials (18 delivery-pct + 4 F&O expiry), implements §8.1 dual-window IC mandate (full IS + 2010-onward sub-window with sign-agreement requirement), §8.3 event-study pass criteria. Outputs `PHASE1_RESULTS.json` + `PHASE1_VERDICT.md`. Exits nonzero on CLOSED FAILED.
  - `research/phase0_certify.py` wired into `ingest.validator` + `ingest.expiry_calendar` modules so checks 3/6/7/8 actually delegate (instead of returning SKIP placeholders). Cert report now reflects real data state — currently shows FAIL on gates 2/6/7 (incomplete bhavcopy + holiday log) and PASS on gate 4 (ISIN master).
  - **294/294 tests passing** on python3.13.

- **2026-05-20 session 5** (Phase 3 orchestrator):
  - `research/run_phase3.py` (~550 LOC) — Phase 3 gauntlet orchestrator. Loads Phase 1 survivors from `PHASE1_RESULTS.json`, recomputes long-short portfolio returns on OOS-A + OOS-B with full Indian cost stack deducted on rebalance days, runs all 5 gates via `gauntlet.gates.run_gauntlet`. Implements §12 decision matrix: **DEPLOY-READY** (all 5 pass) / **CONDITIONAL** (Gates 1-4 pass, Gate 5 fail) / **CLOSED FAILED** (no Gates 1-4 pass). Short-circuits to CLOSED FAILED when Phase 1 has zero survivors. Optional `--factor-matrix` CSV enables §7 residualization; without it the verdict is explicitly marked provisional. Outputs `PHASE3_RESULTS.json` + `GAUNTLET_VERDICT.md`.
  - F&O expiry Phase 3 emits a documented SKIP — daily-return construction for the event-driven strategy needs per-event high-OI stock universe (requires OI data we don't have). Follow-up.
  - 29 tests covering trial-name parsing, OOS panel loading, portfolio-return construction, gauntlet evaluation, classification logic, markdown rendering, CLI integration (synthetic-data end-to-end).
  - **323/323 tests passing** on python3.13.

- **2026-05-20 session 6** (parallel-to-download work — download running externally on user's machine, ~2017 in progress):
  - `ingest/progress.py` — read-only download progress monitor. Reads the live `_download_checkpoint.jsonl`, reports per-result/per-year counts, surfaces halt rows + recent failures, estimates ETA honoring the era split (pre-2020 = 2 sources/weekday, post = 1). 15 tests.
  - `research/build_factor_matrix.py` — orchestrator around `gauntlet.residualization.build_factor_matrix`. Loads bhavcopy → close + volume panels, builds the four-factor return matrix (MKT, SMB, LIQ), writes CSV consumable by `research/run_phase3.py --factor-matrix`. Risk-free defaults to 7%/yr constant if no CSV supplied. SMB falls back to close × volume proxy when no free-float-mcap data (documented). 14 tests.
  - `research/cs_calibration.py` — Phase 0 §6 deliverable. Samples 50 Nifty 500 stocks (seeded), computes Corwin-Schultz half-spread per stock per window (IS / OOS-A / OOS-B), compares against parametric 5 bp, flags any window above the 10 bp documentation threshold. **First real-data smoke produced: IS median 16.33 bp (3.3× parametric) — DIVERGENCE FLAGGED per §6 discipline.** OOS_A skipped (no data yet — download still in 2017). OOS_B median 6.62 bp (within threshold). Result documented, gauntlet cost numbers NOT changed (§15 hard rule). 19 tests.
  - **Defensive fix to four loaders** (`ingest.validator`, `research.run_phase1`, `research.run_phase3`, `research.build_factor_matrix`): added `drop_duplicates(subset=["date","symbol"])` because the user's `build_parquet.py` writes era-overlap dates twice in 2020 (128,806 exact-identical duplicate rows found). Loader files now also accept the `{YYYY}.parquet` canonical naming convention used by the user's build_parquet, not just `bhavcopy*.parquet`.
  - **371/371 tests passing.** Substrate now executable end-to-end against real downloaded data once download completes. Phase 0 §6 deliverable already produced (partial — needs OOS_A data).
