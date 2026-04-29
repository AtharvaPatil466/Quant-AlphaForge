# Tier 1 Pause — Live Execution Loop

**Date engaged:** 2026-04-25
**Mechanism:** `.halt` file at the root of `alphaforge-execution/`
**Effect:** `run_daily.sh` exits immediately on next cron fire with a `HALTED` alert; no new orders are submitted to Alpaca.

## Why

The live loop was running a momentum strategy on a 6-ticker mega-cap
tech universe (`AAPL, MSFT, NVDA, GOOGL, META, AVGO`) against an Alpaca
paper-trading account. Survivorship bias on this universe is extreme —
not just the 50-name CLAUDE.md universe, but a hand-picked subset of
post-hoc winners.

Tier 1 of the AlphaForge roadmap is methodology validation: point-in-time
universe reconstruction, FF5 + momentum risk-model residualization, and
deflation-aware single-factor + combination evaluation against a
pre-committed gate (DSR > 0.95 OOS net of costs, replicated across two
non-overlapping OOS windows).

It is incoherent to simultaneously:

- declare in research artifacts (PDF, RESEARCH_WRITEUP.md, factor study)
  that none of the implemented signals clears the deflation bar, AND
- continue accumulating a "live track record" on one of those exact
  signals against a deliberately-biased universe.

The live loop is paused for the duration of Tier 1 to remove that
incoherence and to keep the Tier 1 evaluation honest.

## Snapshot at pause time

- **NAV (last snapshot 2026-04-21):** $102,502.01
- **Cash:** $75,892.30
- **Open positions (5, ~$26k notional):** AAPL, AVGO, META, MSFT, NVDA
- **Total filled orders (loop lifetime):** 7
- **Total rejected orders:** 4
- **First snapshot:** 2026-03-23 (loop is ~1 month old)

The slippage dataset accumulated over this period (7 fills) is too small
to be load-bearing in any reconciliation analysis, so nothing is lost by
pausing. The original Phase 0 plan called for refactoring the loop into
a tiny-notional random long-short "Slippage Calibration" mode to keep
generating execution data during Tier 1; this is deferred (see Phase 0.4
in the task list / TIER1 plan) because the marginal value of more
slippage data on the current 6-name universe is approximately zero — any
real calibration mode should run on the eventual Tier 1 surviving
universe, not on this one.

## What stays running

- The execution loop **code** (no changes — only `.halt` was added)
- The cron entries (they will fire and exit cleanly via the halt path)
- The SQLite databases (`live_trading.db`, `live_marl.db`) — preserved
  as historical record
- The kill switch and slippage-reconciliation script — unchanged, still
  importable for analysis

## Alpaca paper positions — closed 2026-04-25

Both paper accounts (momentum + MARL) were flattened at Tier 1 start
via `scripts/tier1_close_positions.py`. Ten market sell orders were
submitted and ACCEPTED outside market hours; they will fill at the
next session open. Order IDs are persisted in the respective `orders`
tables (`live_trading.db`, `live_marl.db`) and in the audit log
`tier1_close_<timestamp>.json` at the repo root.

State at pause time (pre-close):

| Account     | Account ID                              | Equity     | Positions                              |
|-------------|------------------------------------------|------------|----------------------------------------|
| momentum    | 444f0015-7293-44ae-8ebf-2dd0cc8b0745    | $103,081.90 | AAPL, AVGO, META, MSFT, NVDA (5)       |
| marl        | 8d21b131-8fce-485d-aa6a-f9984b0dafe7    | $100,609.06 | AAPL, AVGO, GOOGL, MSFT, NVDA (5)      |

Both accounts will sit fully cash-equivalent for the duration of Tier 1.
Re-launching live trading requires removing `.halt` and satisfying the
four conditions below — at which point the survivor signal opens a
clean book.

## Re-launch conditions

Removal of the `.halt` file (and resumption of live trading) requires
**all four** of the following to be true:

1. **Tier 1 gate passed.** ≥1 signal with DSR > 0.95 OOS net of costs
   on point-in-time S&P 500, replicated across two non-overlapping OOS
   windows (per Tier 1 plan §0).
2. **The signal that re-launches the loop is the Tier 1 survivor.** Not
   the legacy momentum composite, not a MARL checkpoint, not a
   hand-picked alternative.
3. **Universe expanded** from the current 6-name list to (at minimum)
   the surviving names from Tier 1's PIT-S&P-500 substrate.
4. **6-month paper-trading minimum** before any external claim of "live
   track record." The point of paper trading is to measure live-vs-
   backtest tracking error; that measurement requires a sample size.

If Tier 1 fails (no signal clears the gate), the loop stays paused
indefinitely and the Tier 2 decision matrix in the main plan governs
what happens next.

## To resume

```bash
rm "/Users/atharva/Quant Projects/Quant Alpha/alphaforge-execution/.halt"
```

Do not run this command unless all four re-launch conditions above are
demonstrably satisfied. If you are reading this and tempted to remove
the halt without satisfying them, the answer is no.
