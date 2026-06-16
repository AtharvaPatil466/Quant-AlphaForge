# FORWARD_RUN — substrate #10 Phase 2 paper-trader, running forward (macOS / launchd)

This is the operations runbook for accumulating the substrate #10 (Kalshi
favorite-longshot bias) **forward paper-trade record** on macOS. It schedules
`research/paper_trader.py` to run periodically over wall-clock so a live,
resolved-event record builds up under `data/paper/`.

> **READ-ONLY PAPER SIM.** No money. No auth. No live orders are ever sent. The
> harness fetches *open* Kalshi markets over the public read-only REST API,
> journals *intended* paper entries, and later settles them against the markets'
> public resolution. Network access is confined to `ingest/kalshi_client.py`.
> See `research/PREDICTION_MARKETS_DESIGN.md` §9 for the Phase 2 contract.

---

## 1. What it does

Two periodic commands, both wrapped by `scripts/run_paper_trader.sh`:

| Command | Cadence | What it does |
|---|---|---|
| `place` | **3×/day** — 09:00, 15:00, 21:00 local | Fetch currently-open markets → select orders matching the frozen rule → append *new* intended entries to the append-only journal (`data/paper/journal.jsonl`). Skips tickers already journalled. |
| `reconcile` | **1×/day** — 23:30 local | For each open journal entry, fetch its (now possibly resolved) market; if resolved, compute net-of-fee P&L (§6 fee + the doubled-fee G4 stress) and append a settlement record. Then rebuild the scorecard. |

Both passes are **resume-safe and idempotent**: the journal is append-only and
keyed by ticker, so `place` never double-journals an open contract and
`reconcile` never double-counts a resolution. Re-running is always safe.

Each scheduled invocation goes through `scripts/run_paper_trader.sh`, which:

