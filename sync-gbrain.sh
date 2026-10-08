#!/usr/bin/env bash
set -uo pipefail
LOGDIR="/mnt/c/mybizz/logs/gbrain-logs"
mkdir -p "$LOGDIR"
TIMESTAMP=$(date +%Y-%m-%dT%H-%M-%S)
LOGFILE="$LOGDIR/sync-$TIMESTAMP.log"
exec > >(tee -a "$LOGFILE") 2>&1

echo "=== gbrain sync start: $TIMESTAMP ==="

# GBrain runs on PostgreSQL (multi-writer) since the PGLite migration.
# No stop/restart step is needed — PGLite's single-writer lock, which
# this used to work around, no longer applies.

# Bare `gbrain sync` syncs only ONE source: it follows the launch
# directory's git root (found live 2026-09-28 — launched from inside
# mybizz-os-docs, the other 16 sources were silently skipped).
# Enumerate every registered source and sync each explicitly, so new
# sources are covered automatically when they are registered.
echo "[1/3] Enumerating registered sources..."
SOURCES=$(gbrain sources list --json | jq -r '.sources[].id')
if [ -z "$SOURCES" ]; then
  echo "ERROR: could not enumerate sources (jq missing or 'gbrain sources list' failed)" >&2
  exit 1
fi
echo "      $(echo "$SOURCES" | wc -l) source(s) found"

# --no-pull (added 2026-09-30): the repositories are edited and committed only in WSL,
# so there is nothing to pull. Without it, one network hiccup (e.g. "Could not resolve host")
# stops a sync of local files. The one repository that follows an upstream project,
# anvil-agent-references (source anvil-agent-references-code), is updated by hand:
#   git -C /mnt/c/mybizz/anvil-agent-references pull
# The memory governor changes GBrain's default source with every governed write. A default naming a
# source that no longer exists stops every sync, so it is reset here. Safe: every sync below and every
# governed write names its own source.
gbrain sources default default >/dev/null 2>&1 || echo "WARNING: could not reset the GBrain default source"

echo "[2/3] Syncing each source..."
FAILED=0
for SRC in $SOURCES; do
  echo "--- source: $SRC ---"
  if ! gbrain sync --source "$SRC" --no-pull --exclude 'obsolete/**' --exclude '**/obsolete/**'; then
    echo "ERROR: sync failed for source: $SRC" >&2
    FAILED=$((FAILED + 1))
  fi
done

# Collect links across sources. A plain sync does not write links from one
# repository to another (added 2026-09-30, after the upgrade to 0.59.18.0).
echo "[2b/3] Collecting links: gbrain extract links --source db (reads every page, so links between repositories are found)..."
if ! gbrain extract links --source db; then
  echo "ERROR: gbrain extract links --source db failed" >&2
  FAILED=$((FAILED + 1))
fi

# Embed any unembedded content
echo "[3/3] Running gbrain embed --stale..."
if ! gbrain embed --stale; then
  echo "ERROR: gbrain embed --stale failed" >&2
  FAILED=$((FAILED + 1))
fi

if [ "$FAILED" -gt 0 ]; then
  echo "=== gbrain sync complete WITH $FAILED FAILURE(S): $(date +%Y-%m-%dT%H-%M-%S) ===" >&2
  exit 1
fi

echo "=== gbrain sync complete: $(date +%Y-%m-%dT%H-%M-%S) ==="
