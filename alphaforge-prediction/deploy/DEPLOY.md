# Phase 2 paper-trader VPS deployment

Why: the forward paper run is the substrate's primary path (design §11 — Phase 1
was underpowered on the free host, so the evidence has to accumulate forward over
wall-clock). The laptop decommission on 2026-07-27 `bootout`'d all three launchd
agents; the scorecard has been frozen since the last manual reconcile on
**2026-08-13** at **123 / 200 resolved**. It only advances again with a 24/7 host.

Unlike the microstructure collector this is a **periodic batch job**, not a
daemon: `place` 3x/day, `reconcile` 1x/day, `digest` weekly. So there is no
`restart: always` service — host cron drives `docker compose run --rm`.

## Critical pre-check: carry the journal across

`alphaforge-prediction/.gitignore` ignores `data/` wholesale, so **a git clone
brings none of the accumulated record.** `data/paper/journal.jsonl` (687 entries,
123 settlements) *is* the substrate's evidence — it cannot be regenerated, because
the free Kalshi host does not serve deep settled history (design §16 ADDENDUM).

Copy it explicitly, and verify the count on the far side before starting cron:

    rsync -a alphaforge-prediction/data/paper/ vps:~/alphaforge/alphaforge-prediction/data/paper/

    # on the VPS — must print 694 entries / 123 settles before you install cron
    python3 -c "import json,collections;print(collections.Counter(json.loads(l)['kind'] for l in open('data/paper/journal.jsonl')))"

If that count is wrong, stop. Starting `place` against an empty journal begins a
new accumulation from zero and silently abandons 61.5% of the target.

## Steps

1. Provision Ubuntu VPS (Hetzner CX22 class is ample — this is 4 API sweeps/day),
   install Docker + compose plugin.

2. Copy both sub-projects — the image build needs the sibling gauntlet package:

       rsync -a --exclude data --exclude .venv --exclude __pycache__ \
           alphaforge-prediction/ vps:~/alphaforge/alphaforge-prediction/
       rsync -a --exclude .venv --exclude __pycache__ \
           alphaforge-gauntlet/ vps:~/alphaforge/alphaforge-gauntlet/

3. Carry the journal across and verify it (see pre-check above).

4. Set the host timezone to match the original cadence, or the 09/15/21 sweeps
   drift relative to the run they are continuing:

       sudo timedatectl set-timezone Asia/Kolkata

5. Build and smoke-test one reconcile. This is read-only (no auth, no orders) and
   idempotent, so it is safe to run ad hoc:

       cd ~/alphaforge/alphaforge-prediction/deploy
       docker compose build
       docker compose run --rm papertrader reconcile

   Expect ~7 new settlements — of the 571 open entries only that many have a
   `close_time` in the past; the rest are long-dated (139 close 2029-01, 78 in
   2045-01). **This is why `place` must run too:** reconcile alone takes the
   count to ~130 and then flatlines. The remaining ~70 resolutions have to come
   from newly placed short-dated contracts.

6. Install cron (edit `DEPLOY_DIR` in the file first):

       crontab deploy/crontab
       crontab -l          # verify

7. Confirm the next scheduled `place` actually fired:

       tail -40 ~/alphaforge/alphaforge-prediction/data/paper/logs/place-$(date +%Y%m%d).log

## Back out

`crontab -r` stops accumulation; the journal is append-only and fsync'd, so a
mid-run kill loses at most the in-flight sweep. To return to the laptop, the
launchd plists are preserved in `ops/launchagents-disabled/`.

## What this does NOT do

It does not re-open the Phase 1 rule question. The forward run continues under
`research/forward_rule.json` (`provisional-FLB-v0`), which is a PROVISIONAL rule,
not a Phase 1 survivor cell. Changing the rule — including narrowing the fade
band away from the 1c-median junk it is currently filling with — resets the
resolved count, so it is a decision to make *before* re-hosting, not after.
