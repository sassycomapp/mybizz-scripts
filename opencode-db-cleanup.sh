#!/bin/bash
# opencode-db-cleanup.sh
#
# Purpose: remove stale `project` and `session` rows from OpenCode's
# opencode.db whose directory/worktree no longer exists on disk — e.g.
# after renaming a project folder (dev-pdlf -> dev-makepdlf, C:\projects
# -> C:\dev). This is a known, confirmed OpenCode gap (no built-in
# cleanup — see anomalyco/opencode#25004, #23248) — not something wrong
# with your setup.
#
# Run this ON DEMAND, right after a rename/move, or anytime you suspect
# stale entries. Not scheduled — deliberately manual, so a false
# positive (e.g. a temporarily-unmounted drive) can never silently
# delete real history.
#
# Always backs up the full database before touching anything, and
# always shows you exactly what it found before asking for confirmation.

set -euo pipefail

DB="$HOME/.local/share/opencode/opencode.db"
BACKUP_ROOT="/mnt/c/backup-wsl/opencode-db-cleanup"
TIMESTAMP=$(TZ="Africa/Johannesburg" date +%Y-%m-%dT%H%M%S%z)
BACKUP_DIR="$BACKUP_ROOT/$TIMESTAMP"

if [ ! -f "$DB" ]; then
  echo "ERROR: database not found at $DB"
  exit 1
fi

echo "=== opencode-db-cleanup.sh ==="
echo "Database: $DB"
echo ""

# --- Step 1: Backup (always, before anything else) ---
mkdir -p "$BACKUP_DIR"
cp "$DB" "$BACKUP_DIR/opencode.db"
[ -f "$DB-wal" ] && cp "$DB-wal" "$BACKUP_DIR/opencode.db-wal"
[ -f "$DB-shm" ] && cp "$DB-shm" "$BACKUP_DIR/opencode.db-shm"
echo "Backup written to: $BACKUP_DIR"
echo ""

# --- Step 2: Find stale project rows ---
echo "--- Stale project entries (folder no longer exists) ---"
STALE_PROJECT_IDS=()
while IFS='|' read -r id worktree; do
  if [ "$worktree" != "/" ] && [ ! -d "$worktree" ]; then
    echo "  MISSING: $id -> $worktree"
    STALE_PROJECT_IDS+=("$id")
  fi
done < <(sqlite3 "$DB" "SELECT id, worktree FROM project;")

if [ ${#STALE_PROJECT_IDS[@]} -eq 0 ]; then
  echo "  (none found)"
fi
echo ""

# --- Step 3: Find stale session rows ---
echo "--- Stale session entries (directory no longer exists) ---"
STALE_SESSION_COUNT=0
STALE_DIRS_TMP=$(mktemp)
sqlite3 "$DB" "SELECT DISTINCT directory FROM session WHERE directory IS NOT NULL;" > "$STALE_DIRS_TMP"
STALE_DIR_LIST=()
while IFS= read -r dir; do
  if [ -n "$dir" ] && [ ! -d "$dir" ]; then
    COUNT=$(sqlite3 "$DB" "SELECT COUNT(*) FROM session WHERE directory = '$dir';")
    echo "  MISSING: $dir ($COUNT session row(s))"
    STALE_SESSION_COUNT=$((STALE_SESSION_COUNT + COUNT))
    STALE_DIR_LIST+=("$dir")
  fi
done < "$STALE_DIRS_TMP"
rm -f "$STALE_DIRS_TMP"

if [ ${#STALE_DIR_LIST[@]} -eq 0 ]; then
  echo "  (none found)"
fi
echo ""

if [ ${#STALE_PROJECT_IDS[@]} -eq 0 ] && [ ${#STALE_DIR_LIST[@]} -eq 0 ]; then
  echo "Nothing stale found. Database is clean. No changes made."
  exit 0
fi

echo "Summary: ${#STALE_PROJECT_IDS[@]} stale project row(s), $STALE_SESSION_COUNT stale session row(s)."
echo ""
read -r -p "Type YES to delete these rows (backup already saved above): " CONFIRM

if [ "$CONFIRM" != "YES" ]; then
  echo "Aborted. No changes made. Backup remains at $BACKUP_DIR in case you need it later anyway."
  exit 0
fi

# --- Step 4: Delete ---
for id in "${STALE_PROJECT_IDS[@]}"; do
  sqlite3 "$DB" "DELETE FROM project WHERE id = '$id';"
done

for dir in "${STALE_DIR_LIST[@]}"; do
  sqlite3 "$DB" "DELETE FROM session WHERE directory = '$dir';"
done

echo ""
echo "Done. Deleted ${#STALE_PROJECT_IDS[@]} project row(s), $STALE_SESSION_COUNT session row(s)."
echo "Backup of pre-deletion state: $BACKUP_DIR"
