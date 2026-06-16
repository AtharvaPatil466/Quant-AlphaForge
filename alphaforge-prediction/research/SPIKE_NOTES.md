# Phase 0 Spike Notes — Kalshi Prediction Markets (Substrate #10)

**Run date:** 2026-06-16. Live calls executed from the build host (`python3.13`,
`requests` + `certifi`). These notes feed `PREDICTION_MARKETS_DESIGN.md` §2 (Phase 0),
§4 (entry-price), and §6 (cost model). They are an engineering ADDENDUM and do not change
the substantive contract.

---

## (a) Endpoints — confirmed live

### Base
`https://api.elections.kalshi.com/trade-api/v2` — read-only market data, **no auth**.
Responds 200 to a plain `GET` with `Accept: application/json`. (Note: macOS system Python
`urllib` fails TLS verification against this host; use `requests`, which ships `certifi`.)

### Settled markets — `GET /markets`
```
GET /markets?status=settled&limit=100&cursor=<C>
-> 200 {"markets": [ {...}, ... ], "cursor": "<next>"}
```
- `cursor` is the empty string / absent on the last page; otherwise a token to pass as
  `&cursor=`. `limit` accepted up to 1000 (default used: 100–200).
- `status=settled` returns markets with `status` field value `"finalized"` (and
  occasionally `"settled"`). Both are terminal/resolved states; treat either as resolved.
- **~25% of settled markets carry volume** (`volume_fp > 0`): of 100 settled markets in a
  fresh page, 25 had volume. The bulk are zero-volume MVE legs that never traded.
- **Numeric fields are JSON strings, not numbers** (e.g. `volume_fp: "1.14"`,
  `last_price_dollars: "0.8670"`). All `*_dollars` and `*_fp` fields must be coerced
  defensively (`float(x)` with a NaN/0 fallback). `volume` (the legacy int field) was
  `null` on every sampled market; `volume_fp` is the live one.
- **Prices** are dollars in [0,1] as strings (`*_dollars`). `*_cent` variants were not
  present on this API version; only `_dollars`.

**Market object keys (45 total), sampled live:**
```
can_close_early, close_time, created_time, custom_strike, event_ticker,
expected_expiration_time, expiration_time, expiration_value,
fractional_trading_enabled, last_price_dollars, latest_expiration_time,
liquidity_dollars, market_type, mve_collection_ticker, mve_selected_legs,
no_ask_dollars, no_bid_dollars, no_sub_title, notional_value_dollars,
open_interest_fp, open_time, previous_price_dollars, previous_yes_ask_dollars,
previous_yes_bid_dollars, price_level_structure, price_ranges,
response_price_units, result, rules_primary, rules_secondary,
settlement_timer_seconds, settlement_ts, settlement_value_dollars, status,
strike_type, ticker, title, updated_time, volume_24h_fp, volume_fp,
yes_ask_dollars, yes_ask_size_fp, yes_bid_dollars, yes_bid_size_fp, yes_sub_title
```
Sample resolved market (abridged):
```
ticker                    = 'KXMVESPORTSMULTIGAMEEXTENDED-S2026...-8C9880C806E'
event_ticker              = 'KXMVESPORTSMULTIGAMEEXTENDED-S2026...'
status                    = 'finalized'
result                    = 'yes'        # in {'yes','no'} for resolved binaries
settlement_value_dollars  = '1.0000'     # 1.0 if YES resolved, 0.0 if NO
last_price_dollars        = '0.8670'
yes_bid_dollars / yes_ask_dollars = '0.0000' / '1.0000'
volume_fp                 = '1.14'
open_time / close_time    = '2026-06-16T07:13:03Z' / '2026-06-16T07:15:00Z'
expiration_time           = '2026-06-16T07:15:00Z'
settlement_ts             = '2026-06-16T07:19:13.379965Z'
market_type               = 'binary'
strike_type               = 'custom'
category                  = None         # <-- NOT on the market; on the event
```

### Category / series — on the EVENT, not the market — `GET /events/{event_ticker}`
The market object's `category` is `None` and it has no `series_ticker`. Both live on the
parent event:
```
GET /events/KXMVESPORTSMULTIGAMEEXTENDED-S2026...
-> 200 {"event": {
     event_ticker, series_ticker, category, title, sub_title,
     mutually_exclusive, strike_period, collateral_return_type,
     available_on_brokers, last_updated_ts
}}
```
Sampled values: `series_ticker = 'KXMVESPORTSMULTIGAMEEXTENDED'`,
`category = 'Exotics'`, `sub_title = 'MVE'`.
**Implication for ingest:** the `series_ticker` returned here is the path segment required
by the candlesticks endpoint, and `category` is the §4 grouping key. The downloader caches
`event_ticker -> (series_ticker, category)` to avoid one events call per market.
(`GET /series/{series_ticker}` also exists for richer series metadata; the event lookup is
sufficient for Phase 0 and one call cheaper.)

