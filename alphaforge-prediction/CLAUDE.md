# alphaforge-prediction — Sub-Project Context

**Substrate #10 — Kalshi favorite-longshot bias (FLB).** Status as of 2026-06-16:
**Phase 0 ingest layer BUILT.** The pre-committed contract is
`research/PREDICTION_MARKETS_DESIGN.md` (the frozen design). **Read it first.** No code may
execute against the substantive Phase 1 calibration until the design is SHA-256 anchored and
Phase 0 is certified (`research/PREDICTION_PHASE0_CERTIFIED.md`).

This is the first substrate where **being small is the edge**: a $40k Kalshi market is too
small for an institution and right-sized for a solo retail trader. The goal is a credible
live track record (positive realized edge + calibration beating the market's), not fund-scale
alpha. See `research/PREDICTION_MARKETS_DESIGN.md` §0.

---

## Strategy Class

**Calibration / structural-bias harvest on binary event contracts** — not cross-sectional
rank (substrates 1-6) nor a continuous predictive signal. The hypothesis (§1): across
resolved Kalshi binaries, market-implied probability (price 0-1) is a biased estimator of
realized resolution frequency — longshots overpriced, favorites underpriced. The test is
per-(price-bucket × category) calibration, net of the honest Kalshi fee + spread model.
**G4 (net-of-fee survival) is make-or-break** — the gross FLB edge is small and price-
dependent fees can exceed it.

---

## Phase 0 Architecture

```
data/                                  ← raw + processed (gitignored bulk)
  processed/
    resolved/part-NNNNN.parquet        ← one row per resolved contract (schema.py)
    _ingest_checkpoint.jsonl           ← per-ticker resume checkpoint (append-only)

ingest/
  __init__.py
  schema.py            ← BUILT — parquet schema, ONE ROW PER RESOLVED CONTRACT;
                         defensive coercers (to_float / iso_to_ns) for Kalshi's
                         string-typed numerics + ISO timestamps → ns ints.
  kalshi_client.py     ← BUILT — read-only REST client; the ONLY network module.
                         Paginated settled markets (cursor), events (category/series),
                         candlesticks. Rate-limited; retry/backoff; 429 → RateLimitedError.
  downloader.py        ← BUILT — paginate settled → filter volume_fp>0 → resolve event →
                         reconstruct §4 entry price from candlesticks → write parquet.
                         Checkpointed/resumable. CLI.

validation/
  __init__.py
  validator.py         ← BUILT — Phase 0 exit gates: coverage (+ per-category),
                         resolution integrity ≥99.9%, no-look-ahead 100%. MD + JSON.

research/
  PREDICTION_MARKETS_DESIGN.md         ← THE CONTRACT (locked; SHA-256 anchored at cert)
  SPIKE_NOTES.md                       ← BUILT — endpoint shapes + fee schedule (spike)
  phase0_certify.py                    ← BUILT — runs validators + recomputes design SHA →
                                         writes PREDICTION_PHASE0_CERTIFIED.md
  PHASE0_VALIDATION.md / .json         ← validator output (data-dependent)
  PREDICTION_PHASE0_CERTIFIED.md       ← cert output (filed at Phase 0 close)

tests/
  conftest.py          ← FakeSession + real-shape market/event/candle fixtures
  test_kalshi_client.py / test_schema.py / test_downloader.py
  test_validator.py / test_phase0_certify.py    ← 59 tests, zero live-network calls
```

### Frozen engineering pre-commits from the Phase 0 spike (see SPIKE_NOTES.md)

1. **Base** `https://api.elections.kalshi.com/trade-api/v2`, read-only, no auth. System
   `urllib` fails TLS here; use `requests` (ships certifi).
2. **String-typed numerics.** Every `*_dollars` / `*_fp` field is a JSON string;
   `schema.to_float` coerces defensively.
3. **Category + series live on the EVENT, not the market.** `GET /events/{event_ticker}`
   returns `series_ticker` (needed for the candlesticks path) and `category` (§4 grouping).
   The downloader caches `event_ticker → (series, category)`.
4. **Candlesticks** `GET /series/{s}/markets/{ticker}/candlesticks?start_ts=&end_ts=&period_interval=`.
   `period_interval ∈ {1,60,1440}` minutes; `start_ts`/`end_ts` required (epoch seconds);
   **max 5000 candles/request**. `price.close_dollars` present iff a trade occurred in the
   bucket; else `price.previous_dollars` carries the prior trade.
5. **§4 entry price (frozen):** last *trade* at/before `close_time − 1h` (fallback: last
   pre-close trade). Look-ahead guaranteed: `entry_snapshot_ts < close_time` on 100% of rows.
6. **Volume filter** `volume_fp > 0` (§7) drops ~75-79% of settled markets (untraded MVE legs).

### Fee schedule (frozen for §6, confirmed in the spike — see SPIKE_NOTES.md (b))

- **General taker fee:** `fees = roundup(0.07 × C × P × (1−P))` dollars, whole-trade ceiling
  to the cent. P = price (dollars 0-1), C = contracts.
- **S&P 500 / Nasdaq-100 series:** half rate, `roundup(0.035 × C × P × (1−P))`.
- **Maker:** 25% of taker where charged. §4 entry is a taker order → §6 models taker.
- **G4 stress:** double the schedule; net edge must stay positive (§14 rule 5: no post-hoc
  fee reductions).
- Source: official *Kalshi Fee Schedule for Feb 2026* (`kalshi.com/docs/kalshi-fee-schedule.pdf`,
  rate-limited at spike time) + 3 corroborating secondary sources.

---

## What Touches What

- **Network access is confined to `ingest/kalshi_client.py`** (+ the optional small live pull
  from the downloader). Everything else reads parquet. Tests mock the network entirely.
- **This sub-project has an INDEPENDENT data flow.** It does NOT read from
  `data/quarantine/market/`, does NOT unfreeze any equity/MARL/execution module, and does NOT
  touch `.halt`. Statistics will use the shared `afgauntlet` package at Phase 1 (per the
  design's `afgauntlet/binary.py`), read-only.

---

## Commands

```bash
cd alphaforge-prediction

# Tests (59 as of 2026-06-16). Use python3.13 (Homebrew 3.14 has broken pyexpat).
python3.13 -m pytest tests/ -q

# Small live pull (a few hundred settled markets) — proves end-to-end
python3.13 -m ingest.downloader --output-root data --max-pages 4 -v

# Full pull (exhaust settled markets) — checkpointed/resumable; just re-run to resume
python3.13 -m ingest.downloader --output-root data

# Phase 0 validator — markdown + JSON; exits nonzero on any blocking FAIL
python3.13 -m validation.validator --data-root data \
    --report-md research/PHASE0_VALIDATION.md \
    --report-json research/phase0_validation.json

# Phase 0 certification — runs validators + recomputes design SHA-256
python3.13 -m research.phase0_certify
```

Operational notes:
- Ingest checkpoint: `data/processed/_ingest_checkpoint.jsonl` (append-only; resume-safe;
  FAILED rows are retried on resume, all other outcomes are terminal).
- Parquet is sharded `part-NNNNN.parquet`, flushed every `--flush-every` rows, atomic replace.
- Certification is CERTIFIED only when all three §2 gates PASS; an empty store → INCOMPLETE.

## Reading order for new sessions

1. `research/PREDICTION_MARKETS_DESIGN.md` — the contract.
2. `research/SPIKE_NOTES.md` — confirmed endpoints + fee schedule.
3. This `CLAUDE.md`.
4. Top-level `/CLAUDE.md` for the broader substrate landscape (nine prior substrates).
