# Phase 6 Design — Honest Writeup + Tier 2 Decision

**Phase:** Tier 1, Phase 6
**Status:** Design draft 2026-05-01
**Owner:** Atharva Patil
**Lifecycle:** Implementation must conform to this memo; deviations
require updating this document first.
**Predecessors:** PHASE4_DESIGN.md, PHASE5_DESIGN.md, and the gate
results in `research/out/phase{4,5}_gate_result.md`.
**Outcome to write up:** Tier 1 gate FAILED — 0/9 single factors,
0/4 combinations clear DSR > 0.95 in both OOS windows. MV combination
nearly passes (DSR 0.85 / 0.81; pre-committed hurdle 0.95).

---

## 1. Why this phase exists

Phase 6 has two jobs, in order:

1. **Produce one publishable artifact** — a single LP-grade research
   memo that documents what was tested, what survived, what didn't,
   and what the failure tells you about the inefficiency space. This
   is the document a master's admissions committee, a quant desk
   recruiter, or a future LP would actually read. Its existence is
   the deliverable; whether it reports a PASS or a FAIL is secondary.
2. **Commit to a Tier 2 diagnostic** — pick one row of the failure-
   path matrix in TIER1_STATUS.txt and justify it. The Tier 2 sub-
   plan is downstream of this commitment; without it, Tier 2 is
   guessing.

If the writeup ships but the diagnostic is hedged, Phase 6 has
failed. If the diagnostic is committed but the writeup is hand-wavy,
Phase 6 has failed.

---

## 2. The audience

Three readers, ranked by how much they shape the writing:

1. **A skeptical quant who's never seen the project** — the bar.
   Does the methodology hold up to a 30-minute hostile read?
2. **A master's admissions committee or desk recruiter** — does the
   document demonstrate that the author can run a rigorous gauntlet,
   kill bad ideas, and pivot on evidence?
3. **Future-self in 6 months** — when revisiting Tier 2 design, can
   I reconstruct exactly why I chose the diagnostic I chose?

The writeup is **not** for current LPs. There are none, and the
project rating against the fund-seed bar is too low to warrant LP
contact. Don't pretend otherwise.

---

## 3. Structure (locked)

```
PHASE6_WRITEUP.md
├── 0. Abstract (1 paragraph, ≤200 words)
├── 1. Thesis
├── 2. Methodology
│     2.1 Universe construction (PIT)
│     2.2 Risk model + residualization
│     2.3 Gauntlet (DSR, SPA, RC, purged CV, two OOS)
│     2.4 Cost model
├── 3. Results
│     3.1 Single-factor gauntlet (Phase 4)
│     3.2 Factor-combination gauntlet (Phase 5)
│     3.3 The MV result — framed honestly
│     3.4 Capacity (placeholder; data point pending)
├── 4. The diagnostic
│     4.1 The two candidate rows of the failure-path matrix
│     4.2 The raw-returns rerun as the disambiguating test
│     4.3 Committed diagnostic + Tier 2 implication
├── 5. What would change my mind
├── 6. Limitations and known-unknowns
├── 7. Tier 2 sub-plan (1 page; details deferred to its own memo)
└── Appendix: full per-factor tables, JSON pointers
```

§4 is the only section that depends on the May 15 raw-rerun. Every
other section can be drafted before then.

---

## 4. Pre-committed honesty rules

These prevent the writeup from becoming a sales document:

- **No ex-post threshold relaxation.** DSR > 0.95 was the gate; if
  MV at 0.85 is reported, it is reported as "did not clear the
  pre-committed gate," full stop. The number 0.85 is interesting and
  worth flagging, but it is not redefined as a pass.
- **No new trial set surgery.** The trial count is what it is at the
  time the writeup is finalized. Trimming trials post-hoc to inflate
  DSR is exactly the failure mode the deflation guards against.
- **No hidden combinations.** Every combination strategy that was
  evaluated appears in the report, including the negative ones.
  Cherry-picking the MV row alone would be the same data-snooping
  the gauntlet exists to prevent.