### Candlesticks (entry-price reconstruction) — confirmed live
```
GET /series/{series_ticker}/markets/{ticker}/candlesticks
      ?start_ts=<unix_s>&end_ts=<unix_s>&period_interval=<minutes>
-> 200 {"ticker": "...", "candlesticks": [ {...}, ... ]}
```
Confirmed constraints (tested live):
- `start_ts` and `end_ts` are **required** Unix epoch **seconds** (UTC). Omitting either
  returns `400 "Query argument start_ts is required"`.
- `period_interval` is the candle width in **minutes** and is restricted to the enum
  **{1, 60, 1440}** (1-minute, 1-hour, 1-day). Any other value (5, 15, 30, 240, ...)
  returns `400 Parameter validation failed ... PeriodInterval`.
- **Hard cap of 5000 candlesticks per request**: a window/interval combination implying
  more returns `400 ... "max candlesticks: 5000"`. At 1-minute granularity that is ~3.47
  days per call; the client must window long-lived markets. For entry-price reconstruction
  we only need the ~2h window straddling `close_time − 1h`, so this never binds in practice.

**Candle object shape** (keys: `end_period_ts`, `price`, `yes_bid`, `yes_ask`,
`volume_fp`, `open_interest_fp`):
```json
{
  "end_period_ts": 1781591760,
  "price":   {"open_dollars":"0.0030","high_dollars":"0.0030","low_dollars":"0.0020",
              "close_dollars":"0.0020","mean_dollars":"0.0025"},
  "yes_bid": {"open_dollars":"0.0000","high_dollars":"0.0000",
              "low_dollars":"0.0000","close_dollars":"0.0000"},
  "yes_ask": {"open_dollars":"0.0000","high_dollars":"1.0000",
              "low_dollars":"0.0030","close_dollars":"1.0000"},
  "volume_fp": "11886.35",
  "open_interest_fp": "303.03"
}
```
- `end_period_ts` is the **closing** Unix-second timestamp of the candle bucket.
- `price.close_dollars` is the **last trade price within the bucket** when a trade
  occurred. When **no trade** occurred in a bucket, `price` drops `*_dollars` OHLC and
  instead carries `price.previous_dollars` (the carried-forward last trade). This is the
  hook for §4's entry-price definition.
- `yes_bid` / `yes_ask` sub-objects always present (quotes update without trades); used for
  the §6 spread cost.

