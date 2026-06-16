#!/bin/bash
#
# run_paper_trader.sh — robust wrapper that runs substrate #10's Phase 2 paper
# trader (research.paper_trader) FORWARD over wall-clock for launchd.
#
# Usage:  run_paper_trader.sh place
#         run_paper_trader.sh reconcile
#
# It is a READ-ONLY paper sim: no money, no auth, no orders. It journals intended
# entries (place) and settles resolved entries + rebuilds the scorecard (reconcile)
# under data/paper/. The underlying harness is resume-safe and idempotent.
#
# Behaviour:
#   - cd to the sub-project root, resolved from this script's own location
#     (NOT a hardcoded cwd) so launchd's WorkingDirectory cannot misroute it.
#   - uses the FULL python3.13 path (Homebrew 3.14 has broken pyexpat).
#   - appends timestamped stdout/stderr to data/paper/logs/<cmd>-YYYYMMDD.log.
#   - takes an atomic mkdir(2) lock so an overlapping run of the same command
#     cannot collide (the journal is append-only + fsync'd, but two concurrent
#     --place passes would waste API calls and risk interleaved logs).
#   - exits nonzero on any failure.

set -euo pipefail

# ---------------------------------------------------------------------------
# Resolve paths from this script's own location (robust to symlinks / cwd).
# ---------------------------------------------------------------------------
SOURCE="${BASH_SOURCE[0]}"
while [ -h "$SOURCE" ]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" >/dev/null 2>&1 && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"
done
SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" >/dev/null 2>&1 && pwd)"
PROJECT_DIR="$(cd -P "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd)"

# Full python3.13 interpreter path (per task spec / CLAUDE.md).
PYTHON="/Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13"

# ---------------------------------------------------------------------------
# Validate argument.
# ---------------------------------------------------------------------------
CMD="${1:-}"
case "$CMD" in
  place|reconcile) ;;
  *)
    echo "usage: $(basename "$0") {place|reconcile}" >&2
    exit 2
    ;;
esac

cd "$PROJECT_DIR"

LOG_DIR="$PROJECT_DIR/data/paper/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/${CMD}-$(date +%Y%m%d).log"

# ---------------------------------------------------------------------------
# Atomic lock (mkdir is atomic on POSIX; no flock/shlock dependency).
# Stale-lock guard: if the lock is older than 1h, assume a crashed run and clear.
# ---------------------------------------------------------------------------
LOCK_DIR="$PROJECT_DIR/data/paper/.${CMD}.lock"

if [ -d "$LOCK_DIR" ]; then
  # macOS stat: -f %m gives mtime epoch seconds.
  if lock_mtime=$(/usr/bin/stat -f %m "$LOCK_DIR" 2>/dev/null); then
    now=$(date +%s)
    age=$(( now - lock_mtime ))
    if [ "$age" -gt 3600 ]; then
      echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) WARN clearing stale ${CMD} lock (age ${age}s)" >> "$LOG_FILE"
      rmdir "$LOCK_DIR" 2>/dev/null || true
    fi
  fi
fi

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) SKIP ${CMD} already running (lock held: $LOCK_DIR)" >> "$LOG_FILE"
  exit 0
fi

# Always release the lock on exit, regardless of success/failure.
cleanup() { rmdir "$LOCK_DIR" 2>/dev/null || true; }
trap cleanup EXIT

# ---------------------------------------------------------------------------
# Run, appending a framed, timestamped block to the daily log.
# ---------------------------------------------------------------------------
START_TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
{
  echo "============================================================"
  echo "[$START_TS] BEGIN ${CMD}  (host=$(hostname -s) pid=$$)"
  echo "  project: $PROJECT_DIR"
  echo "  python : $PYTHON"
} >> "$LOG_FILE"

rc=0
# Forward-config flags (diagnosed 2026-06-17; see research/FORWARD_RUN.md). The
# free host's unfiltered /markets?status=open feed is 100% MVE parlay legs (probe:
# 8,000 markets, 0 non-MVE), so --source events is REQUIRED for `place` to reach
# the non-MVE classic-FLB universe; --rule-spec research/forward_rule.json corrects
# the category set (the frozen DEFAULT lists 'weather'/'climate' separately but
# Kalshi uses the single 'Climate and Weather'); --max-pages 1 caps each sweep.
# These are GLOBAL args (parsed before the subcommand) so they precede "$CMD".
# `reconcile` ignores source/max-pages (it fetches journalled tickers by ticker),
# but the rule keeps the scorecard's recorded rule consistent across commands.
if [ "$CMD" = "place" ]; then
  EXTRA_FLAGS=(--rule-spec research/forward_rule.json --source events --max-pages 1)
else
  EXTRA_FLAGS=(--rule-spec research/forward_rule.json)
fi

# Capture both streams into the log; preserve the harness exit code.
if "$PYTHON" -m research.paper_trader --output-root data "${EXTRA_FLAGS[@]}" "$CMD" >> "$LOG_FILE" 2>&1; then
  rc=0
else
  rc=$?
fi

END_TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "[$END_TS] END ${CMD}  exit=${rc}" >> "$LOG_FILE"

exit "$rc"