- **The diagnostic is committed, not hedged.** §4.3 picks one row
  and defends it. "It could be either row 1 or row 2" is not
  acceptable as a final answer; if the data won't disambiguate, the
  writeup waits for data that will.
- **Direct cost numbers, no rounding for narrative.** Bootstrap CIs
  reported as actual computed bounds, not "approximately positive."

---

## 5. The diagnostic question (§4 of the writeup)

The two live candidates from the failure-path matrix:

| Row | Diagnosis | Tier 2 pivot |
|---|---|---|
| 1 | Raw IC > 0 but residualized IC ≈ 0 → beta/style was the whole story | WRONG SIGNAL CLASS — event-driven, microstructure, alt-data |
| 2 | IC > 0 raw + residualized but net Sharpe ≤ 0 → real signal eaten by costs | EXECUTION PROBLEM — lower turnover, futures/FX |

**The disambiguating test:** the scheduled raw-returns rerun
(routine `trig_01NBbXAGa6bho6xy9hDuJy7B`, fires 2026-05-15).

- If MV-on-raw shows OOS Sharpe ≥ +1.5 in **both** windows: row 2
  applies. The signal exists; the cost model and / or universe
  liquidity is what kills it. Tier 2 = lower-turnover construction,
  larger universe, or asset class with asymmetric impact.
- If MV-on-raw shows OOS Sharpe < +1 in **either** window: row 1
  applies. The +2.8 residualized result was a residualization
  artifact (mis-specified FF5+UMD replica → systematic bias picked
  up by shorting all factors). Tier 2 = different signal class
  entirely (event-driven, microstructure, alt-data).
- If MV-on-raw lands in the gap [+1, +1.5] in either window: the
  test failed to disambiguate. Run a 3-month forward paper-trade of
  the MV signal as the second falsifier; do not commit to a row
  until the paper-trade lands.

The thresholds 1.5 and 1.0 are pre-committed here, before the
raw-rerun runs.

---

## 6. What goes in the Tier 2 sub-plan (§7 of the writeup)

One page. Not a full plan — that's its own memo, drafted *after*
Phase 6 ships. The §7 page commits to:

- Which row of the failure-path matrix applies (from §4.3).
- What the binary Tier 2 gate looks like (the analog of "DSR > 0.95
  in two OOS windows" for the new signal class).
- Approximate timeline (months, not weeks) and budget (hours/wk).
- Explicit "not-doing" list for Tier 2, mirroring Tier 1 §
  "explicit not-doing list."
- What gets re-used from the Tier 1 stack vs. what gets rebuilt.

The point is to commit publicly enough that future-self can hold
present-self accountable.

---

## 7. Implementation plan

- **Session 1 (this memo)** — DONE.
- **Session 2 (now → 2026-05-14):** draft sections 0-3, 5, 6 of
  `PHASE6_WRITEUP.md`. ~12 hours over the next 2 weeks. All sections
  reference existing JSON / markdown artifacts; no new computation.
- **Session 3 (2026-05-15):** raw-returns rerun lands. Read PR
  description and the regenerated `phase4_gate_result.md`.
- **Session 4 (2026-05-16 → 2026-05-22):** fill in §4 of the
  writeup. Commit to the diagnostic row. Draft §7 Tier 2 page.
- **Session 5:** final pass for tone and accuracy. Push to a public
  artifact (personal site or repo top level). The publication step
  IS the deliverable.

**Total Phase 6 budget:** 25-30 hours over ~3 weeks. The Tier 1
plan budgeted 150 hours / 13 weeks for Phase 6 — this is much
shorter because most of the analysis already exists, and the Tier 2
sub-plan proper is a separate memo not part of Phase 6.

---

## 8. What this memo does not cover

- The Tier 2 sub-plan itself. That's a downstream memo, drafted
  after the diagnostic is committed.
- New experiments, new factors, new universes. The not-doing list
  from Tier 1 §"explicit not-doing list" carries forward.
- Restarting live execution. The `.halt` stays on per the original
  re-launch conditions.
- Any sales / LP material. There are no LPs.
