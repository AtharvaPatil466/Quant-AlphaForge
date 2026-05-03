# Blog Post Outline — Building a Point-in-Time S&P 500 from Wikipedia Revisions

**Working title (pick one before drafting):**
- "What 2,811 Wikipedia revisions taught me about survivorship bias"
- "Reconstructing the S&P 500, one edit at a time"
- "Why your backtest universe is lying to you"

**Target length:** 1,800-2,400 words. Long enough to be substantive,
short enough that a recruiter actually finishes it.

**Audience:** A skeptical quant or recruiter who has 8 minutes. They
should leave knowing (a) you understand survivorship bias deeply,
(b) you can ship a real engineering project, (c) you debug honestly.

**Voice:** Technical, first-person, direct. Light self-deprecation
on the debugging stories — never on the methodology. No emojis. No
"in this post we will." Open with a concrete claim or number, not a
preamble.

---

## Section 1 — The hook (~150 words)

Lead with the punchline number: a long-only equal-weight backtest
on the 50 today-surviving large-caps in the S&P 500 over 2010-2025
overstates annualized return by ~1.5-2% vs. the true point-in-time
universe. Then state the problem in one sentence: there is no free
programmatic API for historical S&P 500 membership; Siblis charges
for it; the "obvious" sources (Wikipedia's current page, ETF
holdings, Yahoo) all snapshot today. Frame the post: I rebuilt
historical membership from Wikipedia revision history + EDGAR CIK
enrichment. Five sessions, 90 hours, 837 events, validated.

End the section with a single question that drives the rest of the
post: "Why is this harder than it sounds?"

## Section 2 — Why "today's list" silently destroys backtests (~250 words)

Concrete example. Pick 3-4 names that *were* in the index but are
not today (Lehman, Bear Stearns, Sears, GE before its restructuring)
and 3-4 names that joined recently (Tesla 2020, Coinbase, etc).
Show, with one paragraph each:

- A backtest on today's list will have shorted-out the disasters and
  loaded the winners — both biases push reported Sharpe up.
- The asymmetry: 226 of 881 ever-members in 2010-2025 have *no
  data at all* in standard providers because they were delisted /
  acquired / restructured. They are the most informative names for
  any factor that prices distress.

Cite the rough magnitude (1-2% annualized return inflation is the
classic estimate; cite Brown/Goetzmann/Ross 1992 if you want the
academic anchor). Don't over-cite — one or two references max.

## Section 3 — Why Wikipedia (~200 words)

The non-obvious choice. Walk through the three sources I considered:

1. **Paid (Siblis, Compustat, CRSP)** — gold standard, but $60-1000+/mo
   for a side project. Out of budget.
2. **ETF holdings (SPY)** — only goes back to ETF inception; misses
   the whole pre-2000 history; only snapshots quarterly.
3. **Wikipedia page revisions** — every edit is timestamped, the
   wikitext is structured (templates + tables), and the API is free
   and unrate-limited for read access.

The bet: the S&P 500 Wikipedia page is one of the most-watched on
the site. Edits are reviewed by editors who care about index
membership. If you can parse the diffs across ~2,800 revisions,
you can reconstruct membership without paying anyone.

Honest caveat: this is a noisier source than CRSP. The validation
work in Section 7 is what makes the result trustworthy.

## Section 4 — The CIK normalization rabbit hole (~300 words)

The first hard subproblem. Wikipedia uses ticker symbols. Tickers
are *not* unique keys over time:

- Companies change tickers (FB → META in 2022).
- Share-class notation differs across sources: Berkshire is "BRK.B"
  on NYSE, "BRK-B" on Yahoo, "BRK/B" on some Wikipedia revisions.
- Two unrelated companies can hold the same ticker years apart.

The fix: SEC EDGAR's `company_tickers.json` maps tickers to CIKs
(Central Index Key — a permanent identifier per registrant). I built
a normalizer that handles `.↔-` share-class punctuation, falls back
on company name when CIK lookup fails, and caches the mapping
locally so it survives EDGAR rate limits.

Show the actual punctuation-normalization function (5-8 lines of
Python). It's the smallest piece of code in the post but the one
that took the longest to debug. Single test case: BRK.B / BRK-B
both resolve to CIK 1067983.

## Section 5 — The byte-delta vs comment-keyword filter (~250 words)

The second hard subproblem. 2,811 revisions is too many to fetch in
full. You need a cheap pre-filter that catches every membership
change without false negatives.

Two signals available cheaply (revisions list comes with metadata
and edit comment, no wikitext fetch needed):

- **Byte delta** — adding/removing a row in the constituents table
  is roughly ±200 bytes. Pure typo fixes are ±5-20 bytes.
- **Comment keyword** — editors who add/remove an index member often
  say so ("added Tesla", "removed Sears").

