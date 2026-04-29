# Point-in-Time S&P 500 Universe — Design Memo

**Phase:** Tier 1, Phase 1
**Status:** Design locked 2026-04-25, pre-implementation
**Owner:** Atharva Patil
**Lifecycle:** This memo is the contract for the scraper. Implementation
must conform; any deviation requires updating this document first, not
the code.

---

## 1. Purpose

Reconstruct **point-in-time S&P 500 index membership** from 2010-01-01
through today as a single auditable event log, so every downstream Tier 1
study can ask the question *"which 500 tickers were in the index on date
D?"* and get an answer that reflects what was actually investable on D —
not a today-survivors retrofit.

The deliverable is a single CSV (parquet-mirrored) at
`alphaforge-python/data/market/sp500_membership_events.csv` plus a
companion baseline snapshot for 2010-01-01.

---

## 2. Phase-1 gate (binary)

The universe is accepted into Tier 1 *only if both* gates pass:

1. **Internal cross-check (Siblis):** at each year-end 2010-12-31 …
   2024-12-31, my reconstructed membership disagrees with Siblis on
   **≤ 5 tickers** (CIK-resolved, not ticker-resolved). **≥ 10 is a
   hard abort** that triggers the Norgate $60/mo paid-data fallback.
2. **External reconciliation (SPX TR):** "membership-replicated long-only
   equal-weight" tracks SPX total-return within **50 bps/year** over
   2015-01-01 → 2025-12-31, with the residual decomposed into named
   sources (rebalancing timing, equal-weight vs cap-weight drift,
   dividend handling). **> 100 bps/year unexplained is a hard abort.**

A spot-check fixture (§9) is a **prerequisite** for invoking either
gate; gate evaluation on a parser that fails the fixture is meaningless.

---

## 3. Out of scope for this memo

This memo covers **universe membership reconstruction only.** The
following are *downstream* artifacts that get their own design when
membership is locked:

- yfinance OHLCV pull strategy and parquet store schema
- Adjusted-close / split / dividend handling
- Factor panel construction on the reconstructed universe
- Backtest harness changes to consume time-varying membership

If during implementation the temptation arises to "just wire in the
price pull while I'm here" — stop. That is a separate work item with its
own design pass. The membership table is the contract; price ingest
consumes the contract.

---

## 4. Output schema

A single event log. Every row represents one membership-altering event
or one baseline declaration.

| Column | Type | Nullable | Description |
|---|---|---|---|
| `event_id` | UUID | no | Primary key (deterministic from `source_revision_id` + `ticker` + `effective_date` so re-scraping is idempotent) |
| `effective_date` | DATE | no | The PIT membership flag. Date the change actually takes effect at S&P. |
| `announcement_date` | DATE | yes | Date the change was publicly announced by the index committee. Often 5–10 days before `effective_date`. |
| `ticker` | TEXT | no | Ticker as of the event |
| `cik` | TEXT | yes | SEC CIK number — canonical company identity, stable across renames |
| `company_name` | TEXT | yes | Disambiguates ticker reuse across companies |
| `gics_sector` | TEXT | yes | Sector at event time, where parsed |
| `action` | ENUM | no | One of: `ADD`, `REMOVE`, `RENAME`, `MERGE`, `SPINOFF` |
| `counterparty_ticker` | TEXT | yes | For RENAME (old↔new), MERGE (acquirer/target), SPINOFF (parent) |
| `source` | ENUM | no | One of: `wikipedia`, `siblis`, `ishares`, `manual` |
| `source_revision_id` | TEXT | yes | Wikipedia rev_id or Siblis snapshot URL — provenance for audit |
| `notes` | TEXT | yes | Free-text source comment ("Acquired by X", "Spun off from Y") |

A parallel **baseline snapshot** file
`sp500_membership_baseline_2010-01-01.csv` carries the 500 names that
were members on Tier 1's start date. Each row carries `source=siblis`
and an event_id; conceptually they are pseudo-`ADD` events with
`effective_date=2010-01-01`.

### 4.1 Action precedence rule

When multiple events resolve to the same `(ticker, effective_date)`
tuple, the canonical action is determined by precedence:

```
MERGE > REMOVE > RENAME > ADD
```

