#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# AlphaForge — Daily Paper Trading Runner
#
# Runs end-to-end once per trading day:
#   1. Checks for .halt file
#   2. Checks NYSE calendar
#   3. Syncs local parquet market data (yfinance → data/market/)
#   4. Runs momentum strategy  → live_trading.db
#   5. Runs MARL strategy      → live_marl.db
#   6. Logs alerts to alerts.log
#
# Cron (single entry — do NOT schedule two parallel runs):
#   30 20 * * 1-5 /path/to/alphaforge-execution/run_daily.sh
# ──────────────────────────────────────────────────────────────

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PY_DIR="$(cd "$SCRIPT_DIR/../alphaforge-python" && pwd)"
HALT_FILE=".halt"
ALERT_LOG="alerts.log"
VENV=".venv"
LOG_FILE="live_$(date '+%Y-%m-%d').log"

timestamp() { date '+%Y-%m-%dT%H:%M:%S'; }
alert() { echo "$(timestamp) [$1] $2" >> "$ALERT_LOG"; }

if [ -d "$VENV" ]; then
    # shellcheck disable=SC1091
    source "$VENV/bin/activate"
fi

if [ -f "$HALT_FILE" ]; then
    alert "HALTED" "Trading halted: $(cat "$HALT_FILE")"
    exit 0
fi

if ! python3 -c "from market_calendar import is_market_day; exit(0 if is_market_day() else 1)" 2>/dev/null; then
    alert "SKIP" "Not a market day (weekend or NYSE holiday)"
    exit 0
fi

alert "START" "Daily run begin"

# Refresh parquet market-data store before any strategy executes.
# Without this, validate_history() trips on stale data.
# Incremental: only fetch the last ~60 days and merge (avoids yfinance
# rate-limit errors on the full 2010-present pull). Retry once on failure.
SYNC_START="$(python3 -c 'from datetime import date, timedelta; print((date.today() - timedelta(days=60)).isoformat())')"
sync_data() {
    (
        cd "$PY_DIR"
        python3 sync_market_data.py --start-date "$SYNC_START" >> "$SCRIPT_DIR/$LOG_FILE" 2>&1
    )
}
if ! sync_data; then
    sleep 15
    if ! sync_data; then
        alert "SYNC_ERROR" "sync_market_data.py failed twice — proceeding anyway"
    fi
fi

run_strategy() {
    local name="$1"
    local db="$2"
    local extra="$3"
    echo "" >> "$LOG_FILE"
    echo "===== $name → $db =====" >> "$LOG_FILE"
    # shellcheck disable=SC2086
    if python3 run_live.py --db "$db" $extra >> "$LOG_FILE" 2>&1; then
        alert "OK" "$name completed"
        return 0
    else
        local rc=$?
        alert "ERROR" "$name exited $rc"
        tail -5 "$LOG_FILE" | sed 's/^/    /' >> "$ALERT_LOG"
        return $rc
    fi
}

run_strategy "momentum" "live_trading.db" "--strategy momentum"
MOM_EXIT=$?

run_strategy "marl" "live_marl.db" "--strategy marl"
MARL_EXIT=$?

if [ $MOM_EXIT -eq 0 ] && [ $MARL_EXIT -eq 0 ]; then
    alert "DONE" "Both strategies completed"
    exit 0
fi
exit 1