The naive AND filter (byte-delta AND comment) misses ~12% of real
events because editors don't always describe what they did. The
naive OR filter (byte-delta OR comment) catches everything but
returns ~3,500 candidates, more than the input.

The hybrid: comment-keyword passes the candidate immediately;
otherwise require byte-delta > 150. Calibrated against a manually-
labeled training set of 50 revisions. Result: 1,118 candidates with
~99% recall on the labeled set. Show the calibration curve.

## Section 6 — Four parser bugs (~300 words)

The honest part. Walk through 3-4 bugs I shipped, what they looked
like in the output, and how I caught them. Suggested four:

1. **Caption-row misclassification** — Wikipedia editors sometimes
   add a "Date added" column header that the row-detector treated as
   a member entry. Caught by a sanity-check assertion that membership
   never exceeds 510 names.
2. **Reference tag bleed** — `<ref>` tags inside the ticker cell.
   Strip with regex before CIK lookup.
3. **Header shift on multi-row table edits** — when an editor
   restructures the columns, the parser silently mis-indexed for
   ~40 revisions. Caught by a year-end snapshot test that requires
   membership ∈ [495, 510].
4. **Action-precedence in the differ** — a single revision that
   both removes one ticker and adds another to the same CIK was
   being recorded as a RENAME in some cases and an ADD+REMOVE in
   others. Locked precedence rules and added a suspect-pair guard.

For each bug, one sentence on the symptom, one on the root cause,
one on how the fix is regression-tested. This section is the post's
credibility — it proves you debug rather than worship your code.

## Section 7 — Validation (~250 words)

Three independent checks, in increasing strength:

- **Spot-test fixtures** — 12 well-known events (TSLA add 2020-12-21,
  GE removal 2018-06-26, etc.) verified by hand. All 12 pass.
- **Cross-check against Wikipedia's own "Selected changes" table** —
  semi-independent because the table is human-curated. 84% match.
  Discuss the 16% gap honestly: most are RENAMEs the changes table
  doesn't track, plus a handful of revisions where my differ caught
  events the curated table missed.
- **The hard test: monthly return correlation against `^SP500EW`** —
  build an equal-weight portfolio of the PIT membership at each
  month-end, compute monthly returns, correlate against Yahoo's
  S&P 500 EW total return ticker. Result: **0.9895** correlation
  over 16 years.

The third test is the one that matters. If the membership list were
materially wrong, the correlation would not be 0.99. It is. Ship it.

## Section 8 — What I'd do differently (~150 words)

Three honest items:

1. **Pay Siblis.** $60/mo for 12 months is $720; the 90 hours I
   spent are worth more than that at any reasonable hourly rate.
   Building it myself was the right *learning* call, the wrong
   *engineering* call.
2. **Cache the wikitext fetches sooner.** I re-fetched the same
   1,118 revisions three times during debugging. Disk is free.
3. **Write the validation suite first.** I wrote the parser, then
   the differ, then the validator. The validator caught bugs in
   both upstream layers. Reverse the order next time.

## Section 9 — What this is for (~100 words)

Closing. Don't oversell. State plainly: this is the universe
substrate for an honest factor study. Most cross-sectional factor
results in the literature are over-stated by survivorship bias by
some amount; the next post (or paper) reports what survives a
gauntlet on this universe.

Link to: the GitHub repo, the design doc
(`alphaforge-python/data/market/PIT_UNIVERSE_DESIGN.md`), the event
log artifact, and your follow-up post when it exists.

---

## Appendix — what to NOT include

- The Tier 1 narrative. This post is about Phase 1 only. The factor-
  study failure goes in its own post (after Phase 6 ships) so each
  artifact stands alone.
- Sales language. No "this is the foundational stack for a future
  hedge fund." That belongs in private memos, not a public technical
  post about debugging Wikipedia parsers.
- Full code dumps. Use 5-10 line snippets to illustrate; link to the
  repo for the rest. Long code blocks lose readers.
- Benchmarks against Siblis. You don't have Siblis access; don't
  pretend the comparison would be favorable. Just say "verified
  against `^SP500EW` at 99%" and let the reader judge.

---

## Drafting plan

- **Day 1 (~2 hrs):** sections 1-3. The framing is the hard part;
  if you nail it, the technical sections write themselves.
- **Day 2 (~3 hrs):** sections 4-6. The middle of the post. Pull
  actual code snippets and bug commit messages from git log.
- **Day 3 (~2 hrs):** sections 7-9. The validation section is your
  credibility; spend the time on the 0.9895 paragraph.
- **Day 4 (~1 hr):** read aloud, cut 20%, ship.

Total: ~8 hours over 4 sittings. Fits inside one week of the
parallel-skill-track budget.

**One commitment to make before drafting:** decide whether this
post lives on a personal site (better for recruiter signal long-
term) or as `WRITEUP.md` in the repo (faster to ship, lower
discoverability). Either is fine; just pick before opening the
editor so you don't get stuck on infrastructure questions instead
of writing.