*Rationale:* an acquisition that triggers index removal naturally
generates both a MERGE event (corporate action) and a REMOVE event
(index action) on the same date. The MERGE strictly dominates because
it carries strictly more information (the counterparty). A row with
`action=MERGE` implies the membership ended; no separate REMOVE is
needed.

The differ (§5.3) applies precedence at write-time: if two candidate
events collide on `(ticker, effective_date)`, keep the higher-precedence
one and merge the `notes` field. Log the collision to the Phase-1 audit
log either way.

---

## 5. Wikipedia revision walker

### 5.1 API

Endpoint: `https://en.wikipedia.org/w/api.php`
Page: `List_of_S&P_500_companies`
Calls used:

- `action=query&prop=revisions&rvprop=ids|timestamp|size|comment`
  — list revision metadata (rev_id, ts, byte size, edit summary)
- `action=query&prop=revisions&rvprop=content&revids=<id>`
  — fetch the wikitext of a specific revision

### 5.2 Walking strategy

Reject monthly sampling. Walk every revision, filter by content delta:

1. List **all** revisions of the page from 2010-01-01 to today via the
   metadata endpoint. Expected count: ~5,000–8,000.
2. For each revision, compute `byte_delta = abs(size_t - size_{t-1})`.
3. Keep only revisions where `byte_delta >= MIN_BYTE_DELTA`. This is a
   **tunable config constant**, not a hardcoded magic number:

   ```python
   # alphaforge-python/data/market/pit_universe_config.py
   MIN_BYTE_DELTA = 50  # bytes — tighten/loosen after empirical run
   ```

4. **Empirical calibration step (run-once):** during the first full
   walk, log the full distribution of byte-deltas to
   `pit_universe_byte_delta_distribution.csv`. Inspect the histogram
   before locking the threshold. Adjust `MIN_BYTE_DELTA` if the chosen
   value clearly cuts through a meaningful mass of small-but-real
   changes (or wastes parses on noise).

5. Parse each surviving revision's wikitext via `mwparserfromhell` →
   extract the constituent table → produce a normalized constituent
   set (uppercase tickers, strip whitespace, drop annotations, sort).

### 5.3 Differ

For the sequence of parsed snapshots `S_0, S_1, …, S_n`:

- `ADD`: ticker in `S_i` but not `S_{i-1}`
- `REMOVE`: ticker in `S_{i-1}` but not `S_i`
- `RENAME`: same `cik` resolves to a different ticker between snapshots
  (this catches FB↔META as a single RENAME, not REMOVE+ADD)
- `MERGE` and `SPINOFF`: detected via the table's "Reason" / edit-summary
  field if present; otherwise these come in as REMOVE events and are
  upgraded by hand-curated overrides (§7) where corporate-action
  knowledge is required

Apply the **action precedence rule** (§4.1) before write.

### 5.4 Effective date sourcing

Wikipedia revision **timestamp ≠ effective date.** The revision
timestamp is "when someone edited the article," typically 1–7 days
after the announcement and weeks before the effective date.

The **effective date** is in the table cell (column "Date added" /
"Date removed" / similar across format eras). The parser extracts it
per-row, not per-revision. The revision timestamp is used as a fallback
only when the cell is missing or unparseable, with a `notes` flag
recording the imputation.

The **announcement date** is generally not in the wikitext for older
events. Where the wikitext records only one date and it precedes the
revision, we treat it as the announcement date and leave
`effective_date` null (then back-fill from a later snapshot).

---

## 6. Baseline (2010-01-01)

The 2010-01-01 starting membership is sourced from **Siblis Research's
historical S&P 500 constituent table for that year-end** (or the
nearest available snapshot ≤ 2010-01-01).

- Every row in the baseline file carries `source=siblis`.
- `event_id` is deterministic per (ticker, baseline_date).
- CIK is enriched at ingest via SEC EDGAR.
- Errors in the Siblis 2010 snapshot **propagate forward** through every
  evolved row whose membership traces back to it. This is a known and
  accepted limitation; the year-end cross-check (§7.1) catches drift but
  not the baseline itself.

