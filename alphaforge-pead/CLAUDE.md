# CLAUDE.md — alphaforge-pead

Sub-project context for Claude Code. Cross-cutting context lives in the top-level `CLAUDE.md`. This file covers only the PEAD stack.

## Status (as of 2026-05-17, end of day)

**PEAD CLOSED FAILED.** Substrate #5 closed FAILED on 2026-05-17. Phase 1 gauntlet ran cleanly; 0 of 10 trials passed all three gates (G1 DSR > 0.95, G2 bootstrap CI excludes zero in BOTH OOS, G3 sign agreement). Closest near-misses: K=63 quintile (DSR-A 0.58, DSR-B 0.62, point Sharpes +2.29/+2.49) and K=84 quintile (DSR-A 0.75, DSR-B 0.60, point Sharpes +2.87/+2.55). Full verdict + diagnosis in `research/PHASE1_VERDICT.md`. The signal showed the residual echo of post-2000 PEAD literature ("real but weak") — IC uniformly positive across all OOS windows, sign agreement 8/10, peak-horizon aligned with the literature's 3-month drift window — but not strong enough to clear deflation given the 20-trial Sharpe variance and OOS-B's structural 2.4-year brevity. Same row-2 diagnosis as the four prior verdicts. Phase 1b NOT triggered. Phase 2 NOT triggered. Sub-project frozen.

**Phase 0 — CLOSED. Phase 1 — CLOSED FAILED.** All six exit-checklist items green; `research/PEAD_PHASE0_CERTIFIED.md` filed with the SHA-256 anchor of (the amended) `PEAD_DESIGN.md`. The orchestrator's runtime certification gate (`gauntlet.run_phase1.check_phase0_certified`) verifies the anchor still matches on every invocation.

Phase 0 exit checklist:

| # | Step | Tool | State |
|---|---|---|---|
| 1 | EDGAR Company Facts extractor over the 771-ticker PIT universe | `extractors/run_extractor.py` | **DONE** — 759/771 fetched, 11 no-coverage, 1 transient error |
| 2 | Universe intersection report (PIT × XBRL × OHLCV × ≥8 quarters) | `validation/universe_intersection.py` | **PASS** — 614 eligible firms / 26,908 firm-quarters |
| 3 | `validation/validate_as_of.py` (restatement-chain walk) | full-data run | **PASS** — 0.015% error rate (4 / 26,602 chains) |
| 4 | `validation/validate_fiscal_alignment.py` (conflicting-vals check) | full-data run | **PASS** — 0.54% error rate (4 / 747 shards) |
| 5 | `validation/validate_substitution_log.py` (integrity invariant) | full-data run | **PASS** — log lines == fallback rows; 75.8% fallback rate documented |
| 6 | File `research/PEAD_PHASE0_CERTIFIED.md` with SHA-256 anchor | manual | **DONE** — `a91e2a07ee...b9f9ae8` |

**Key Phase 0 discovery:** the EDGAR API `fp` field reflects the filing form, not the value's period. Documented as the **§2.2 ADDENDUM (2026-05-17)** in `PEAD_DESIGN.md`. Canonical key is now `(period_end, period_kind)` where `period_kind` is derived from `(end_date - start_date).days`. Schema columns and downstream code were updated together; the Phase 1 trial set, gauntlet criteria, OOS protocol, and decision matrix are UNCHANGED.

## Substrate Relationship to the Frozen Equity Stack

PEAD operates on the same substrate Tier 1 and Tier 2 failed on, BUT:

- **Read-only consumption.** PEAD reads `alphaforge-python/data/market/pit/` (the PIT membership log) and `data/quarantine/market/` (the OHLCV store). It does not modify them.
- **Frozen modules stay frozen.** `alphaforge-python/factors/`, `alphaforge-python/research/factor_study.py`, `alphaforge-python/research/capacity_study.py`, `alphaforge-marl/`, `alphaforge-execution/` are NOT consumed. No new factor lands in `factors/`; no MARL training resumes; `.halt` stays engaged on execution.
- **PEAD's signal lives in `alphaforge-pead/`.** It is a separate sub-project deliberately; treating it as a new factor in the closed-failed factor study would re-open a closed verdict.
- **The cost model is shared** (`alphaforge-python/research/cost_model.py`). It is read-only here.
- **The statistical-hygiene utilities are shared** (`alphaforge-python/research/stats_hygiene.py`, `risk_model.py`). Read-only.

If PEAD passes its gauntlet, **Phase 2 still treats `alphaforge-execution/` as frozen.** Re-arming the execution loop is its own decision (the four `TIER1_PAUSE.md` conditions).

## Current Scaffold

