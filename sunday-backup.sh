#!/usr/bin/env bash
# Sunday backup: PostgreSQL backup cycle (both instances), then the GBrain export.
# Run by the Task Scheduler task SundayBackup. Exit 0 = all done; exit 9 = a step failed (see the log).
set -uo pipefail
export PATH="$HOME/.bun/bin:$PATH"
D=$(date +%F)
WSLB=/home/dev-p/backup-gbrain; WINB=/mnt/c/backup-gbrain
LOGDIR=/mnt/c/mybizz/logs/sunday-backup; mkdir -p "$LOGDIR" "$WSLB" "$WINB"
LOG="$LOGDIR/sunday-backup-$D.log"
exec > >(tee -a "$LOG") 2>&1
FAIL=0
FAILS=""
step() { echo; echo "== $1"; }
fail() { echo "   FAILED: $1"; FAIL=1; FAILS="$FAILS - $1\r\n"; }
PGW='C:\Program Files\PostgreSQL\15\bin\pg_dump.exe'
URL=$(python3 -c 'import json,os;print(json.load(open(os.path.expanduser("~/.gbrain/config.json")))["database_url"])')
BASE=${URL%/*}

step "1. Instance B (WSL, PostgreSQL 16, port 5432)"
for pair in "gbrain:gbrain-db-backup" "memory_governor:memory_governor-db-backup" "postgres:postgres-b-admin-db-backup"; do
  db=${pair%%:*}; name="${pair#*:}-$D.dump"
  if pg_dump "$BASE/$db" -Fc -f "$WSLB/$name" && cp "$WSLB/$name" "$WINB/$name"; then echo "   dumped $name"; else fail "$name"; fi
done

step "2. Instance A (Windows, PostgreSQL 15, port 5433)"
for trip in "pdlf:pdlf_agent:pdlf-db-backup" "postgres:postgres:postgres-a-admin-db-backup"; do
  IFS=: read -r db user stem <<< "$trip"; name="$stem-$D.dump"
  if powershell.exe -NoProfile -Command "& '$PGW' -h 127.0.0.1 -p 5433 -U $user -d $db -w -Fc -f 'C:\\backup-gbrain\\$name'; exit \$LASTEXITCODE" \
     && [ -s "$WINB/$name" ] && cp "$WINB/$name" "$WSLB/$name"; then echo "   dumped $name"; else fail "$name"; fi
done

step "3. Hash check, both locations"
n=0
for f in "$WSLB"/*-"$D".dump; do
  [ -e "$f" ] || continue; b=$(basename "$f"); n=$((n+1))
  [ "$(sha256sum < "$f")" = "$(sha256sum < "$WINB/$b" 2>/dev/null)" ] && echo "   match $b" || fail "hash $b"
done
[ "$n" -eq 5 ] || fail "expected 5 dumps, found $n"

step "4. Keep the two most recent cycles in each location"
if [ "$FAIL" -eq 0 ]; then
  for dir in "$WSLB" "$WINB"; do
    for d in $(ls "$dir" | grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}\.dump$' | sed 's/\.dump$//' | sort -u | sort -r | tail -n +3); do
      rm -f "$dir"/*"$d".dump; echo "   removed cycle $d from $dir"
    done
  done
else echo "   skipped because a step above failed"; fi

step "5. GBrain export: one folder per source, in C:\\backup-dream-cycle\\$D"
EXP=/mnt/c/backup-dream-cycle/$D
rm -rf "$EXP"; mkdir -p "$EXP"
SRCS=$(gbrain sources list --json 2>/dev/null | python3 -c 'import json,sys;print("\n".join(s["id"] for s in json.load(sys.stdin)["sources"]))')
[ -n "$SRCS" ] || fail "could not list GBrain sources"
for s in $SRCS; do
  if gbrain export --source "$s" --dir "$EXP/$s" > "$EXP/$s.export.log" 2>&1; then echo "   exported $s"; else fail "export $s (see $EXP/$s.export.log)"; fi
done
if [ "$FAIL" -eq 0 ]; then
  for d in $(ls /mnt/c/backup-dream-cycle | grep -E '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' | sort -r | tail -n +3); do
    rm -rf "/mnt/c/backup-dream-cycle/$d"; echo "   removed export $d"
  done
fi

echo
MSG=/mnt/c/mybizz/logs/sunday-backup/last-result.txt
if [ "$FAIL" -eq 0 ]; then
  printf 'Sunday backup finished: ALL DONE.\r\n\r\nNext: open OpenCode and run /mb-memory-system-diagnostic.\r\nAnswer yes to the dream cycle at its end.\r\n' > "$MSG"
else
  printf "Sunday backup FAILED:\r\n$FAILS\r\nDo this:\r\n1. If PostgreSQL 15 is named above, start it. PowerShell (Admin): Start-Service postgresql-x64-15\r\n2. Run the backup again. PowerShell: Start-ScheduledTask SundayBackup\r\n3. If it fails again, paste these lines to Claude.\r\n\r\nYou may still run /mb-memory-system-diagnostic,\r\nbut answer NO to the dream cycle until the backup has succeeded.\r\n" > "$MSG"
fi
powershell.exe -NoProfile -Command "Start-Process powershell.exe -WindowStyle Hidden -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','C:\mybizz\scripts\show-sunday-result.ps1'" >/dev/null 2>&1
if [ "$FAIL" -eq 0 ]; then echo "SUNDAY BACKUP: ALL DONE"; exit 0; else echo "SUNDAY BACKUP: FAILED - see $LOG"; exit 9; fi