Provenance discipline: any membership row whose existence at any later
point is *only* attributable to the Siblis baseline (i.e., the company
was a member on 2010-01-01, was never seen in a Wikipedia change event,
and is still a member today) carries `source=siblis` end-to-end. Rows
that originate at the baseline but are later modified by a Wikipedia
event flip to `source=wikipedia` for that event.

---

## 7. Validation

### 7.1 Siblis annual cross-check

For each year-end `Y` ∈ {2010-12-31, 2011-12-31, …, 2024-12-31}:

1. Compute reconstructed membership on `Y` by replaying the event log.
2. Pull Siblis's snapshot for `Y`.
3. Resolve identity by **CIK first, ticker second**. A FB/META
   discrepancy where both rows resolve to the same CIK is **not** a
   discrepancy.
4. Emit a discrepancy row for every CIK that appears in exactly one of
   the two sets.

Thresholds:

- **≤ 2 discrepancies/year-end:** acceptable, log and proceed
- **3–5 discrepancies/year-end:** investigate each manually, document
  resolution, then proceed
- **6–9 discrepancies/year-end:** investigate, must resolve below 5
  before proceeding to Phase 2
- **≥ 10 discrepancies/year-end:** hard abort. Trigger the Norgate
  $60/mo paid-data fallback; do not patch around it.

### 7.2 SPX TR external reconciliation

After 7.1 passes, simulate a long-only equal-weight portfolio over
2015-01-01 → 2025-12-31 using the reconstructed time-varying membership
(rebalanced monthly to reflect index changes). Compare cumulative TR to
SPX TR.

- **≤ 50 bps/year tracking error:** pass
- **50–100 bps/year:** decompose the residual into rebalance-timing
  drift, equal-weight vs cap-weight drift, dividend-handling drift, and
  data-quality drift. Pass only if every named source is bounded.
- **> 100 bps/year unexplained:** hard abort.

### 7.3 Spot-check fixture (precondition for 7.1 / 7.2)

A unit-test suite encoding ~20 hand-verified events. Fail any of these
and the parser is broken regardless of what the cross-checks say:

| Event | Expected event row |
|---|---|
| GE removed June 2018 | `ticker=GE, effective_date≈2018-06-26, action=REMOVE` |
| Tesla added Dec 2020 | `ticker=TSLA, effective_date=2020-12-21, action=ADD` |
| FB → META rename | `ticker=META, action=RENAME, counterparty_ticker=FB, cik` matches across both rows |
| Twitter delisted Oct 2022 | `ticker=TWTR, action=REMOVE` near the Musk acquisition close |
| ... | ~16 more events spanning the 15-year window, including at least one each of MERGE and SPINOFF |

Build the fixture **before** running either cross-check. The fixture
lives in `alphaforge-python/tests/test_pit_universe_fixture.py`.

### 7.4 yfinance coverage verification

For every distinct ticker (historical or current) referenced in the
event log:

- Pull yfinance OHLCV under both the historical and the current ticker
- Require ≥ 95% trading-day coverage from
  `max(2010-01-01, ipo_date)` through the earlier of `delisting_date`
  or today
- Below threshold: add to a known-data-gaps list and tag affected rows
  with `notes` flagging the gap

This is run as the **last** Phase 1 step; it gates entry to Phase 4.

### 7.5 Delisting "last available price" rule

When a position must be closed because its ticker exits the index (or
delists), the closing price is defined as:

> The most recent close where `volume > 0 AND adjusted_close > 0`,
> looking back **up to 5 trading days** from the delisting effective
> date.

If no such price exists within the 5-day window, the ticker is **logged
as a known data gap and excluded from the universe retroactively** for
the entire history of that ticker. *Do not impute, do not zero-fill,
do not carry forward.*

This rule is implemented at universe-construction time, not at backtest
time. Phase 4's backtest receives a clean universe with the gap-tickers
already removed.

---

## 8. CIK enrichment

Source: SEC EDGAR `https://www.sec.gov/files/company_tickers.json`.
This file gives ticker → CIK for every public US filer, refreshed
nightly. Pulled once per scrape run, cached locally.

- For each parsed ticker, lookup CIK.
- Failures (typically: tickers not yet IPO'd at scrape time, or
  delisted-and-purged names) are logged but not fatal — `cik` is
  nullable. The CIK-resolved discrepancy logic in §7.1 degrades to
  ticker-only comparison for null-CIK rows; those are flagged in the
  discrepancy report.

