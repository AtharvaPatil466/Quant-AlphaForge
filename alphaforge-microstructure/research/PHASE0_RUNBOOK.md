# Phase 0 Runbook

Operational doc for running the live collector 24/7 and certifying Phase 0 complete. Pairs with `research/MICROSTRUCTURE_DESIGN.md` (the design contract) and the sub-project `CLAUDE.md` (architecture + exit criteria).

---

## 0. One-time setup

```bash
cd alphaforge-microstructure
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 -m pytest tests/ -v      # 43 tests, all should pass
```

## 1. Pulling historical aggTrades (one-shot, ~10–20 min wall-clock)

This unblocks TFI research without waiting on live data. Trade tape only; book data still requires the live collector.

```bash
# 90 days of BTCUSDT — adjust dates to your "last 90 days"
python3 -m historical.binance_vision \
    --symbol BTCUSDT \
    --start 2026-02-17 --end 2026-05-17 \
    --out data/ \
    --concurrency 4
```

The loader is idempotent — re-running skips days already on disk. Add `--force` to re-download.

Sanity-check:

```bash
python3 -m collector.status --data-root data/
```

Look at the `Trades` line — days, rows, date range. ~1.5–2M rows/day for BTCUSDT is normal.

## 2. Starting the live collector

The collector must run 24/7 to accumulate L2 book data. Choose ONE supervision method:

### Option A — tmux (simplest)

```bash
tmux new -s collector
source .venv/bin/activate
python3 -m collector.run_collector --symbol BTCUSDT --out data/
# Ctrl-B then D to detach. Reattach with `tmux attach -t collector`.
```

### Option B — systemd user unit (recommended for long-running)

Create `~/.config/systemd/user/alphaforge-collector.service`:

```ini
[Unit]
Description=AlphaForge microstructure collector (BTCUSDT)
After=network-online.target

[Service]
Type=simple
WorkingDirectory=%h/Quant Projects/Quant Alpha/alphaforge-microstructure
ExecStart=%h/Quant Projects/Quant Alpha/alphaforge-microstructure/.venv/bin/python -m collector.run_collector --symbol BTCUSDT --out data/
Restart=always
RestartSec=5
StandardOutput=append:%h/Quant Projects/Quant Alpha/alphaforge-microstructure/logs/systemd.log
StandardError=append:%h/Quant Projects/Quant Alpha/alphaforge-microstructure/logs/systemd.log

[Install]
WantedBy=default.target
```

Enable:

```bash
systemctl --user daemon-reload
systemctl --user enable --now alphaforge-collector
systemctl --user status alphaforge-collector
```

Tail logs:

```bash
journalctl --user -u alphaforge-collector -f
```

On macOS without `systemctl --user`, use `launchd` or fall back to tmux.

## 3. Daily check (≤30 seconds)

```bash
python3 -m collector.status --data-root data/
```

What to look for:

- **Book snapshots `days`** growing by ~1 per calendar day.
- **Gaps `gap_fraction`** stays well under 0.1% (the threshold).
- **`explicit_gap_events`** is small and stable. If it grows fast (>10/hour), the collector is fighting the resync protocol — investigate.

If `days` stops growing for >1 hour: collector is down or wedged. Check the supervisor and the latest log line.

## 4. Recovery from a crash

The collector exits non-zero on unrecoverable errors so the supervisor restarts it. Each restart costs ~1–2 seconds of book data while it re-buffers + re-fetches the REST snapshot. That gap is logged to `data/_gaps.jsonl` automatically.

If crashes are *frequent* (>~5/hour), look at `logs/collector_*.log` for the exception type. Common causes:

- **`sequence gap`** — Binance dropped a depth event. Normal, infrequent. Reconnect is correct.
- **`first diff does not bracket lastUpdateId+1`** — buffer/snapshot mismatch. After the 2026-05-17 fix this should be rare; if it spikes, file an issue.
- **`aiohttp.ClientError`** — network blip. Auto-handled.
- **`ConnectionResetError` / `WSMessageTypeError`** — exchange-side disconnect. Auto-handled.

## 5. Mid-run validators (after ≥1 day of data)

Three validators correspond to three of the four Phase 0 exit criteria:

```bash
# Criterion 2 — reconstructed book matches Binance REST (live HTTP call)
python3 -m validation.book_snapshot_check --data-root data/ --samples 24

# Criterion 3 — every trade timestamp lies between its bracketing book snapshots
python3 -m validation.temporal_alignment --data-root data/ --date $(date -u +%F)

# Criterion 4 — feed gaps < 0.1% of collection window
python3 -m validation.gap_detector \
    --data-root data/ \
    --start 2026-05-17 --end $(date -u +%F)
```

Each emits a JSON report and exits non-zero on failure. Run all three weekly.

## 6. Phase 0 exit (the gate)

Phase 0 is CLOSED when:

| # | Criterion | Tool |
|---|---|---|
| 1 | ≥30 days of book data on disk (90 preferred) | `collector.status` |
| 2 | Reconstructed book = REST snapshot, 0 diffs over 24 samples | `validation.book_snapshot_check` |
| 3 | <0.01% trades violate temporal ordering vs book | `validation.temporal_alignment` |
| 4 | <0.1% gap fraction in book coverage | `validation.gap_detector` |

When all four are green, file a `PHASE0_CERTIFIED.md` in `research/` with the date and the four validator JSON outputs pasted in. That document unblocks Phase 1.

**Do not loosen any criterion to make Phase 0 close earlier.** This is the same pre-commitment discipline that produced the three honest negative verdicts in the rest of the project. The gate is the gate.

## 7. What NOT to do during Phase 0

- Don't touch `collector/`, `historical/`, or `validation/` code unless you're fixing a documented bug. Pre-commitment means the data-collection protocol doesn't shift while data is accumulating.
- Don't add new instruments. The plan is BTC-USDT only until Phase 1 closes.
- Don't write signal code (`signals/`, `strategy/`, `backtest/` — these directories don't exist and must not be created here yet).
- Don't run ad-hoc exploratory analysis on partial data. The gauntlet is one-shot at Phase 1; peeking now creates a multiple-testing problem that DSR can't deflate against because the trial set hasn't been written down.

## 8. While you wait

The 30 days is wall-clock, not your time. ~2–4 hours of active involvement total: daily 30-second check + occasional restart. Spend the rest of the time on:

- Reading microstructure literature (Cont, Kukanov, Stoikov for OBI; Easley/López de Prado for adverse-selection metrics; Almgren/Chriss for the inventory side).
- Pre-writing the Phase 1 trial set — every signal, every parameter, every horizon — in a `PHASE1_DESIGN.md` that must be checked in BEFORE any IC numbers are computed. Same pre-commitment discipline as Tier 1 / Tier 2.
- Skill-track work (math foundations, paper reading, public artifacts).
