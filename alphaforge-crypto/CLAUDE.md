# alphaforge-crypto — CLAUDE.md

Sub-project for the crypto-substrate research stack. Spun up 2026-05-15 after the equity-substrate gauntlet (Tier 1 + Tier 2) closed FAILED on 2026-05-02. See `~/.claude/projects/-Users-atharva-Quant-Projects-Quant-Alpha/memory/substrate_pivot_crypto.md` for the decision context.

## Scope

- **In:** data layer (Binance public REST → local parquet store), minimal factor study targeting **funding-rate carry** and **spot-perp basis** as the crypto-native alpha class.
- **Out (for v0):** market-making (needs L2 depth + queue simulation), MARL, execution. These are deferred to a Phase 2 pivot decision.
- **Explicitly not:** porting the equity cross-sectional factor zoo to crypto. That's the substrate class Tier 1/2 just failed on; doing it again on crypto OHLCV would learn nothing.

## Architecture

```
alphaforge-crypto/
├── data/
│   ├── paths.py             store layout
│   ├── binance_client.py    public REST client, weight-aware rate limiter
│   ├── universe.py          top-N USDT-M perpetuals by 24h quote volume
│   ├── downloader.py        paginated klines + funding + OI downloader
│   ├── validator.py         parquet integrity checks
│   └── loader.py            aligned panel reader
├── research/
│   ├── carry_study.py       (stub) cross-sectional funding-rate carry
│   └── basis_study.py       (stub) spot-perp basis as predictor
├── sync_binance_data.py     orchestrator CLI — the ONLY module that touches the network
└── tests/
```

Parquet store layout (under `<repo>/data/binance/`):
```
data/binance/
├── _manifest.json                       universe + per-symbol last_synced_at
├── klines_1h_spot/<SYMBOL>/<YEAR>.parquet
├── klines_1h_perp/<SYMBOL>/<YEAR>.parquet
├── funding/<SYMBOL>.parquet             whole-history single file (8h cadence is low-cardinality)
├── open_interest/<SYMBOL>/<YEAR>.parquet
└── _quarantine/                         validator-failed shards
```

## Network discipline

- `sync_binance_data.py` is the ONLY module that touches the network. Everything else reads parquet. This mirrors the equity stack's `sync_market_data.py` discipline.
- Binance public endpoints used: `/api/v3/klines`, `/api/v3/exchangeInfo`, `/api/v3/ticker/24hr`, `/fapi/v1/klines`, `/fapi/v1/exchangeInfo`, `/fapi/v1/ticker/24hr`, `/fapi/v1/fundingRate`, `/futures/data/openInterestHist`.
- **No API key required for v0.** Auth is needed only for trading endpoints, which we are not building yet.
- Tests use mocked HTTP exclusively. No tests hit the live API.

## Honest known limitations (v0)

- **Survivorship bias.** The universe is "top 30 USDT-M perpetuals by current 24h volume." Symbols Binance has delisted are not in the panel. A PIT crypto universe is a future project, not a v0 deliverable.
- **No L2 book.** Klines + funding only. Market-making research is blocked on this.
- **Liquidation buffer / maintenance margin not modeled.** Funding-rate carry research treats funding as a clean cash flow; in practice liquidations during extreme funding regimes can destroy a paper-perfect carry strategy.
- **Funding-rate carry crowding.** Long spot / short perp funding harvest is a well-known retail trade. Expect costs to eat most of the headline edge at small-mid AUM — this must be modeled honestly, not ignored.

## Methodology carries over from equity stack

The equity-stack hygiene rules apply unchanged:

- Pre-commit gates BEFORE looking at out-of-sample performance.
- Deflated Sharpe across the full trial set (not naive Sharpe).
- Stationary-bootstrap confidence intervals.
- Honest transaction costs from the first backtest (taker fee, maker rebate, funding cash flow, slippage).
- Purged + embargoed CV.
- No look-ahead. Funding paid at time t is conditioned only on information available before t.

Tier 1 / Tier 2 failed because the cross-sectional equity factor class doesn't survive deflation + realistic costs. The pivot is to a different alpha class, not to weaker methodology.

## Commands

```bash
cd alphaforge-crypto

# install deps
pip install -r requirements.txt

# tests (mocked HTTP, fast)
python3 -m pytest tests/ -v

# sync — small smoke test
python3 sync_binance_data.py --top-n 3 --start-date 2025-01-01 --end-date 2025-01-07

# sync — full v0 universe
python3 sync_binance_data.py --top-n 30 --start-date 2020-01-01
```

## What's not built yet (next sessions)

- Research scripts: `carry_study.py` and `basis_study.py` are stubs. Actual design comes after we look at the funding-rate distribution in the downloaded data — committing to a study shape blind is the same mistake the equity gauntlet made early.
- PIT universe for crypto (handles delistings + listings honestly).
- A `cost_model.py` analog with realistic Binance fee tiers, funding cash flow accounting, and slippage estimation.
