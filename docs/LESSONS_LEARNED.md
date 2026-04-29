# Building a Point-in-Time Universe from Scratch: Lessons from 90 Hours of Wikipedia Scraping

*What I learned building survivorship-bias-free S&P 500 membership data without paying for it.*

---

## The Problem

Every factor backtest I'd run was contaminated. My universe was 50 stocks that are in the S&P 500 *today* — AAPL, MSFT, NVDA, GOOGL, all the winners. Any long-only baseline on today's survivors in a decade-long bull market earns Sharpe +0.92 before you do anything clever. That's not alpha; it's survivorship bias.

The textbook answer is "buy CRSP or Norgate point-in-time data." The price: $60–300/month. The question I wanted to answer first: can I build a research-grade PIT universe from free public data?

Five sessions, ~90 hours, and 837 membership events later: **yes, but it taught me more about data engineering than about finance.**

---

## Lesson 1: Silent Column Shifts Are the Worst Kind of Parser Bug

Wikipedia's S&P 500 constituent table has gone through at least 4 format eras since 2010. The modern table has 9 columns with an `id="constituents"` attribute. The 2011 table has 4 columns, no ID, and a `|+ S&P 500 component stocks` caption line.

My first parser treated caption lines (`|+`) as data cells. The effect: every header column shifted by one. "3M COMPANY" was extracted as a ticker. One misparse of one revision generated ~1,000 phantom REMOVE+ADD events at the next diff.

**The insidious part:** the parser didn't crash. It produced a DataFrame with the right number of rows and plausible-looking column names. The output was quietly garbage, and I only caught it because the differ emitted 1,000 events for a single revision — a sanity check I'd added "just in case."

**Takeaway:** Any table parser operating across format eras needs a row-count floor. I added: any parse producing fewer than 400 constituent rows raises immediately. It caught 3 more misparses in later sessions.

---

## Lesson 2: A 4-Byte Edit Can Carry More Information Than a 40KB Edit

The FB→META rename on Wikipedia changed exactly 4 bytes of wikitext. My byte-delta filter (designed to catch substantive edits by filtering on `abs(size_t - size_{t-1}) >= 50 bytes`) would have missed it entirely.

This forced a redesign: the filter became a **hybrid** — byte-delta ≥ 50 bytes OR edit comment matches a membership-keyword regex. The keyword regex itself needed tuning: including "S&P 500" generated ~1,000 false positives because MediaWiki auto-generates section-edit comments like `/* S&P 500 component stocks */` for any edit to that section, even typo fixes.

**Final filter:** 1,118 of 2,811 revisions passed (39.8%). All four named-event sanity checks (TSLA add, FB→META rename, GE removal, TWTR delisting) passed.

**Takeaway:** Size-based heuristics miss categorical changes. In any data pipeline where small edits can be semantically important, you need a content-aware filter alongside the volume filter.

---

## Lesson 3: Identity Resolution Makes Everything Else Trivial

The SEC EDGAR `company_tickers.json` file maps every public US filer to a Central Index Key (CIK) number. CIKs are stable across ticker renames: Facebook (FB), Meta Platforms (META), and the intermediate stages all share CIK 0001326801.

With CIK-based identity:
- **Rename detection is trivial.** Same CIK, different ticker between consecutive snapshots = RENAME. No fuzzy name-matching needed.
- **The SYMC→NLOK→GEN chain** (Symantec → NortonLifeLock → Gen Digital, all CIK 0000849399 across two renames) was captured cleanly.
- **The GE family** (GEHC and GEV spinoffs) was correctly classified as new ADDs because they have different CIKs from GE proper.

Without CIK, all of these would have been REMOVE+ADD pairs, doubling the event count and destroying continuity for downstream factor research.

**Caveat:** EDGAR maps *current* tickers only. ~10% of tickers in the 2020 snapshot no longer exist in EDGAR (delisted, merged). For these, `cik=None` is the correct output — it's the point-in-time information the universe is designed to capture, not an error.

**Takeaway:** If your domain has a stable entity identifier (CIK for US public companies, LEI for global entities, ISIN for securities), invest the effort to resolve identity through it. The downstream simplification is enormous.

---

## Lesson 4: Inline Markup Breaks Cell Splitting in Ways That Look Like Data

A vandalism revert on Wikipedia reintroduced an old-format article whose caption contained a multi-line `<ref>` tag with template parameters on separate lines starting with `|`. My cell splitter treated those `|` lines as table cells, shifting columns by 2 for every row in that revision.

The result looked like valid data — ticker-like strings in the ticker column, numbers in the number columns — but was garbage. I call this the "2022 catastrophe" because it corrupted every diff from that revision forward until I added `<ref>...</ref>` and `<!-- ... -->` stripping before row/cell splitting.

**Takeaway:** When parsing structured text that humans edit (wikitext, markdown, HTML), assume that every structural delimiter (`|`, `\n`, `{`, `}`) will appear inside content at some point. Strip nested markup before splitting.

---

## Lesson 5: Don't Advance Your Baseline on Noise — But DO Advance It

