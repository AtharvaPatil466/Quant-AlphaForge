#!/bin/sh
# Backs up the irreplaceable AlphaForge data that exists nowhere else:
#   - alphaforge-microstructure/data      Phase 0 L2 book + trade capture (live-only, unrecoverable)
#   - alphaforge-prediction/data          Kalshi forward paper-trade record (the substrate's evidence)
#   - alphaforge-python/data/market/pit/artifacts   PIT membership event log + baseline
#   - data/quarantine/market              OHLCV parquet store (re-downloadable in theory; slow + drifty)
#   - alphaforge-execution/*.db           order/snapshot/signal history (via sqlite3 .backup for consistency)
#
# Destination resolution (first match wins):
#   1. BACKUP_DEST from ops/backup.env or the environment
#      - "remote:path" with rclone installed -> rclone copy (true offsite)
#      - any other value                     -> rsync to that directory
#   2. iCloud Drive folder if present        -> offsite via Apple sync, zero setup
#   3. ~/AlphaForgeBackups                   -> SAME-DISK fallback; protects against
#                                              repo-level accidents only, NOT disk loss
#
# Copies are additive (rsync without --delete / rclone copy): a local deletion
# never propagates to the backup.
#
# Scheduled nightly at 02:30 by cron (see ops/backup_critical_data.cron).

set -eu

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT_DIR/ops/backup.env"
[ -f "$ENV_FILE" ] && . "$ENV_FILE"

ICLOUD_DIR="$HOME/Library/Mobile Documents/com~apple~CloudDocs"
if [ -n "${BACKUP_DEST:-}" ]; then
    DEST="$BACKUP_DEST"
elif [ -d "$ICLOUD_DIR" ]; then
    DEST="$ICLOUD_DIR/AlphaForgeBackups"
else
    DEST="$HOME/AlphaForgeBackups"
    echo "WARNING: same-disk fallback destination $DEST — configure ops/backup.env" >&2
fi

NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "[$NOW] backup starting -> $DEST"

# sqlite3 .backup produces a consistent snapshot even if a writer is active.
DB_STAGE="$(mktemp -d)"
trap 'rm -rf "$DB_STAGE"' EXIT
for db in "$ROOT_DIR"/alphaforge-execution/*.db; do
    [ -f "$db" ] || continue
    sqlite3 "$db" ".backup '$DB_STAGE/$(basename "$db")'"
done

copy() {
    src="$1"; sub="$2"
    [ -e "$src" ] || { echo "skip (missing): $src"; return 0; }
    case "$DEST" in
        *:*)
            rclone copy "$src" "$DEST/$sub" --transfers 4 ;;
        *)
            mkdir -p "$DEST/$sub"
            rsync -a "$src/" "$DEST/$sub/" ;;
    esac
    echo "done: $sub"
}

copy "$ROOT_DIR/alphaforge-microstructure/data"                 "microstructure-data"
copy "$ROOT_DIR/alphaforge-prediction/data"                     "prediction-data"
copy "$ROOT_DIR/alphaforge-python/data/market/pit/artifacts"    "pit-artifacts"
copy "$ROOT_DIR/data/quarantine/market"                         "quarantine-market"
copy "$DB_STAGE"                                                "execution-db"

END="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
case "$DEST" in
    *:*) printf '%s\n' "$END" | rclone rcat "$DEST/_last_backup.txt" ;;
    *)   printf '%s\n' "$END" > "$DEST/_last_backup.txt" ;;
esac
echo "[$END] backup complete"
