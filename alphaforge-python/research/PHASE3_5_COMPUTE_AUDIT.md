# Phase 3.5 — Compute Audit (pre-Phase-4)

**Phase:** Tier 1, Phase 3.5
**Date:** 2026-04-30
**Decision:** **Phase 4 green-lit. No redesign needed.**
**Budget gate (Tier 1 plan §3.5):** if projected wall-clock > 40 hours, redesign.
**Measured projection:** ~15 minutes per full Phase 4 gauntlet run.

---

## Why this audit exists

Phase 4 will run the full statistical gauntlet (Hansen SPA + White's
Reality Check + DSR + purged-embargoed CV + bootstrap CIs) on the
residualized factor panel. Without a profiling pass first, two failure
modes are possible:

1. The single-machine wall-clock is too long (>40h budget); need to
   parallelize, downsample, or rent compute.
2. Memory blows up on the 476-ticker × 2,514-day panel; need chunking.

Both are addressed below. Neither is a real concern.

---

## Measured baseline

End-to-end run of `research/factor_study.py` on the PIT universe,
non-residualized, no env-var overrides:

```
[  0.0s] Loading pit parquet panel (2016-01-04 → 2025-12-31)
          universe: 476 tickers, 2514 trading days
[ 12.0s] Building factor panels (8 factors)
[ 12.5s] Sector-neutral variant (D2)
[ 12.6s] Per-factor pipeline starts...
[ 66.9s]   raw variant: 8 factors done
[121.0s]   neutral variant: 8 factors done
[122.5s] Hansen SPA + White RC (raw + neutral)
[124.0s] White RC + Purged CV IC (h=21)
[142.7s]   CV done
[185.2s] Random long-short baseline (100 seeds)
[186.3s] Done
```

**Total: 186 seconds (~3 minutes).**

### Stage breakdown

| Stage | Time | % | Notes |
|---|---:|---:|---|
| Per-factor pipeline (16 = 8 × {raw, neutral}) | 108s | 58% | dominant; IC × 5 horizons + quintile backtest + bootstrap |
| Random LS baseline (100 seeds) | 42s | 23% | embarrassingly parallel if needed |
| Purged CV IC | 19s | 10% | acceptable; one-shot |
| Panel load | 12s | 6% | cached after first run |
| Hansen SPA / White RC | 2s | 1% | trivial |
| Misc | 3s | 2% | |

### Bootstrap reps cost (per factor, 2,514-day series)

| Reps | Time | Per-study cost (×16 panels) |
|---:|---:|---:|
| 2,000 | 1.51s | 24s |
| 1,000 | 0.74s | 12s |
| 500 | 0.37s | 6s |

**Bootstrap is cheap.** Even at 2,000 reps, the full bootstrap budget
is 24s of the 108s per-factor pipeline. The other 84s is IC-across-5-
horizons (Spearman + sector-neutral variants) and quintile backtests.
Bootstrap rep count is not a bottleneck.

---

## Residualization cost

The dominant new cost in Phase 4 is **rolling FF5+UMD residualization**
of the daily return panel. Profiled standalone:

```python
rolling_factor_residuals_panel(raw_returns, reference, window=252, min_obs=252)
# 593 seconds (~10 min) on the 476-ticker × 2,514-day panel
```

This is ~1M small OLS regressions (476 tickers × ~2,000 useful days).
Fine for the budget but the longest single stage.

**Mitigations available if it becomes annoying:**
- Cache the residual panel (compute once, reuse across factor variants
  and across iteration runs). Single biggest lever.
- Vectorize with `numpy` rolling-window matrix algebra (~5-10× faster).
- Reduce `RESIDUAL_WINDOW` from 252 → 126: roughly halves the cost
  but reduces residual quality.

None of these are needed before starting Phase 4. The 593s is the
*single most expensive operation* in the entire Phase 4 pipeline and
it still leaves ~38 hours of headroom under the 40h budget.

