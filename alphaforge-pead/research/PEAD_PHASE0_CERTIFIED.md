# PEAD Phase 0 — CERTIFIED

**Date:** 2026-05-17
**Author:** Atharva Patil
**Anchor:** SHA-256 of `research/PEAD_DESIGN.md` (including the §2.2 addendum):

```
a91e2a07eebbc8661f8f83f05050f7baa0ca810c2725773dcb186f287b9f9ae8  research/PEAD_DESIGN.md
```

Any subsequent edit to `PEAD_DESIGN.md` will change this hash and invalidate certification. The Phase 1 orchestrator (`gauntlet.run_phase1.check_phase0_certified`) re-computes this hash at runtime and refuses to execute if it doesn't match.

---

## Phase 0 Exit Checklist

| # | Criterion | Tool | Result |
|---|---|---|---|
| 1 | Extractor over PIT universe | `extractors.run_extractor` | 759 / 771 fetched (98.4%); 11 no-XBRL-coverage (incl. 4 corrupted CIKs from upstream PIT data); 1 transient error (irrecoverable; logging patched going forward) |
| 2 | Substitution-log integrity | `validation.validate_substitution_log` | **PASS** — 136,588 rows, integrity invariant (log lines == fallback rows) holds. Substitution rate **75.8%** (documented limitation; see "Known limitations" below) |
| 3 | Fiscal alignment (conflicting-vals) | `validation.validate_fiscal_alignment` | **PASS** — 4 errors / 747 shards = 0.54%, below 2% threshold |
| 4 | As-of-date discipline | `validation.validate_as_of` | **PASS** — 4 errors / 26,602 restatement chains = 0.015%, below 0.1% threshold |
| 5 | Universe intersection | `validation.universe_intersection` | **PASS** — 614 eligible firms / 26,908 firm-quarters (PIT × XBRL × OHLCV × ≥8 quarters) |
| 6 | This certification document | manual | filed 2026-05-17 |

---

## Universe Intersection Summary

| Filter | Firm count |
|---|---:|
| PIT universe (total) | 771 |
| Has XBRL coverage | 747 |
| Has OHLCV parquet | 654 |
| Has BOTH XBRL and OHLCV | 634 |
| Has ≥8 quarters of clean Diluted EPS | 723 |
| **Eligible (all four filters)** | **614** |

**Total eligible firm-quarters: 26,908** spanning the substrate window **2012-01-01 → 2026-05-17**.

Substrate windows for the Phase 1 gauntlet (per `PEAD_DESIGN.md` §5):
- IS: 2012-01-01 → 2020-12-31 (9 years)
- OOS-A: 2021-01-01 → 2023-12-31 (3 years)
- OOS-B: 2024-01-01 → 2026-05-17 (2.4 years)
- 21-day embargo at each window boundary

---

## §2.2 Addendum Resolution

The Phase 0 validation surfaced a real SEC API semantic issue: the `fp` field reflects the FILING form, not the value's period. The fix is documented in `PEAD_DESIGN.md` §2.2 as the **§2.2 ADDENDUM (2026-05-17)** — an in-place correction of an assumption that proved wrong on first contact with data, NOT a relaxation of any gate. Implementation:
- New schema columns: `period_duration_days` (int), `period_kind` (str ∈ {quarterly, annual, ytd_q2, ytd_q3, other})
- `compute_sue` now keys by `period_end` (date) with seasonal predecessor lookup via ±15-day date arithmetic
- `panel.build_panel_for_firm` filters to `period_kind == "quarterly"`
- `value_as_of` defaults to `period_kind="quarterly"` filter
- `extractors.normalize_shards` was run once to backfill the new columns on existing shards (no SEC re-fetch needed)

The Phase 1 trial set, gauntlet criteria, OOS protocol, decision matrix, and hard rules are **UNCHANGED**. Only the implementation key changed.

---

## Known Limitations (carried into the eventual `PEAD_PHASE1_VERDICT.md`)

1. **76% of EPS rows come from the fallback concept** `EarningsPerShareDiluted` (total Diluted EPS) rather than the primary `IncomeLossFromContinuingOperationsPerDilutedShare` (continuing-ops only). This reflects real S&P 500 reporting behavior — most companies don't have discontinued operations to break out separately. The two concepts are identical for companies without discontinued operations (most firms most quarters). The verdict document must report this prominently.

2. **0.54% of firms have at least one conflicting-value row** in the `(period_end, filed, concept)` group. Investigated cases:
   - CIK 93556 (Stanley Black & Decker) reports `vals=[0.83, 161781000.0]` at one filing — the 161M is net income filed under the EPS concept (SEC tagging error).
   - CIK 861878 (Stericycle?) reports `vals=[0.34, 0.87]` and `[0.7, 1.02]` at single filings — likely Class A vs Class B share reporting under the same concept tag.
   These are real SEC data quirks, not parser bugs.

3. **157 PIT firms had no XBRL coverage or no OHLCV** (771 → 614 after intersection). The XBRL-mandate phase-in (2009–2011) and yfinance gaps for delisted/restructured tickers account for most of this. 4 of the 11 "no XBRL" results were corrupted CIKs leaking from the upstream PIT event log (>10 digits; not real SEC CIKs).

4. **1 transient error during extraction** (1/771 = 0.13%). The extractor's stdout-only logging at the time meant the specific failure context is irrecoverable. Patched 2026-05-17 to also log to disk for future runs.

---

## Permission Granted

Per `PEAD_DESIGN.md` §0 and §8: Phase 1 may now execute against the extracted data. `gauntlet.run_phase1.run_phase1(..., require_certification=True)` will validate this anchor at runtime and refuse if it doesn't match.

The next step is:

```bash
python3 -m gauntlet.run_phase1 \
    --pead-root . \
    --edgar-root data/edgar_eps/ \
    --ohlcv-root ../data/quarantine/market/ \
    --out research/PHASE1_RESULTS.json
```

Phase 1 produces a deflation-aware PASS/FAIL verdict on the 10-trial gauntlet pre-committed in `PEAD_DESIGN.md` §3.1. Survivors (if any) trigger Phase 1b conditional + Phase 2 stress/capacity/regime gauntlet per `PHASE2_DESIGN.md`. Zero survivors closes substrate #5 as FAILED with the same discipline that produced the four prior verdicts.
