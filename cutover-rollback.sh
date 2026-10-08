#!/usr/bin/env bash
# GBrain upgrade rollback: back to your old checkout and restore both databases from the block 1 backups.
# Run it only if a block tells you to. It needs --yes.
set -uo pipefail
cd /tmp
B="$HOME/backups"
GB=/home/dev-p/gbrain
fail() { echo; echo "STOP: $*"; exit 1; }
[ "${1:-}" = "--yes" ] || { echo "This restores the databases from $B and returns to your old GBrain code."; echo "Run: bash $0 --yes"; exit 1; }
if ps aux | grep -E 'opencode|gbrain|uvicorn app.main|app\.worker' | grep -v grep >/dev/null; then
  fail "a process that uses GBrain is running. Stop it first."
fi
ls "$B"/db-*-before-upgrade.dump >/dev/null 2>&1 || fail "no database backups found in $B"
echo "== 1. return to the old code"
git -C "$GB" checkout master || fail "could not check out master"
[ "$(git -C "$GB" rev-parse HEAD)" = "$(cat "$B/rollback-commit.txt")" ] || fail "master is not at the recorded commit. Use branch pre-upgrade-backup."
( cd "$GB" && bun install --ignore-scripts ) || fail "bun install failed"
echo "gbrain version: $(gbrain --version 2>/dev/null | grep -o '[0-9]*\.[0-9]*\.[0-9]*\.[0-9]*' | head -1) (must be 0.46.1.0)"
echo "== 2. restore the databases"
sudo -v || fail "sudo did not work"
for f in "$B"/db-*-before-upgrade.dump; do
  db=$(basename "$f" | sed 's/^db-//; s/-before-upgrade\.dump$//')
  echo "restoring $db"
  sudo -u postgres pg_restore --clean --if-exists -d "$db" < "$f" 2>&1 | tail -3
done
echo
echo "ROLLBACK COMPLETE. Start the governor with: systemctl --user start memory-governor-api memory-governor-worker"
echo "Then reopen OpenCode and run: gbrain doctor"
