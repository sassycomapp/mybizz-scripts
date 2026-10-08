#!/bin/bash
# opencode-session-prune.sh
#
# Purpose: OpenCode has no built-in retention limit for session history —
# confirmed, ongoing upstream issue (anomalyco/opencode#22110): storage
# grows unbounded, full reasoning/tool-output kept forever for every
# session. This script prunes sessions older than RETENTION_DAYS.
#
# Unlike opencode-db-cleanup.sh (which is deliberately manual, since
# "stale" is judged by folder existence and could false-positive on a
# temporarily unmounted drive), age-based pruning is safe to run
# unattended on a schedule — the criterion is purely a timestamp, no
# false-positive risk.
#
# ALWAYS backs up the full database before deleting anything. Designed
# to be called from Windows Task Scheduler via WSL, e.g.:
#   wsl bash /mnt/c/mybizz/scripts/opencode-session-prune.sh

set -euo pipefail

DB="$HOME/.local/share/opencode/opencode.db"
BACKUP_ROOT="/mnt/c/backup-wsl/opencode-session-prune"
RETENTION_DAYS=60
TIMESTAMP=$(TZ="Africa/Johannesburg" date +%Y-%m-%dT%H%M%S%z)
BACKUP_DIR="$BACKUP_ROOT/$TIMESTAMP"
LOG_FILE="$BACKUP_DIR/prune-log.txt"

if [ ! -f "$DB" ]; then
  echo "ERROR: database not found at $DB" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"

# Keep 7 days of backups: older backup folders are deleted.
find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -mtime +7 -exec rm -rf {} +

{
  echo "=== opencode-session-prune.sh — $TIMESTAMP ==="
  echo "Retention: $RETENTION_DAYS days"
  echo "Database: $DB"
  echo ""

  # --- Step 1: Backup (always, before anything else) ---
  cp "$DB" "$BACKUP_DIR/opencode.db"
  [ -f "$DB-wal" ] && cp "$DB-wal" "$BACKUP_DIR/opencode.db-wal"
  [ -f "$DB-shm" ] && cp "$DB-shm" "$BACKUP_DIR/opencode.db-shm"
  echo "Backup written to: $BACKUP_DIR"
  echo ""

  # --- Step 2: Compute cutoff timestamp ---
  # session.time_updated is epoch milliseconds (confirmed from live data).
  CUTOFF_MS=$(( ($(date +%s) - RETENTION_DAYS * 86400) * 1000 ))
  echo "Cutoff: sessions with time_updated older than $CUTOFF_MS (epoch ms) will be pruned"
  echo ""

  # --- Step 3: Identify stale session IDs ---
  STALE_IDS_FILE=$(mktemp)
  sqlite3 "$DB" "SELECT id FROM session WHERE time_updated < $CUTOFF_MS;" > "$STALE_IDS_FILE"
  STALE_COUNT=$(wc -l < "$STALE_IDS_FILE")
  echo "Sessions to prune: $STALE_COUNT"

  if [ "$STALE_COUNT" -eq 0 ]; then
    echo "Nothing to prune. Exiting cleanly."
    rm -f "$STALE_IDS_FILE"
    exit 0
  fi

  # Build a comma-separated quoted ID list for use in SQL IN (...) clauses.
  ID_LIST=$(awk '{printf "%s%s", (NR>1?",":""), "\x27" $0 "\x27"}' "$STALE_IDS_FILE")

  # --- Step 4: Discover and clean up dependent tables dynamically ---
  # We don't hardcode message/part/session_message schema — instead we
  # ask sqlite which tables have a foreign key pointing at `session`,
  # and delete matching rows there first. Run two passes to also catch
  # tables that reference a first-level child table (grandchildren).
  TABLES=$(sqlite3 "$DB" ".tables" | tr -s ' ' '\n')

  for pass in 1 2; do
    for tbl in $TABLES; do
      [ "$tbl" = "session" ] && continue
      FK_INFO=$(sqlite3 "$DB" "PRAGMA foreign_key_list($tbl);" 2>/dev/null || true)
      echo "$FK_INFO" | grep -q "|session|" || continue
      COL=$(echo "$FK_INFO" | awk -F'|' '$3=="session"{print $4}' | head -1)
      [ -z "$COL" ] && continue
      DELETED=$(sqlite3 "$DB" "DELETE FROM $tbl WHERE $COL IN ($ID_LIST); SELECT changes();")
      [ "$DELETED" != "0" ] && echo "  Pass $pass: deleted $DELETED row(s) from $tbl"
    done
  done

  # --- Step 5: Delete the stale sessions themselves ---
  sqlite3 "$DB" "DELETE FROM session WHERE id IN ($ID_LIST);"
  echo "Deleted $STALE_COUNT session row(s) from session table."

  rm -f "$STALE_IDS_FILE"

  # --- Step 6: Reclaim disk space ---
  echo "Running VACUUM to reclaim disk space..."
  sqlite3 "$DB" "VACUUM;"

  echo ""
  echo "Done. $STALE_COUNT session(s) pruned. Backup: $BACKUP_DIR"
} | tee "$LOG_FILE"