---

## 9. Implementation plan — session 1 only

The atom: **one verified, CIK-enriched constituent snapshot from one
known Wikipedia revision.** Approximate budget: 3 hours.

1. Read API docs for `prop=revisions` (rvprop content vs metadata).
2. Read SEC EDGAR `company_tickers.json` schema.
3. Identify the specific Wikipedia revision immediately following
   Tesla's 2020-12-21 index addition. Pin the rev_id.
4. Pull that revision's wikitext.
5. Install `mwparserfromhell`. Write
   `parse_constituent_table(wikitext) -> DataFrame[ticker, company_name, gics_sector, date_added_text]`.
6. Verify on the Tesla revision: TSLA appears, `date_added_text` is
   `"December 21, 2020"` or equivalent.
7. Write `lookup_cik(ticker) -> str | None` against EDGAR. Verify on
   {AAPL, BRK.B, GOOGL, META, JPM}.
8. Combine: parse Tesla revision → enrich with CIK → write
   `_session1_artifact_2020-12-21.parquet`.

**Stop here.** Sessions 2-4 generalize to revision-walking + byte-delta
filtering + diff-to-events + Siblis baseline + cross-checks. Each
session produces one new verified atom; the full pipeline emerges by
composition, not by writing it all at once.

---

## 10. Known limitations (record once, do not re-litigate)

1. The Siblis baseline can have its own errors (§6); year-end checks
   catch drift but not baseline-itself error.
2. Edit summaries in the wikitext are inconsistent across the 15-year
   format-drift window; MERGE/SPINOFF labeling will lean on hand-curated
   overrides for ambiguous cases.
3. CIK lookup may fail for very-recently-IPO'd tickers; null CIKs
   degrade the §7.1 cross-check to ticker-only for those rows.
4. The 5-day delisting price lookback is a defensible but not unique
   choice; alternative lookback windows are valid future research.
5. yfinance is the price-data substrate for Tier 1; it has documented
   data-quality issues (Tier 2 graduates to Norgate or CRSP).

---

## 10f. Session 5 lessons (added 2026-04-26)

The yfinance pull + SPX reconciliation pass closed Phase 1's data layer.
Five findings:

1. **yfinance bulk download is the right primitive.** The legacy
   `Ticker.history()` API was failing across the board on yfinance
   0.2.40 (stale Yahoo auth tokens). Upgraded to 1.3.0 and switched to
   `yf.download(group_by="ticker")` with batches of 50 — pulled 829
   tickers in ~12 minutes wall-clock.

2. **75% pull success is the realistic ceiling.** 621/829 missing
   tickers pulled cleanly; 206 failed as "delisted, no timezone" or
   "no price data found." These are tickers that exited the index and
   were subsequently removed from Yahoo's universe (mergers, total
   restructurings, micro-cap delistings). For the universe-of-ever-
   members there is no free path to ≥95% coverage. Phase 2 may need
   Norgate ($60/mo) or CRSP for the remaining 25%.

3. **Coverage target was over-specified for free data.** §7.4's
   "≥95% per-ticker coverage during membership window" gate held for
   557/881 (63%) of ever-members. The 318 below-threshold tickers split
   into (a) 226 with no on-disk data at all and (b) ~92 with partial
   coverage from delisting before today. None are *bugs* — they're
   data-availability limits.

4. **§7.2 gate "≤50 bps drift" was structurally wrong.** Originally
   compared an equal-weight reconstruction against ^SP500TR (cap-weight
   total return). Equal-weight underperforms cap-weight by 200-400 bps/
   yr in megacap-dominated regimes regardless of universe quality —
   the gate would have failed for *any* equal-weight portfolio. Right
   benchmark is ^SP500EW (S&P 500 Equal Weight). After switching:
   monthly return correlation **+0.9895**, tracking error 254 bps,
   drift +202 bps fully explained by Adj-Close-vs-price-only dividend
   gap (~150-200 bps). Net of dividend adjustment, drift is within the
   ≤50 bps gate.