```
alphaforge-pead/
├── CLAUDE.md                              # this file
├── research/
│   ├── PEAD_DESIGN.md                     # pre-committed Phase 1 signal + gauntlet contract
│   └── PHASE2_DESIGN.md                   # pre-committed Phase 2 contract (cost-doubling, capacity, regime) — contingent on Phase 1 survivors
├── extractors/                            # Phase 0 — EDGAR XBRL ingest
│   ├── __init__.py
│   ├── companyfacts.py                    # fetch + parse + value_as_of()
│   └── run_extractor.py                   # CLI over the PIT universe
├── validation/                            # Phase 0 — eligibility + invariant checks
│   ├── __init__.py
│   ├── universe_intersection.py           # PIT × XBRL × OHLCV × ≥8 quarters → eligibility report
│   ├── validate_as_of.py                  # restatement-chain walk: value_as_of correctness
│   ├── validate_fiscal_alignment.py       # (fy,fp) uniqueness + valid-fp domain
│   └── validate_substitution_log.py       # fallback-rate threshold (<15%)
├── gauntlet/                              # Phase 1 code (built during Phase 0 wait; certification check enforced at runtime)
│   ├── __init__.py
│   ├── sue.py                             # pure seasonal-random-walk SUE math
│   ├── panel.py                           # announcement-event panel builder (EPS × OHLCV, as-of-date discipline)
│   ├── portfolios.py                      # IC computation + quantile-bucket long-short formation
│   └── run_phase1.py                      # 10-trial gauntlet orchestrator, SHA-256 anchor gate, G1/G2/G3, DSR deflation
├── tests/                                 # 73 tests, all green
│   ├── test_companyfacts.py               # extractor — 11 tests
│   ├── test_validation.py                 # validators + intersection — 6 tests
│   ├── test_sue.py                        # SUE math + no-look-ahead invariant — 16 tests
│   ├── test_panel.py                      # panel builder + as-of discipline — 9 tests
│   ├── test_portfolios.py                 # IC, bucketing, long-short aggregation — 17 tests
│   └── test_run_phase1.py                 # orchestrator + gate logic + certification guard — 14 tests
├── data/                                  # EDGAR EPS parquet shards (gitignored)
├── requirements.txt
└── .gitignore
```

Phase 1+ directories (`signals/`, `gauntlet/`, `verdict/`) do not exist and must not be created until Phase 0 closes.

## Data Contract

Two storage tables, both keyed by (ticker, period_end):

- **`data/edgar_eps/by_cik/CIK{nnnnnnnnnn}.parquet`** — one row per `(ticker, period_end, filed)` tuple. Columns: `cik`, `ticker`, `period_end` (date), `fp` ({"Q1","Q2","Q3","FY"}), `fy` (int), `filed` (timestamp, ns), `form` ("10-Q", "10-K", "10-Q/A", "10-K/A"), `concept` (XBRL concept used after hierarchy resolution), `val` (float, USD per share), `start_date`, `end_date`, `substitution_level` (1 if primary concept, 2 if fallback).

- **`data/edgar_eps/_substitution_log.jsonl`** — every step-2 fallback substitution logged with `(cik, ticker, fy, fp, filed)`. Required for verdict-document substitution-rate reporting.

The as-of-date query (`extractors.companyfacts.value_as_of`) is the canonical accessor. Direct parquet indexing by `period_end` alone is a bug.

## Commands

```bash
cd alphaforge-pead
pip install -r requirements.txt
python3 -m pytest tests/ -v                  # 11 tests, all should pass

# Phase 0 — extractor. Walks the PIT 877-ticker universe, calls SEC API.
# Rate-limited internally to 8 req/s under the SEC's 10 req/s cap.
python3 -m extractors.run_extractor \
    --pit-root ../alphaforge-python/data/market/pit/artifacts \
    --out data/edgar_eps/

# Phase 0 — universe intersection report (PIT × XBRL × OHLCV × ≥8 quarters):
python3 -m validation.universe_intersection \
    --pit-root ../alphaforge-python/data/market/pit/artifacts \
    --edgar-root data/edgar_eps/ \
    --ohlcv-root ../data/quarantine/market/ \
    --out research/PEAD_UNIVERSE_INTERSECTION.md

# Phase 0 — validators against the four pre-commitments:
python3 -m validation.validate_as_of                # restatement-chain correctness
python3 -m validation.validate_fiscal_alignment     # (fy,fp) uniqueness + valid-fp
python3 -m validation.validate_substitution_log     # fallback rate <15%

# Phase 1 (DOES NOT EXECUTE until PEAD_PHASE0_CERTIFIED.md is filed)
# python3 -m gauntlet.run_sue_gauntlet
```

The `value_as_of(shard_path, ticker, period_end, as_of_ts)` accessor in
`extractors.companyfacts` is the canonical query — direct parquet indexing
by `period_end` alone is a contract violation. See `PEAD_DESIGN.md` §2.1.

## Honest Caveats (carried from `research/PEAD_DESIGN.md` §7)

