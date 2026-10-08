#!/usr/bin/env bash
# GBrain upgrade, block 1: record the state, stop the services, back everything up.
# It changes nothing in GBrain except cancelling waiting jobs. It stops with a message if anything is wrong.
set -uo pipefail
cd /tmp
B="$HOME/backups"
GB=/home/dev-p/gbrain
fail() { echo; echo "STOP: $*"; exit 1; }
mkdir -p "$B"
rm -f "$B/.stage1-ok"

echo "== 1. record the current state"
git -C "$GB" rev-parse HEAD | tee "$B/rollback-commit.txt"
echo "branch: $(git -C "$GB" branch --show-current)"
git -C "$GB" branch pre-upgrade-backup HEAD 2>/dev/null || echo "(backup branch already exists)"
[ -z "$(git -C "$GB" status --short)" ] || fail "the GBrain checkout has uncommitted changes"

echo "== 2. OpenCode and the GBrain server must not be running"
if ps aux | grep -E 'opencode|gbrain serve' | grep -v grep >/dev/null; then
  ps aux | grep -E 'opencode|gbrain serve' | grep -v grep | cut -c1-120
  fail "OpenCode or gbrain serve is still running. Close it, then run this script again."
fi

echo "== 3. cancel the waiting GBrain jobs"
n=0
for id in $(gbrain jobs list --status waiting --limit 500 2>/dev/null | awk '$1 ~ /^[0-9]+$/ && $3 == "waiting" {print $1}'); do
  if gbrain jobs cancel "$id" >/dev/null 2>&1; then n=$((n+1)); else echo "could not cancel job $id"; fi
done
echo "cancelled $n job(s)"
gbrain jobs stats 2>/dev/null | grep -E "Queue health" || true

echo "== 4. stop the memory governor (API first, then the worker)"
systemctl --user stop memory-governor-api || fail "could not stop the governor API"
echo "waiting 60 seconds so the worker can deliver what is already promoted"
sleep 60
systemctl --user stop memory-governor-worker || fail "could not stop the governor worker"
for u in memory-governor-api memory-governor-worker; do echo "$u: $(systemctl --user is-active $u)"; done
if ps aux | grep -E 'uvicorn app.main|app\.worker|gbrain' | grep -v grep >/dev/null; then
  ps aux | grep -E 'uvicorn app.main|app\.worker|gbrain' | grep -v grep | cut -c1-140
  fail "a process that uses GBrain is still running (listed above)"
fi

echo "== 5. back up every database and the GBrain settings folder (the sudo password may be asked)"
sudo -v || fail "sudo did not work"
DBS=$(sudo -u postgres psql -Atc "select datname from pg_database where not datistemplate and datname <> 'postgres'") || fail "could not list the databases"
[ -n "$DBS" ] || fail "no databases found"
echo "databases: $(echo $DBS)"
for db in $DBS; do
  echo "dumping $db"
  sudo -u postgres pg_dump -Fc "$db" > "$B/db-$db-before-upgrade.dump" || fail "pg_dump failed for $db"
done
tar czf "$B/dot-gbrain-before-upgrade.tgz" -C "$HOME" .gbrain || fail "could not archive ~/.gbrain"
chmod 600 "$B"/db-*-before-upgrade.dump "$B/dot-gbrain-before-upgrade.tgz"

echo "== 6. verify the backups"
for f in "$B"/db-*-before-upgrade.dump "$B/dot-gbrain-before-upgrade.tgz"; do
  [ -s "$f" ] || fail "$f is empty"
done
for f in "$B"/db-*-before-upgrade.dump; do
  if pg_restore -l "$f" >/dev/null 2>&1; then echo "readable: $f"; else fail "$f is not a readable dump"; fi
done
tar tzf "$B/dot-gbrain-before-upgrade.tgz" >/dev/null 2>&1 || fail "the settings archive is not readable"
ls -l "$B"/db-*-before-upgrade.dump "$B/dot-gbrain-before-upgrade.tgz"
touch "$B/.stage1-ok"
echo
echo "BLOCK 1 COMPLETE. Do not restart anything. Paste this whole output to Claude."