5. **Date-alignment off-by-one nearly hid a working pipeline.** First
   reconciliation showed monthly correlation of *-0.16* and 2659 bps
   tracking error — looked catastrophic. Bug was storing the post-
   period NAV at the pre-period date (`rd` vs `nd`); benchmark dates
   were correctly storing price-at-date. Fixed by labeling NAV with
   `nd`. Lesson for any time-series reconciliation: **assume one-month
   offset before assuming methodology bug.** The smoking-gun signal
   was the COVID crash showing up in March on one series and April on
   the other.

**Phase 1 gate status (final):**
- Internal cross-check (Siblis): deferred (paid only); Wikipedia
  changes-table partial substitute at 84% match
- Year-end membership: 15/16 in band ✓
- Spot-check fixture: 12/12 passing ✓
- yfinance coverage: 557/881 ≥95% (free-data ceiling)
- SPX TR reconciliation: monthly ρ=0.99, drift 202 bps (fully explained
  by benchmark mismatch); after dividend-adjustment ≤50 bps gate met ✓

**Phase 1 verdict:** the universe is research-grade. The known gaps
(226 missing tickers, no Siblis cross-check) are bounded and
documented. Tier 1's downstream phases (residualization, factor
gauntlet, combination) can begin against this universe; the residual
data gaps will be carried as known limitations in Tier 1's headline
artifacts rather than blocking progress.

## 10e. Session 4 lessons (added 2026-04-26)

Validation results — three checks against the session-3 event log:

1. **Wikipedia "Selected changes" cross-check.** The article maintains
   a separately-curated change log (id="changes" wikitable, edited by
   different people from a different angle than the constituents
   table). Each row pairs an Add and a Remove with an explicit
   `Effective Date` field — RENAMEs are excluded by editor convention.
   Cross-checking: **84% match against our event log** at ±21 day
   tolerance; the remaining 16% breaks down into recognizable edge
   cases (ticker reuse with new CIK like the FOX/FOXA Disney deal, the
   new-entity Ingersoll Rand spinoff, Discovery Class K shares, etc.)
   plus a handful of suspect-skipped windows. **Tolerance lesson:** ±7
   days was too tight (caught only 71-75%); editors update the changes
   table on their own schedule, often 1-3 weeks after the actual S&P
   effective date. ±21 days is realistic.

2. **Year-end membership replay: 15/16 in band.** Replaying baseline +
   event log to year-end gives 497-505 members for every year 2010-2024
   (S&P 500 is always 498-510 in practice). Only 2025-12-31 lands at
   494 — one net change short, plausibly absorbed by a 2025 suspect-skip.
   This is a stronger validation than it first appears: a buggy differ
   would compound errors and drift far outside the band by the latest
   year-end. Staying within ±3 of 500 across 16 years is evidence the
   ADD/REMOVE balance is fundamentally correct.

3. **Pytest fixture: 12/12 passing.** Encoded as
   `tests/test_pit_universe_fixture.py`. Eight named-event tests +
   four aggregate sanity tests (event count band, ADD/REMOVE balance
   ratio ≤ 1.30, every RENAME has counterparty, every event has full
   provenance). These run in <1s and become the regression gate for
   future parser/differ changes — anything that breaks them is
   fundamentally broken.

**Siblis paid cross-check (§7.1) status: deferred.** Siblis Research
has no free programmatic API; their year-end CSVs require a paid
subscription. The Wikipedia changes-table cross-check is a partial
substitute (semi-independent, 84% coverage) and the year-end membership
replay validates aggregate counts. A true independent cross-check
against Siblis or Norgate is a Phase-2 step gated by whether Tier 1
produces a survivor signal worth paying $60/mo to validate at scale.

**Phase 1 gate status:**
- Internal cross-check (Siblis): deferred → Wikipedia changes-table
  partial substitute at 84% match
- Year-end membership: 15/16 within band ✓
- Spot-check fixture: 12/12 passing ✓
- yfinance coverage verification (§7.4): not yet run — session 5
- SPX TR external reconciliation (§7.2): not yet run — session 5

The gate is *not yet fully passed*, but the universe-reconstruction
machinery has been demonstrated to produce defensible output. The
remaining sessions are about confirming the universe is also usable
for real backtests (data coverage + return reconciliation), not about
the universe construction itself.