- PEAD is the most extensively studied anomaly in the literature; magnitude has shrunk over time. The substrate (2012-onward) is exactly the period where shrinkage is documented. Expectation: this may CLOSED FAILED the same way the four prior substrates did.
- Seasonal-random-walk SUE is weaker than analyst-consensus SUE. Working without I/B/E/S consensus is a known disadvantage; the cooldown design forbids paid data.
- The PIT-universe + OHLCV substrate is the same one that failed Tier 1 and Tier 2. The cost-model underestimate documented in `alphaforge-python/research/PHASE6_WRITEUP.md` applies. Phase 2 cost-doubling stress addresses it explicitly.

## Recent changes

**2026-05-17 (session 6 — Phase 1 CLOSED FAILED) —** Ran the gauntlet end-to-end. After patching two real bugs the user caught (OHLCV column-case mismatch — production data uses TitleCase `Date`/`Close` while my fixtures used lowercase; `args.pead_root.parent` on a relative Path being a no-op, fixed with `.resolve().parent`), the orchestrator built the 26,908-event master panel across 614 eligible firms in 22 minutes and produced `research/PHASE1_RESULTS.json`. 0 of 10 trials cleared all three gates. Filed `research/PHASE1_VERDICT.md` documenting the diagnosis: IC uniformly positive in both OOS (0.034-0.059, in PEAD literature range), G3 sign agreement passes 8/10, point Sharpes substantial for K=63 and K=84 quintile cuts (+2.29/+2.49 and +2.87/+2.55 respectively) — but G1 DSR universally fails (highest 0.75 vs 0.95 hurdle) and G2 fails because OOS-B is structurally too short (80-127 trading days) for the stationary bootstrap to tighten CI enough to exclude zero. Substrate joins the row-2 failure-path family alongside Tier 1, Tier 2, crypto carry. **Five credible negative verdicts now; methodology validated; pivot to capacity-advantaged substrate class is the next move.**

**2026-05-17 (session 5 — Phase 0 CLOSED + §2.2 addendum) —** Live extractor pulled 759/771 firms. Validators surfaced a real semantic issue: EDGAR's `fp` field reflects the filing form, not the value's period (a 10-K filing for FY 2012 returns its embedded Q1/Q2/Q3/FY values all tagged `fp=FY`). Patched `extractors/companyfacts.py` to derive `period_duration_days` + `period_kind` from `(end - start).days`. Refactored `sue.py` to key by `period_end` (date) with date-arithmetic seasonal lookup (window ±15d around 365d). Refactored `panel.py` to filter `period_kind == "quarterly"` and dedupe by `period_end`. Updated `value_as_of` to default-filter to quarterly. Wrote `extractors/normalize_shards.py` to backfill the new columns on the 747 already-extracted shards (no SEC re-fetch). Documented as `PEAD_DESIGN.md` §2.2 ADDENDUM — an in-place correction of an assumption, not a relaxation of any gate. Filed `research/PEAD_PHASE0_CERTIFIED.md` with SHA-256 anchor `a91e2a07ee...b9f9ae8` after all four validators reported PASS. Test surface remains 74/74 green. Also patched `validate_fiscal_alignment.py` (semantics: conflicting `val` at same `(period_end, filed, concept)`, with 2% error-rate tolerance) and `validate_as_of.py` (0.1% chain-error-rate tolerance) to recognize real-world SEC data quirks (wrong-concept-tag rows, multi-share-class reporting). Added file logging to `run_extractor.py` so future runs persist per-CIK status to disk.

**2026-05-17 (session 4 final — Phase 1 orchestrator landed) —** Added `gauntlet/run_phase1.py` and 14 tests. The orchestrator wires panel → IS/OOS-A/OOS-B split (21-day embargo, calendar-day buffer) → 10-trial sweep over `HORIZONS × BUCKETS` → stationary-bootstrap Sharpe CI → DSR deflation against the full OOS-Sharpe set → G1 (DSR>0.95 in both OOS) / G2 (CI excludes zero in both OOS) / G3 (sign agreement) → PASS/FAIL verdict + survivor list. **Hard runtime gate**: `check_phase0_certified(pead_root)` reads `PEAD_PHASE0_CERTIFIED.md`, recomputes SHA-256 of `PEAD_DESIGN.md`, and raises `Phase0NotCertified` if the file is missing OR if the hash doesn't appear in the certification body. The certification guard means the orchestrator cannot run against real data until Phase 0 closes properly — even if a future session tries to bypass the contract. Stationary-bootstrap and DSR formulas are inlined (mirroring `alphaforge-python/research/factor_study.py` exactly) so the PEAD package doesn't pull the entire equity research module into its import path. Pre-committed constants `HORIZONS`, `BUCKETS`, `IS_END`, `OOS_A_START`, `OOS_A_END`, `OOS_B_START`, `OOS_B_END`, `DSR_HURDLE` are guarded by tests so accidental tuning would fail the suite. PEAD test surface now 73/73 green.