**§4 entry-price reconstruction logic (frozen):** target ts = `close_time − 3600s`.
Pull 1-minute candles over `[open_time, close_time]` (windowed to ≤5000), keep candles with
`end_period_ts <= target_ts`, take the **last** one whose `price.close_dollars` is non-null
→ that is `entry_price`. Fallback if none traded before the target: the last candle with a
non-null `price.close_dollars` anywhere strictly before `close_time` (the "last available
pre-close trade" fallback the contract permits). `yes_bid`/`yes_ask` recorded from that same
candle (or its bracketing quote candle). Look-ahead is structurally guaranteed: the chosen
candle's `end_period_ts < close_time` on 100% of rows (validator asserts this).

---

## (b) Kalshi fee schedule — CONFIRMED (secondary sources; official PDF cited)

**Primary source:** Kalshi official *Fee Schedule for Feb 2026*,
`https://kalshi.com/docs/kalshi-fee-schedule.pdf`. The PDF host returned **HTTP 429 Too
Many Requests** on every fetch attempt during this spike (rate-limited), so the verbatim
text below is reconstructed from a search index quoting that exact PDF plus three
independent secondary sources that agree. Treat the formula as **CONFIRMED** (4-source
agreement on the general formula); the only point of minor divergence across secondary
sources is the per-series multiplier list, noted below.

### General trading fee (frozen for §6)
> **`fees = roundup( 0.07 × C × P × (1 − P) )`**  dollars,
> where **P** = contract price in dollars (0–1) and **C** = number of contracts traded.

- **Rounding:** round **up to the next whole cent for the entire order/trade** (not per
  contract). i.e. `fee_dollars = ceil(0.07 * C * P * (1-P) * 100) / 100`. This makes
  small-C trades disproportionately expensive (a 1-contract trade always pays ≥ $0.01 even
  where the raw fee is sub-cent) — load-bearing for the §5 G4 gate on a small-edge,
  small-size strategy.
- **Parabolic in P:** peaks at P=0.50 (max ≈ 1.75¢/contract) and → 0 at the price extremes.
  **This cuts directly against the FLB thesis:** the longshot (≤15c) and favorite (≥85c)
  buckets the strategy targets sit in the *low-fee* tails, which helps G4; but the per-trade
  cent-ceiling on small size pushes the other way. Net effect is exactly what G4 measures.

### Per-series rate (S&P 500 / Nasdaq-100)
> **`fees = roundup( 0.035 × C × P × (1 − P) )`** — **half** the general rate, for the
> S&P 500 and Nasdaq-100 index series.

Most categories use the 0.07 general rate. One secondary source (predictionhunt) claims
finer per-category multipliers (sports/econ ≈ 0.06, politics/weather ≈ 0.056, crypto = 0.07);
this is **not corroborated** by the other three sources or by the quoted official PDF text,
which describe a single 0.07 general rate plus the 0.035 S&P/Nasdaq exception. **Frozen
decision:** §6 uses **0.07 general / 0.035 for S&P 500 + Nasdaq-100 series**, taker side.
Any finer per-category multiplier is treated as UNCONFIRMED and not used.

### Maker fee
> Maker fees, where a series charges them, are **25% of the taker fee**
> (≈ `roundup(0.0175 × C × P × (1 − P))`), max ≈ 0.44¢/contract at P=0.50.

The §4 entry definition is a marketable (taker) order crossing the spread, so §6 models the
**taker** rate. Maker treatment is recorded for completeness only.

### G4 stress (per §6 + §5)
Double the schedule (0.07 → 0.14 general; 0.035 → 0.07 S&P/Nasdaq); the net edge must remain
positive in the FLB direction. No post-hoc fee reductions are permitted (§14 rule 5).

**Source URLs:**
- Official (429 at spike time): https://kalshi.com/docs/kalshi-fee-schedule.pdf  — "Fee Schedule for Feb 2026"
- https://marketmath.io/platforms/kalshi
- https://pm.wiki/learn/kalshi-fees-explained
- https://www.predictionhunt.com/blog/kalshi-fees-complete-guide-2026
- https://whirligigbear.substack.com/p/makertaker-math-on-kalshi

---

## Engineering pre-commits baked into Phase 0 from this spike

1. **String-typed numerics.** Every `*_dollars` / `*_fp` field is a JSON string; the schema
   layer coerces with a defensive `_to_float` (NaN/None → fallback) at parse time.
2. **Category/series come from the event, not the market.** The downloader caches
   `event_ticker → (series_ticker, category)` and reuses it across that event's markets.
3. **Candlesticks need the series_ticker** (from the event) and are capped at 5000 candles /
   `period_interval ∈ {1,60,1440}`; entry reconstruction uses 1-minute candles over a short
   window around `close_time − 1h`.
4. **Resolved = `status ∈ {finalized, settled}`** with `result ∈ {yes, no}` and
   `settlement_value_dollars ∈ {1.0, 0.0}`; the validator cross-checks result vs settlement.
5. **Volume filter `volume_fp > 0`** drops ~75% of settled markets (untraded MVE legs) per
   §7; the threshold is pre-committed here.

---

## (c) Data-availability findings — IMPORTANT for §3 (substrate window)

Discovered while proving the downloader end-to-end (live, 2026-06-16). These bear directly
on the §3 assumption of "Kalshi meaningful-volume history ≈ 2022 → present".

1. **The `/markets?status=settled` feed is most-recent-first and MVE-dominated.** A 30,000-
   market cursor walk only receded ~4.5 hours (all 2026-06-16): the settled feed is
   saturated by sub-minute crypto/sports "MVE" markets that close every 1-2 minutes. **Pure
   cursor pagination cannot practically reach 2022** — it would take an astronomical number
   of pages. The downloader therefore supports **date-window paging** via
   `min_close_ts`/`max_close_ts` (`--min-close` / `--max-close`).
2. **Historical date-windows ARE reachable, but ONLY without the `status` filter.**
   `status=settled` + a 2025 window returns **empty**; the same window with the `status`
   param omitted returns markets. So the historical pull mode drops `status` and filters
   resolved (`status ∈ {finalized,settled}`) rows client-side. (`status=finalized` as a
   *query value* is rejected 400, even though it's a valid market *state*.)
3. **Pre-≈2025 markets on this host carry zero recorded volume.** Probing the elections host:
   2021/2022 windows are **empty**; the earliest exposed close is **2023-06-22**, but those
   old rows have status `"closed"` (not resolved) and `volume_fp == 0`. A 2025-03 window
   returns 400 markets — **all with `volume_fp == 0`**. The recent (2025-2026) feed is where
   resolved + volume-bearing contracts actually live, and it is dominated by Exotics/MVE.
   **Implication for §3:** on this free read-only `api.elections.kalshi.com` host, the usable
   (resolved + volume-bearing) universe appears to be **recent and MVE-heavy**, not a clean
   2022→present panel. The full historical pull should be run with date-windowing, and Phase
   0 coverage by *calendar* and by *non-MVE category* (sports/econ/weather/politics — the
   classic-FLB-relevant categories) should be checked before relying on the §3 split. If
   older or richer category history is needed, a different/authenticated Kalshi data source
   may be required — flag to the design owner before Phase 1.
4. **Live end-to-end proof:** ~2,400 settled markets pulled across two resumable runs →
   **292 volume-bearing resolved contracts** written, **100% resolution integrity**, **100%
   no-look-ahead**, Phase 0 **CERTIFIED**. All 292 were category `Exotics` (the recent MVE
   front of the feed); a broader, date-windowed full pull is needed for category breadth.