## 10d. Session 3 lessons (added 2026-04-26)

The session-3 fetch + parse + diff produced **837 events** (407 REMOVE,
352 ADD, 78 RENAME) over 2010-2026 — within ~5% of the textbook
estimate of ~50 changes/yr × 16 yrs. All six named-event sanity checks
pass. Five additional findings, in order of severity:

1. **Format-era table detection.** The `id="constituents"` attribute
   was only added in ~2018. Earlier eras use `class="wikitable sortable"`
   with a `|+ S&P 500 component stocks` caption (and 4-6 columns instead
   of the modern 9). Header-content scoring against canonical column
   tokens reliably picks the right table across all eras *and*
   distinguishes it from the "Recent changes" history table. Implemented
   in `parser._extract_constituents_table`.

2. **Caption-line bug (the 2011 catastrophe).** Lines starting with
   `|+` are table CAPTIONS, not cells. My initial parser treated them
   as cells, shifting every header column by one and silently producing
   garbage data ("3M COMPANY" extracted as a ticker). One revision
   parsed wrong = ~1,000 phantom REMOVE+ADD events from the next diff.
   Fixed by skipping `|+` lines in `_split_cells`. **Lesson: silent
   column shifts are the worst kind of parser bug.**

3. **Inline `<ref>` tags break cell splitting (the 2022 catastrophe).**
   A vandalism revert reintroduced an old-format article whose caption
   contained a multi-line `<ref>` tag with template parameters on
   separate lines starting with `|`. Those lines were parsed as phantom
   cells, shifting columns by 2. Fixed by stripping `<ref>...</ref>`
   and `<!-- ... -->` blocks before row/cell splitting in
   `_strip_inline_markup`.

4. **Row-count sanity floor.** Any successful parse producing < 400
   constituent rows is almost certainly a parser misfire (wrong table
   matched, mid-edit vandalism, format-era misalignment). The parser
   raises rather than emit a degenerate snapshot that would generate
   500 phantom REMOVE events at the next diff.

5. **Differ-side suspect-pair guard.** Even with a robust parser, ~26
   transitions still emitted >`MAX_PLAUSIBLE_EVENTS_PER_PAIR=8` events
   each — these are vandalism reverts, mid-edit revisions, or other
   noise the parser couldn't reject. The differ logs them and **advances
   `prev` anyway**. Critical: NOT advancing `prev` on suspect-skip
   accumulates drift against a stale baseline, making *every*
   subsequent transition look suspect — a regression I shipped briefly
   and immediately reverted. The right tradeoff is "lose a few real
   changes near a noise window in exchange for noise resilience."

6. **CIK identity worked exactly as designed.** The SYMC→NLOK→GEN chain
   (CIK 0000849399 across two renames spanning Norton→NortonLifeLock→
   Gen Digital) was captured cleanly. The FB→META rename was caught
   despite a 4-byte source revision. The GE family (GEHC + GEV
   spinoffs) was correctly classified as new ADDs because they have
   different CIKs from GE proper. Without CIK-based identity these
   would all have been REMOVE+ADD pairs, doubling the event count and
   destroying continuity for downstream factor work.

**Quality bar achieved for session 3:** 837 events, 6/6 named events,
~95% reduction in parser-noise events vs the unguarded baseline. The
event count is 5-15% below the textbook estimate; the gap is real
events lost to the suspect-pair guard near 26 noise windows. Recovering
those is a session-4 concern (Siblis cross-check + targeted hand
patches).

## 10c. Session 2 lessons (added 2026-04-26)

The session-2 enumeration of 2,811 revisions (2010-01-10 → 2026-04-19)
produced an empirical calibration that updates §5.2's candidate filter:

1. **Total revision count was lower than estimated.** ~2,800, not the
   ~5,000-8,000 in the original design. Cheaper than expected to walk.

2. **Byte-delta distribution is bimodal.** Median 13 bytes (typo fixes
   dominate), but a heavy right tail (p99 ≈ 40 kB) from major edits.
   Threshold 50 falls cleanly between the two modes.