---

## Phase 4 full-run projection

A single end-to-end Phase 4 gauntlet run = baseline + residualization +
small additions for the 11-factor and 2-OOS-window expansions.

| Component | Estimate | Source |
|---|---:|---|
| Panel load | 12s | measured |
| Build 8 factor panels + sector-neutral variant | 0.5s | measured |
| FF5+UMD residualization (cached after first run) | 593s | measured |
| Per-factor pipeline × 16 (raw + neutral, raw returns) | 108s | measured |
| Per-factor pipeline × 16 (raw + neutral, residualized) | 108s | same cost as above |
| Adding 3 more factors to reach 11: × {raw, neutral, residualized} × 2 | ~80s | extrapolated |
| Two non-overlapping OOS windows | ~5s | slicing existing series, not full re-runs |
| Hansen SPA + White RC (raw + neutral + residualized variants) | ~10s | measured + scaled |
| Purged-embargoed CV IC (residualized) | 25s | measured + scaled |
| Random LS baseline (100 seeds, residualized) | 42s | measured |
| Misc reporting | 5s | measured |
| **Total per full run** | **~990s ≈ 16 minutes** | |

If the user iterates 5-10 times during Phase 4 calibration:
**~1.5-2.5 hours of total compute.**

**40-hour budget cleared by ~16×.** No redesign needed.

---

## Memory check

Panel dimensions:
- `close`: 476 × 2,514 = ~1.2M float64 cells = ~9.5 MB
- `volume`: same shape = 9.5 MB
- 8 factor panels: 8 × ~9.5 MB = 76 MB
- `sector_neutral` variant: another 76 MB
- Forward returns at 5 horizons: 5 × ~9.5 MB = 48 MB
- Residual panel: 9.5 MB
- Reference factors: trivial (~7 cols × 15K rows)

**Total RAM working set: ~250-300 MB.** No memory concerns. Standard
laptop configuration handles this comfortably.

---

## Identified bottlenecks (priority ordered)

1. **Residualization (593s, 60% of full run)** — single biggest lever.
   Cache the residual panel between iterations; don't recompute on
   every Phase 4 run during calibration. Implementation: pickle the
   `residual` DataFrame after Phase 3 staging completes; load from
   pickle in subsequent runs unless the panel inputs changed.

2. **Per-factor pipeline (216s across raw + residualized variants)** —
   second biggest. Each factor pass is sequential. Trivially
   parallelizable with `multiprocessing.Pool` across factors (8-core
   laptop → ~3-4× speedup). Not needed unless iteration count climbs
   high.

3. **Random LS baseline (42s)** — third. Already independent across
   seeds, just runs sequentially. Optional parallelization.

4. **Purged CV IC (~25s)** — fine; one-shot.

---

## Recommendation: cache the residual panel

Single change worth making before Phase 4 starts. Add caching to
`prepare_analysis_returns()` in `factor_study.py`:

- Cache key: hash of (close panel checksum, reference factors checksum,
  `RESIDUAL_WINDOW`, `RESIDUAL_MIN_OBS`).
- Cache path: `research/out/_residual_cache/<hash>.parquet`.
- Hit: skip the 593s residualization; load parquet (~0.5s).
- Miss: compute, save, return.

This converts the calibration loop from ~16 min/run to ~6 min/run after
the first one. ~2-3× iteration-rate boost for ~30 lines of code.

Optional. Not blocking Phase 4 entry.

---

## Decision

**Phase 4 cleared for entry.** Compute budget has ~16× headroom under
the 40-hour gate. Memory is trivial. No redesign needed. Residual-
panel caching is a recommended optimization but not a precondition.

The full Phase 4 plan from Tier 1 §4 (gauntlet on residualized
returns, 11 factors, two OOS windows, Hansen SPA + RC + DSR + purged
CV) runs in ~15 minutes per full pass on a single laptop. Calibration-
loop iteration is quick.