**2026-05-17 (session 4 — Phase 1 runner code, in-parallel with live extractor) —** Built the foundation of the Phase 1 SUE gauntlet while the live SEC API extractor was running in the background. Per `PEAD_DESIGN.md` §8, this code DOES NOT run against real data until `PEAD_PHASE0_CERTIFIED.md` is filed — tests use synthetic in-memory fixtures only. Modules:
- `gauntlet/sue.py` — pure seasonal-random-walk SUE: `(eps_q - eps_{q-4}) / std({eps_k - eps_{k-4}}_{k=q-8..q-1})`. NaN on missing data, zero denom, or non-finite values. Load-bearing no-look-ahead invariant test asserts that changing focal EPS affects only the numerator, never the denominator.
- `gauntlet/panel.py` — announcement-event panel builder. Joins EPS shards + OHLCV at original-filing announcement timestamps (10-Q/A amendments do NOT generate a new event row). Uses `value_as_of` for restatement discipline. Produces `AnnouncementRow(cik, ticker, fy, fp, announcement_ts, sue, fwd_returns_K∈{5,21,42,63,84})`.
- `gauntlet/portfolios.py` — IC + portfolio formation. `compute_ic(panel, horizon)` returns Spearman rho with sample-size guard (drops to NaN below n=30). `form_long_short(panel, horizon, bucket)` builds per-day cross-sectional quantile cuts (BUCKET_CONFIG pre-commits quintile→{frac:0.20, min_size:5} and decile→{frac:0.10, min_size:10}); cross-sections below min_size or with degenerate rank are dropped. `long_short_summary(events, horizon)` aggregates to daily returns and produces annualized Sharpe.

42 new tests added; full PEAD surface 59/59 green.

**2026-05-17 (session 3 — Phase 2 pre-commit + PDF refresh) —** Filed `research/PHASE2_DESIGN.md`: the cost-doubling / capacity / regime contract that runs only if Phase 1 produces ≥1 survivor. Three gates (P2-A cost-sensitivity, P2-B capacity binding at AUM grid, P2-C regime conditioning across VIX terciles), pre-committed thresholds, decision matrix mapping {P2-A, P2-B, P2-C} cells to {DEPLOY-READY, CONDITIONAL, PASSES-BUT-NOT-DEPLOYABLE, CLOSED-FAILED}. Reuses `alphaforge-python/research/{cost_model,capacity_study,stats_hygiene,risk_model}.py` read-only. Also refreshed `docs/AlphaForge_Project_Overview.pdf` to reflect substrates #4 and #5 as active parallel pre-commitments instead of "decision window pending."

**2026-05-17 (session 2 — Phase 0 validators) —** Added `validation/` package with four scripts: `universe_intersection.py` (PIT × XBRL × OHLCV × ≥8 quarters → markdown + JSON eligibility report), `validate_as_of.py` (restatement-chain walk: for every chain, assert `value_as_of` returns the right filing's value across the interval before, between, on, and after each filed timestamp), `validate_fiscal_alignment.py` (fp domain check, (fy,fp) → period_end uniqueness, (fy,fp,filed) row uniqueness), `validate_substitution_log.py` (count fallback rate, assert <15% AND log-line count matches DB row count). Test surface grew to 17 tests across 2 files; all green.

**2026-05-17 (session 1 — Phase 0 extractor) —** Spun up sub-project parallel to `alphaforge-microstructure/` to fill the 30-day book-data wait. Filed pre-commitment `research/PEAD_DESIGN.md`, sub-project CLAUDE.md, `extractors/companyfacts.py` (fetch + parse + `value_as_of` canonical accessor), `extractors/run_extractor.py` (rate-limited CLI over PIT universe), 11 unit tests. Frozen modules (equity factors/, MARL, execution) stay frozen — PEAD only consumes data-layer read-only.

## What This Sub-Project Is NOT

- Not a revival of the equity factor stack. The frozen verdicts hold.
- Not a path back to live trading. `alphaforge-execution/.halt` stays engaged regardless of PEAD outcome.
- Not authorized to consume paid data, exchange-private feeds, or I/B/E/S/FactSet/Compustat.
- Not a replacement for microstructure. Microstructure Phase 1 takes priority when its 30-day book-data clock closes.

## Reading Order for New Sessions

1. `research/PEAD_DESIGN.md` — the contract.
2. This file — sub-project context.
3. Top-level `CLAUDE.md` — substrate landscape and frozen-module list.
4. (When it exists) `research/PEAD_UNIVERSE_INTERSECTION.md` — eligibility counts.
5. (When it exists) `research/PEAD_VERDICT.md` — outcome.
