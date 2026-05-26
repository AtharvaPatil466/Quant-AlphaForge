# Substrate #9 — Phase 0 Certification

**Date:** 2026-05-26
**Status:** CERTIFIED — Phase 1 UNBLOCKED

## SHA-256 Anchor

`SUBSTRATE9_DESIGN.md` SHA-256: `2840a7750658e706a663cc38e5ff67bbd58a2b16ab47b4295279f32977f4c22a`

The Phase 1 orchestrator and Phase 3 master runner must refuse to execute if the SHA of
`research/SUBSTRATE9_DESIGN.md` does not match this anchor at runtime.

## Phase 0 Exit Criteria (per §2.4 of SUBSTRATE9_DESIGN.md)

| # | Criterion | Status | Notes |
|---|-----------|--------|-------|
| 1 | SPY OHLCV 2004-01-02 → present, 5-spike validator | PASS (inherited) | `alphaforge-vix/data/etps/SPY.parquet` certified in Substrate #7 Phase 0 |
| 2 | VIX index 2004-01-02 → present, 10-date spot-check | PASS (inherited) | `alphaforge-vix/data/vix_indices/` certified in Substrate #7 Phase 0. VIX3M ≥ VIX on 92.3% of dates confirmed. |
| 3 | FRED DGS3MO or fallback constants | PASS (inherited) | Fallback constants from `alphaforge-vix/ingest/fred.py` §14.7 in use. |
| 4 | `SUBSTRATE9_PHASE0_CERTIFIED.md` filed with SHA anchor | PASS | This document. |

## Data Sources (read-only from Substrate #7)

- `alphaforge-vix/data/etps/SPY.parquet` — SPY OHLCV 1990-01-02 → 2026-05-19
- `alphaforge-vix/data/vix_indices/` — VIX/VIX3M/VIX6M 1990-01-02 → 2026-05-19
- `alphaforge-vix/ingest/fred.py` — DGS3MO with fallback constants

No new network downloads required for Phase 0. All data already on disk from Substrate #7.

## IBKR Paper Account

IBKR paper trading account opened 2026-05-26. Options permissions enabled.
Required for Phase 4 (paper trading) only — not for Phases 1-3.

## What Phase 1 Must Do

1. Load SPY OHLCV and VIX from Substrate #7 parquet paths
2. Compute VRP_t = VIX_t − realized_vol_t(21d) across full IS window 2004-01-02 → 2014-12-31
3. Run T1 (base trial, 16Δ/5Δ, no filter) B-S reconstruction for IS monthly cycles
4. Compute correlation(VRP_t, cycle_pnl_t) across IS
5. Compute yearly sign analysis
6. Apply §9.1 Phase 1 pass criterion (correlation > 0, 7/11 years positive, 5/9 ex-2008/09 positive)
7. Write `research/PHASE1_RESULTS.json` + `research/PHASE1_VERDICT.md`
8. The Phase 3 runner is blocked until Phase 1 verdict is filed