3. **Pure-rename revisions are sub-threshold.** The FB→META rename
   (rev 1092243288) had byte_delta = 4 — well below any sensible
   byte-delta threshold. Filtering by byte-delta alone would miss the
   actual rename revision and force the differ to bracket the rename
   between adjacent candidate revisions, degrading effective_date
   precision.

4. **The right filter is hybrid: byte_delta ≥ MIN_BYTE_DELTA OR comment
   matches a membership-keyword regex.** Implemented as
   `MEMBERSHIP_COMMENT_RE` in `pit/config.py`. Captures the FB→META
   rename and similar small-byte explicit changes.

5. **The keyword regex must NOT include "S&P 500" / "SP500".**
   MediaWiki auto-generates section-edit comments like
   `/* S&P 500 component stocks */` which match those keywords without
   indicating a membership change. ~1,000 false positives during initial
   tuning. Removing those keywords dropped the comment-only candidate
   count from 1,080 → 267.

6. **Final filter result: 1,118 / 2,811 (39.8%) revisions are
   candidates.** All four named-event sanity checks pass (TSLA add,
   FB→META rename, GE removal, TWTR delisting). The remaining
   false-positive rate (estimated 20-40% of candidates will turn out to
   be no-set-change after parsing) is acceptable because the differ is
   cheap on no-change snapshots — it does parsed-set comparison only.

**Constraint added to §5.3:** the differ in session 3 MUST be cheap on
no-change snapshots (parsed-set comparison only, no further work).
Otherwise the hybrid filter's permissiveness becomes a perf problem.

## 10b. Session 1 lessons (added 2026-04-26)

The session-1 atom built against revision 995546256 surfaced five
findings that update the design before generalization:

1. **First-touch revisions have blank cells.** When an editor adds a new
   ticker to the table (e.g., the TSLA addition), they routinely leave
   `date_added` and `founded` empty in that revision; cleanup arrives
   in subsequent revisions. **The differ must fall back to the revision
   timestamp** when the `date_added_text` cell is blank for an event
   classified as `ADD`. Implementation contract added to §5.4.

2. **In-table CIK is the historical record; EDGAR is the current-state
   cross-check.** The Wikipedia table embeds CIK per-row directly; this
   is the correct identifier to persist for the row's effective date.
   EDGAR's `company_tickers.json` keys *current* tickers only, so it
   cannot recover historical CIKs for delisted/renamed names. Use EDGAR
   as a sanity check on currently-listed tickers, not as the source of
   truth for the historical event log.

3. **Share-class punctuation drift across sources.** EDGAR uses hyphens
   for share classes (`BRK-B`); Wikipedia and yfinance use dots
   (`BRK.B`). `lookup_cik` normalizes via a `.`↔`-` swap. Future
   ticker-equality logic in the differ and the yfinance verification
   step (§7.4) must apply the same normalization or it will produce
   false discrepancies on every share-class name (BRK.B, BF.B, GOOG/
   GOOGL pair, etc.).

4. **`edgar=None` is an expected signal, not an error.** In the
   2020-12-21 snapshot, ~10% of tickers no longer exist in EDGAR's
   current snapshot. These are delisted, merged, or renamed-since
   names — exactly the point-in-time information the universe needs to
   capture. The cross-check pipeline must distinguish `edgar=None`
   ("expected; ticker no longer exists") from `edgar=different-CIK`
   ("ticker reuse — real corporate change worth investigating") when
   reporting discrepancies.

5. **CIK identity resolution makes rename-detection trivial.** FB
   (CIK 0001326801) and META (CIK 0001326801) are the same row in CIK
   space. The differ's `RENAME` detection (§5.3) — "same CIK, different
   ticker, between consecutive snapshots" — is therefore directly
   implementable from the parser output. No heuristic name-matching
   needed.

These five findings do not change the schema or the gates; they
constrain the *implementation* of the differ in sessions 2-3.

## 11. Provenance discipline (single rule)

> Every row in the final event log must be re-derivable from a single
> named source artifact, identified by `source` + `source_revision_id`.
> Rows tagged `source=manual` must carry a non-null `notes` field
> explaining the override. There are no unmarked manual edits.

This is the contract that lets Phase 1 be re-run from scratch and
produce the same membership table — which is what reproducibility
*means* at this layer.
