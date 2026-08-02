# Collector VPS deployment

Why: the laptop is not a viable 24/7 collection host — machine sleep produced
multi-hour book gaps nightly throughout the Phase 0 window (~14% of hour-buckets
missing as of 2026-07-19, vs a <0.1% gap budget). A $10-20/mo VPS with
`restart: always` is the durable fix.

## Critical pre-check: region gating

The trade tape is REST-polled because the current host's IP is region-gated for
the `btcusdt@aggTrade` WebSocket stream (see ../COLLECTOR_NOTES.md). A VPS IP
may be gated differently — in either direction. **Before committing to a
provider/region, run the probe from the VPS:**

    python3 -m validation.feed_probe

- If WS `aggTrade` delivers frames on the VPS, the native stream is preferred
  over REST polling (fidelity upgrade) — but switching trade source mid-window
  is a data-provenance change; document it in COLLECTOR_NOTES.md first.
- If `fapi.binance.com` REST itself is blocked from the VPS region, pick a
  different region. Binance blocks US-based IPs from futures endpoints —
  avoid US regions.

## Steps

1. Provision Ubuntu VPS (Hetzner CX22 / EC2 t3.small class), install Docker.
2. Copy the sub-project (excluding accumulated data):

       rsync -a --exclude data --exclude logs --exclude .venv \
           alphaforge-microstructure/ vps:~/alphaforge-microstructure/

3. Run the region probe (above). Decide trade source.
4. Start:

       cd ~/alphaforge-microstructure
       docker compose -f deploy/docker-compose.yml up -d --build
       docker compose -f deploy/docker-compose.yml ps   # wait for "healthy"

5. Point monitoring at it: install a cron entry on the VPS mirroring
   ops/collector_watchdog.sh (health_check + healthchecks.io ping). Reuse the
   same healthchecks.io check UUID so the dead-man alert follows the collector.
6. Only after the VPS collector shows OK health for 24h: stop the laptop agent

       launchctl bootout gui/$(id -u)/com.alphaforge.microstructure

   and record the cutover timestamp in COLLECTOR_NOTES.md — the gap detector
   needs it to attribute the handover seam.
7. Back up the VPS data nightly (rclone to object storage, or rsync back to
   the laptop where ops/backup_critical_data.sh picks it up).

## Restart-clock decision (user call, not ops)

Whether the accumulation clock restarts at cutover is a Phase 0 governance
question — a host change mid-window mixes two collection environments. The
conservative read of the design contract is: restart the 30-day clock on the
VPS. Decide explicitly and file it in research/ before Phase 1 consumes the
data.
