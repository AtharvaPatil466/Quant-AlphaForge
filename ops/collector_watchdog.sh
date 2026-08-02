#!/bin/sh
# Watchdog for the microstructure Phase 0 collector.
#
# Wraps collector/health_check.py (the existing liveness monitor) and adds:
#   1. A local log line every run  -> alphaforge-microstructure/logs/watchdog.log
#   2. A macOS notification on CRITICAL (so a failure is visible at the machine)
#   3. An optional healthchecks.io dead-man heartbeat: OK pings the check URL,
#      WARNING/CRITICAL pings <url>/fail. If this machine dies entirely, the
#      pings stop and healthchecks.io alerts on silence — that is the dead-man
#      property a purely local watchdog cannot provide.
#
# Configure the heartbeat by creating ops/watchdog.env (gitignored) with:
#   HEALTHCHECKS_URL="https://hc-ping.com/<your-check-uuid>"
# Sign up free at https://healthchecks.io, create a check with a 15-minute
# grace period, and paste its ping URL. Until then this script still logs
# locally and raises desktop notifications.
#
# Scheduled by ops/com.alphaforge.watchdog.plist (launchd, every 300s).

set -u

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MICRO_DIR="$ROOT_DIR/alphaforge-microstructure"
LOG_FILE="$MICRO_DIR/logs/watchdog.log"
ENV_FILE="$ROOT_DIR/ops/watchdog.env"

[ -f "$ENV_FILE" ] && . "$ENV_FILE"
HEALTHCHECKS_URL="${HEALTHCHECKS_URL:-}"

cd "$MICRO_DIR"
mkdir -p logs

JSON="$(.venv/bin/python -m collector.health_check --json 2>&1)"
RC=$?

case "$RC" in
    0) STATUS="OK" ;;
    1) STATUS="WARNING" ;;
    *) STATUS="CRITICAL" ;;
esac

NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "$NOW $STATUS rc=$RC" >> "$LOG_FILE"

if [ "$STATUS" = "CRITICAL" ]; then
    # Keep the full failing payload for forensics.
    echo "$JSON" >> "$LOG_FILE"
    /usr/bin/osascript -e 'display notification "Collector health CRITICAL — check watchdog.log" with title "AlphaForge watchdog"' 2>/dev/null || true
fi

if [ -n "$HEALTHCHECKS_URL" ]; then
    if [ "$RC" -eq 0 ]; then
        PING_URL="$HEALTHCHECKS_URL"
    else
        PING_URL="$HEALTHCHECKS_URL/fail"
    fi
    # Body shows up as "last ping" in the healthchecks.io UI; cap the size.
    printf '%s' "$JSON" | head -c 8000 | \
        curl -fsS -m 10 --retry 2 -o /dev/null --data-binary @- "$PING_URL" \
        || echo "$NOW ping failed: $PING_URL" >> "$LOG_FILE"
else
    [ "$RC" -ne 0 ] && echo "$NOW (no HEALTHCHECKS_URL configured — local alert only)" >> "$LOG_FILE"
fi

exit "$RC"
