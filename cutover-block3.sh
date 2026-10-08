#!/usr/bin/env bash
# GBrain upgrade, block 3: start the memory governor and prove that every fact is still there.
# It refuses to run unless block 2 has completed. It does not start OpenCode.
set -uo pipefail
cd "$HOME"
B="$HOME/backups"
PROBLEMS=0
problem() { echo "PROBLEM: $*"; PROBLEMS=$((PROBLEMS+1)); }
command -v jq >/dev/null 2>&1 || { echo "STOP: jq is not installed."; exit 1; }
[ -f "$B/.stage2-ok" ] || { echo "STOP: block 2 has not completed. Run block 2 first."; exit 1; }
if ps aux | grep -E 'opencode|gbrain serve' | grep -v grep >/dev/null; then
  echo "note: OpenCode or gbrain serve is running. That is fine at this stage."
fi

echo "== 1. start the memory governor (API and worker)"
systemctl --user start memory-governor-api memory-governor-worker || problem "could not start the governor services"
sleep 10
for u in memory-governor-api memory-governor-worker; do
  st=$(systemctl --user is-active "$u")
  echo "$u: $st"
  [ "$st" = "active" ] || problem "$u is not active"
done
echo "port 8321 listeners: $(ss -tlnp 2>/dev/null | grep -c ':8321 ')"
CODE=$(curl -s -m 10 -o /dev/null -w "%{http_code}" http://127.0.0.1:8321/memory/review-queue)
echo "unauthenticated review-queue answer: $CODE (must be 422)"
[ "$CODE" = "422" ] || problem "the governor API did not answer 422"
N=$(grep -c '\.bun/bin' "$HOME/.config/systemd/user/memory-governor-worker.service" 2>/dev/null)
echo "worker unit lines with the bun path: ${N:-0} (must be 1 or more)"
[ "${N:-0}" -ge 1 ] || problem "the worker unit has no bun path line"
echo "recent worker log:"
journalctl --user -u memory-governor-worker -n 12 --no-pager 2>/dev/null | cut -c1-150

echo "== 2. facts in every source, before and after the upgrade"
jsononly() { sed -n '/^{/,$p' "$1" 2>/dev/null; }
ids() { jsononly "$1" | jq -r '.facts[]?.id' 2>/dev/null | sort -u; }
EXPECTED=$(ls "$B"/recall-before-*.json 2>/dev/null | wc -l)
CHECKED=0
TOTAL_MISSING=0
printf "%-30s %8s %8s %8s\n" source before after missing
for s in $(gbrain sources list --json 2>/dev/null | jq -r '.sources[].id'); do
  CHECKED=$((CHECKED+1))
  GBRAIN_SOURCE=$s gbrain call recall '{"limit": 500}' > "$B/recall-after-$s.json" 2>/dev/null
  ids "$B/recall-before-$s.json" > /tmp/ids-before.txt
  ids "$B/recall-after-$s.json"  > /tmp/ids-after.txt
  nb=$(grep -c . /tmp/ids-before.txt); na=$(grep -c . /tmp/ids-after.txt)
  miss=$(comm -23 /tmp/ids-before.txt /tmp/ids-after.txt | grep -c .)
  printf "%-30s %8s %8s %8s\n" "$s" "$nb" "$na" "$miss"
  TOTAL_MISSING=$((TOTAL_MISSING+miss))
  sb=$(wc -c < "$B/recall-before-$s.json" 2>/dev/null || echo 0)
  [ "$sb" -le 400 ] || [ "$nb" -gt 0 ] || problem "$s: the saved before-file has content, but no facts could be read from it"
  jsononly "$B/recall-after-$s.json" | jq -e 'has("facts")' >/dev/null 2>&1 || problem "$s: the after-result is not a normal recall answer"
done
[ "$CHECKED" -gt 0 ] && [ "$CHECKED" = "$EXPECTED" ] || problem "checked $CHECKED source(s), but $EXPECTED before-files exist"
[ "$TOTAL_MISSING" = "0" ] || problem "$TOTAL_MISSING fact(s) present before the upgrade are missing now"

echo
if [ "$PROBLEMS" = "0" ]; then
  touch "$B/.stage3-ok"
  echo "BLOCK 3 COMPLETE: every check passed."
else
  echo "BLOCK 3 FINISHED WITH $PROBLEMS PROBLEM(S). Do not go on. Paste this whole output to Claude."
fi