The differ compares consecutive parsed snapshots to generate ADD/REMOVE/RENAME events. When a pair of revisions produces more than 8 events (my `MAX_PLAUSIBLE_EVENTS_PER_PAIR` threshold), it's almost certainly parser noise — vandalism reverts, mid-edit saves, format transitions.

My first instinct: skip the noisy pair and don't advance `prev` (the baseline for the next comparison). This was catastrophically wrong. Not advancing `prev` means the *next* diff compares against a stale baseline. If revision 100 is noisy and I keep `prev` at revision 99, then the diff from 99→101 includes both the noisy changes *and* the real changes, making 101 look noisy too. The error cascades — eventually every transition looks suspect.

The fix: skip the noisy pair's events, but **still advance `prev` to the noisy revision**. This means I lose a few real events near noise windows, but the differ recovers immediately. The tradeoff — losing ~5% of real events for noise resilience — is correct for a research universe.

**Takeaway:** In any sequential-diff pipeline, the "skip but advance" pattern is usually right. "Skip and hold" compounds errors.

---

## Lesson 6: The Date-Alignment Off-by-One

My first SPX reconciliation showed a monthly return correlation of **−0.16** and 2,659 bps tracking error. It looked like the universe was fundamentally wrong.

The actual bug: I was storing the post-period NAV at the pre-period date. My `nav_at_date` used the return *during* the period labeled with the *start* date, while the benchmark used the price *at* the labeled date. The effect: my returns were shifted by one month. The COVID crash showed up in March on one series and April on the other.

After fixing the label alignment: monthly return correlation **+0.9895**, tracking error 254 bps, fully explained by adjusted-close-vs-price-only dividend gap (~150–200 bps).

**Takeaway:** In any time-series reconciliation, if the correlation is negative or near-zero, **assume a one-period offset before assuming a methodology bug.** Check by plotting both series and looking for a known event (COVID crash, 2022 rate hikes) that appears on different dates.

---

## Lesson 7: The Benchmark Itself Can Be Wrong

My original validation gate compared an equal-weight reconstruction against `^SP500TR` (the S&P 500 Total Return Index). The gate required ≤50 bps/year tracking error.

The problem: `^SP500TR` is *cap-weighted*. An equal-weight portfolio of the same 500 names structurally underperforms cap-weight by 200–400 bps/year in mega-cap-dominated regimes (2020–2024), regardless of universe quality. My gate would have failed for *any* equal-weight portfolio, even a perfect one.

The fix: benchmark against `^SP500EW` (S&P 500 Equal Weight Index). After switching, the drift was within the ≤50 bps gate once dividend adjustment was accounted for.

**Takeaway:** When validating a portfolio against a benchmark, the benchmark weighting scheme must match your portfolio's weighting scheme. This sounds obvious, but "S&P 500" means at least three different return series (price, total return, equal-weight), and picking the wrong one invalidates the entire validation.

---

## Lesson 8: 75% Coverage Is the Free-Data Ceiling

Of 881 tickers that were ever in the S&P 500 between 2010 and 2026, yfinance returned clean OHLCV for 655. The missing 226 are delisted, restructured, or acquired companies that Yahoo Finance no longer tracks.

This isn't a bug — it's the structural limitation of free data. Companies that leave the index (the ones that create survivorship bias in the first place) are the ones most likely to be missing from free data sources.

For Tier 1, I carry these as known data gaps. For Tier 2 (if the signal survives), CRSP or Norgate ($60/month) would fill most of them.

**Takeaway:** Free data gives you the survivors. Paid data gives you the dead. The dead are exactly what you need for unbiased research.

---

## The Result

| Metric | Value |
|---|---|
| Revisions walked | 2,811 |
| Candidates after hybrid filter | 1,118 |
| Membership events extracted | 837 (407 REMOVE, 352 ADD, 78 RENAME) |
| Spot-check fixtures | 12/12 passing |
| Wikipedia changes-table cross-check | 84% match |
| Year-end membership replay | 15/16 within [495, 510] band |
| Monthly return correlation vs ^SP500EW | 0.9895 |
| yfinance coverage | 655/881 ever-members (74%) |
| Total engineering time | ~90 hours across 5 sessions |

The universe is research-grade. Not perfect — the 226 missing tickers and the absent Siblis cross-check are real limitations — but defensible. Every downstream study that consumes it knows exactly what it's getting and what's missing.

The detailed session-by-session design contract, including all the bugs and their fixes, lives in [PIT_UNIVERSE_DESIGN.md](../alphaforge-python/data/market/PIT_UNIVERSE_DESIGN.md). The implementation itself is at [data/market/pit/](../alphaforge-python/data/market/pit/), with 12 regression tests gating any future parser changes.

---

*This is the kind of problem that looks simple ("just get the list of S&P 500 members over time") and turns out to be an exercise in parsing, identity resolution, diffing, validation, and accepting the limitations of your data source. The 90 hours weren't wasted — they're the difference between a backtest that means something and one that doesn't.*