- `cd`s to the sub-project root (resolved from the script's own path),
- uses the full `python3.13` interpreter
  (`/Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13` — Homebrew
  3.14 has broken `pyexpat`),
- runs `python3.13 -m research.paper_trader --output-root data <forward-flags> <cmd>`
  where `<forward-flags>` are the diagnosed forward config (see "Forward config" below),
- appends a framed, timestamped block of stdout+stderr to
  `data/paper/logs/<cmd>-YYYYMMDD.log`,
- holds an atomic `mkdir(2)` lock (`data/paper/.<cmd>.lock`) so overlapping runs
  of the same command cannot collide (stale locks > 1h are auto-cleared),
- exits nonzero on failure.

### Forward config (diagnosed 2026-06-17)

The wrapper now passes the flags that make forward accumulation actually work on
the free read-only host. **Why they are required** (probe: `research/probe_open_universe.py`):

| Flag | Applies to | Why |
|---|---|---|
| `--source events` | `place` | The unfiltered `/markets?status=open` feed is **100% MVE parlay legs** (8,000 markets paged, 0 non-MVE). The non-MVE classic-FLB universe is ONLY reachable via the `/events?with_nested_markets` feed (carries `category` + nested open markets). Without this, `place` journals nothing. |
| `--rule-spec research/forward_rule.json` | both | The frozen `DEFAULT_RULE_SPEC` lists `weather`/`climate` as separate categories, but Kalshi's actual category string is the single **"Climate and Weather"** → the literal default matches no weather markets. `forward_rule.json` corrects the category set to Kalshi's real non-MVE strings (and still EXCLUDES `exotics`/MVE per design §16). **Bucket bands are unchanged** (≤15c fade, ≥85c back — frozen by §4/§5). PROVISIONAL — not a Phase 1 survivor rule. |
| `--max-pages 1` | `place` | Caps each sweep. One page (~1,100 non-MVE markets) already journals ~660 eligible extremes; deeper pages add more but inflate the open backlog. `reconcile` ignores it. |

`reconcile` ignores `--source`/`--max-pages` (it fetches each journalled ticker by
ticker) but is still passed `--rule-spec` so the scorecard's recorded rule is
consistent across commands.

> **Provisional notice.** `provisional-FLB-forward-v1-nonMVE` is a *hypothesis-derived*
> rule, NOT a Phase 1 survivor rule (Phase 1 was INCONCLUSIVE / MVE-only —
> `research/PHASE1_VERDICT.md`). The scorecard is correctly marked PROVISIONAL.
> Re-freeze to the survivor cell once the forward record or a richer-data Phase 1
> confirms one. Edit the flag arrays in `scripts/run_paper_trader.sh` to change config.

---

## 2. Files

```
scripts/run_paper_trader.sh                                   # robust wrapper (place|reconcile)
scripts/com.alphaforge.prediction.papertrader.place.plist    # launchd agent — place 3x/day
scripts/com.alphaforge.prediction.papertrader.reconcile.plist# launchd agent — reconcile 1x/day
research/FORWARD_RUN.md                                       # this runbook
```

Outputs (created/updated by the runs; bulk is gitignored):

```
data/paper/journal.jsonl              # append-only entries + settlements
data/paper/paper_scorecard.md         # human-readable live scorecard
data/paper/paper_scorecard.json       # machine-readable scorecard
data/paper/logs/place-YYYYMMDD.log    # framed wrapper log (one file/day/cmd)
data/paper/logs/reconcile-YYYYMMDD.log
data/paper/logs/launchd-place.out.log / .err.log       # launchd's raw capture
data/paper/logs/launchd-reconcile.out.log / .err.log
```

---

## 3. Install (one time)

The two launchd plists must live in `~/Library/LaunchAgents/` and be loaded into
the per-user GUI domain. Copy them, then load.

```bash
# 1. Copy the plists into the LaunchAgents directory.
cp "/Users/atharva/Quant Projects/Quant Alpha/alphaforge-prediction/scripts/com.alphaforge.prediction.papertrader.place.plist" \
   ~/Library/LaunchAgents/
cp "/Users/atharva/Quant Projects/Quant Alpha/alphaforge-prediction/scripts/com.alphaforge.prediction.papertrader.reconcile.plist" \
   ~/Library/LaunchAgents/

# 2a. Load them (modern launchctl, macOS 11+):
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.alphaforge.prediction.papertrader.place.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.alphaforge.prediction.papertrader.reconcile.plist

# 2b. ...OR the legacy equivalent (also works):
# launchctl load -w ~/Library/LaunchAgents/com.alphaforge.prediction.papertrader.place.plist
# launchctl load -w ~/Library/LaunchAgents/com.alphaforge.prediction.papertrader.reconcile.plist
```

If `bootstrap` reports `Bootstrap failed: 5: Input/output error`, the agent is
usually already loaded — `bootout` first (see §6) then re-`bootstrap`, or just
use `load -w`.

---

## 4. Check status

```bash
# Are both agents registered? (PID column is '-' when idle between fires.)
launchctl list | grep alphaforge

# Detailed state of one agent (last exit code, schedule, etc.):
launchctl print gui/$(id -u)/com.alphaforge.prediction.papertrader.place

# Fire a run NOW without waiting for the schedule (useful to smoke-test):
launchctl kickstart -k gui/$(id -u)/com.alphaforge.prediction.papertrader.place
launchctl kickstart -k gui/$(id -u)/com.alphaforge.prediction.papertrader.reconcile
```

A registered agent shows a line like:
```
-	0	com.alphaforge.prediction.papertrader.place
```
(columns: PID, last-exit-status, Label). `-` PID + `0` status = loaded, idle,
last run clean.

---

## 5. Read the logs and the scorecard

```bash
cd "/Users/atharva/Quant Projects/Quant Alpha/alphaforge-prediction"

# Tail today's wrapper logs:
tail -f data/paper/logs/place-$(date +%Y%m%d).log
tail -f data/paper/logs/reconcile-$(date +%Y%m%d).log

# launchd's own capture (rare — only if the wrapper itself can't write):
tail -f data/paper/logs/launchd-place.err.log

# The live scorecard (counts, net-of-fee P&L, calibration, FLB-region edge CIs,
# and the §9 success check):
cat data/paper/paper_scorecard.md

# The raw journal (one JSON object per line; kind='entry' | 'settle'):
wc -l data/paper/journal.jsonl
tail -5 data/paper/journal.jsonl
```

The scorecard header reads **ACCUMULATING** until the §9 success conditions are
met (N resolved ≥ target, edge CI excludes zero in the FLB direction,
calibration beats market, net P&L > 0), then flips to **SUCCESS**. The
pre-committed resolved-event target is 200 (see `DEFAULT_TARGET_RESOLVED`).

---

## 6. Stop / unload

```bash
# Modern launchctl:
launchctl bootout gui/$(id -u)/com.alphaforge.prediction.papertrader.place
launchctl bootout gui/$(id -u)/com.alphaforge.prediction.papertrader.reconcile

# ...OR legacy:
# launchctl unload -w ~/Library/LaunchAgents/com.alphaforge.prediction.papertrader.place.plist
# launchctl unload -w ~/Library/LaunchAgents/com.alphaforge.prediction.papertrader.reconcile.plist

# To remove entirely, also delete the copies in LaunchAgents:
rm ~/Library/LaunchAgents/com.alphaforge.prediction.papertrader.place.plist
rm ~/Library/LaunchAgents/com.alphaforge.prediction.papertrader.reconcile.plist
```

---

## 7. Change the cadence

Edit the `StartCalendarInterval` block in the relevant plist
(`scripts/com.alphaforge.prediction.papertrader.{place,reconcile}.plist`), then
reinstall the changed plist:

```bash
launchctl bootout gui/$(id -u)/com.alphaforge.prediction.papertrader.place   # unload old
cp "/Users/atharva/Quant Projects/Quant Alpha/alphaforge-prediction/scripts/com.alphaforge.prediction.papertrader.place.plist" \
   ~/Library/LaunchAgents/                                                    # copy new
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.alphaforge.prediction.papertrader.place.plist  # load new
```

`StartCalendarInterval` is an array of `{Hour, Minute}` dicts (a single dict for
one fire/day). Omit a key to mean "every": e.g. only `Minute=0` fires at the top
of every hour. launchd does **not** stack missed runs — if the machine was
asleep at a fire time, the agent runs **once** at next wake, not N times.

---

## 8. Manual run (no launchd)

The wrapper is standalone — you can drive the forward record by hand at any time:

```bash
cd "/Users/atharva/Quant Projects/Quant Alpha/alphaforge-prediction"
./scripts/run_paper_trader.sh place
./scripts/run_paper_trader.sh reconcile
```

Or call the harness directly (bypassing the wrapper's logging/locking):

```bash
python3.13 -m research.paper_trader --output-root data place
python3.13 -m research.paper_trader --output-root data reconcile
python3.13 -m research.paper_trader --output-root data scorecard   # rebuild scorecard only
```
