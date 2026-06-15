# Phase 0 Recovery — Stale-Collector Incident (2026-06-15)

**Status: Phase 0 NOT certifiable. Recollection required. The 56-trial Phase 1 contract (`PHASE1_DESIGN.md`) is intact and unchanged.**

## What happened

A readiness audit on 2026-06-15 (29 calendar days after the collector started) found the book-data feed nowhere near the Phase 0 gate:

| Phase 0 exit criterion | Threshold | Observed |
|---|---|---|
| Gap fraction (`< 0.1%`) | < 0.1% | **81.8%** |
| Per-day coverage | continuous | **0 / 29 days had ≥ 22h; ~33% of hours captured** |
| Book rows | ~2.6×10⁷ / half (design §4.4) | 4.5×10⁶ total (~18% of wall-clock) |

## Root cause (high confidence)

**The live collector process was started 2026-05-17 01:35 IST on pre-session-2-fix code and never restarted.** Of 108,002 logged gap events, **107,641 (99.7%)** are `snapshot_reconcile:buffer empty after dropping stale events` — the exact message the session-2 fix (2026-05-17) removed. That string **exists nowhere in the current source** (`collector/binance_ws.py::_reconcile_buffer_with_snapshot` now *returns `None`* on the empty-buffer case, lines 247–251), and the events span the full 29.5 days. So the running binary is stale; the code on disk is already correct.

Mechanism: the old code treated the *normal* "snapshot newer than all buffered diffs" case as a fatal resync — raise → log gap → full reconnect → re-buffer 1s → re-snapshot → (usually) raise again. The collector spent most of its life in reconnect churn instead of streaming, yielding ~33% coverage.

**No fix to `binance_ws.py` is required.** The bug is already fixed in source; the process just needs to run current code.

## What was changed this session (Phase 0 tooling only — contract untouched)

1. `collector/status.py` — no longer crashes on the live in-progress hourly parquet (no footer until roll); skips unreadable files and reports the skip count.
2. `collector/health_check.py` — added a **recent gap-event RATE** alarm (`gap_rate_per_hour`, trailing 1h). Cumulative `gap_events` could not distinguish old churn from ongoing churn; the rate signal escalates to CRITICAL at ≥ 20 events/h and would have fired in hour 1 of this incident. Covered by `tests/test_health_check.py` (6 tests).

## Recovery procedure (run on the collection host)

1. **Stop the stale collector.** Find and kill the process started 2026-05-17 (`ps aux | grep run_collector`). Confirm no `run_collector` remains.
2. **Restart on current code, supervised** so it survives crashes and host reboots:
   ```bash
   cd alphaforge-microstructure
   # tmux (minimum) — or a systemd unit with Restart=always (preferred)
   tmux new -d -s mscollector \
     'python3 -m collector.run_collector --symbol BTCUSDT --out data/'
   ```
3. **Verify the churn is gone within the first hour:**
   ```bash
   python3 -m collector.health_check --data-root data/
   # Require: Gap rate ~0.0 events/hour (NOT ~150). Status should not be
   # CRITICAL for churn reasons once a clean hour has accumulated.
   ```
4. **Confirm < 0.1% gaps on 1–2 fresh days** with `collector.status` before trusting the feed:
   ```bash
   python3 -m collector.status --data-root data/
   ```
   Optionally archive/rotate the old `data/_gaps.jsonl` (108k stale entries) so cumulative counts reflect the clean run; the rate alarm already ignores the old events by timestamp.
5. **Only then start the 30-day accumulation clock.** Earliest honest full Phase 1 ≈ **30 days after step 4 passes** (~2026-07-16 if recollection starts 2026-06-16). Keep `health_check` on a 5-minute cron (`*/5 * * * *`) for the duration so a regression is caught in minutes, not weeks.

## Note for Phase 1 (when it unblocks)

The §4.4 power claim ("~2.6×10⁷ obs/half → power is overwhelming; the risk is regime specificity, not power") assumes near-continuous 100ms sampling. Two effects make the *effective* sample far smaller than the nominal count: (a) the 100ms book stream and overlapping K-horizon returns are heavily autocorrelated; (b) any residual feed gaps fragment the series. When Phase 1 runs, report ICs with autocorrelation-robust (stationary-bootstrap) error bars — the canonical implementation now lives in `alphaforge-gauntlet/afgauntlet` — rather than relying on the raw `1/√N` intuition. This does not alter the frozen gates; it is reporting rigor, consistent with the project-wide MDE work.
