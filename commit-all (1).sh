#!/usr/bin/env bash
# Commit, update GBrain and push every repository on the list below with one command.
#   bash commit-all.sh "your message"   does everything
#   bash commit-all.sh --status         only shows what would be committed; changes nothing
SYNC="${SYNC:-/mnt/c/mybizz/scripts/sync-gbrain.sh}"
if [ -n "${REPOS_OVERRIDE:-}" ]; then read -r -a REPOS <<< "$REPOS_OVERRIDE"; else
REPOS=(
  /mnt/c/mybizz/mybizz-os-docs
  /mnt/c/mybizz/mybizz-config-docs
  /mnt/c/data-mybizz-mgt
  /mnt/c/pdlf
  /mnt/c/dev/dev-root
  /mnt/c/dev/dev-mb-3-cs/mb-3-cs-project-context
  /mnt/c/dev/dev-mb-3-cs/mb-3-cs-project-library
  /mnt/c/dev/dev-mb-4-ecom/mb-4-ecom-project-library
  /mnt/c/dev/project-library-global
  /mnt/c/mybizz/mb-project-docs
  /mnt/c/mybizz/mb-memory-system-diagnostic
  /mnt/c/mybizz/mb-compile-rules
  /mnt/c/mybizz/mb-sentinel-review
  /mnt/c/mybizz/mb-sysdoc-creator
  /mnt/c/mybizz/mb-submit-memory
  /mnt/c/mybizz/mb-archify-scope
  /mnt/c/mybizz/mb-close-out
  /mnt/c/mybizz/scripts
)
fi

if [ "${1:-}" = "--status" ]; then
  for r in "${REPOS[@]}"; do
    echo "== $(basename "$r")"
    s="$(git -C "$r" status --short | head -15)"; [ -n "$s" ] && echo "$s" | sed 's/^/   /' || echo "   (nothing to commit)"
  done
  exit 0
fi

MSG="${1:-}"
if [ -z "$MSG" ]; then read -r -p "Commit message: " MSG; fi
[ -z "$MSG" ] && { echo "STOP: a commit message is needed."; exit 1; }

LOGDIR="${LOGDIR:-$HOME/backups}"; mkdir -p "$LOGDIR"; LOG="$LOGDIR/commit-all-last.txt"
exec > >(tee "$LOG") 2>&1
echo "Message: $MSG"
declare -A COMMIT PUSH
BLOCKED=0; FAILED=0

echo; echo "######## 1. Commit"
for r in "${REPOS[@]}"; do
  name="$(basename "$r")"; echo; echo "---- $name"
  if ! grep -q "mb-doc-check" "$r/.git/hooks/pre-commit" 2>/dev/null; then echo "   WARNING: the mb-doc-check hook is not installed in this repository"; fi
  porc="$(git -C "$r" status --porcelain)"
  if [ -z "$porc" ]; then COMMIT[$name]="nothing to commit"; echo "   nothing to commit"; continue; fi
  echo "$porc" | head -8 | sed 's/^/   /'; [ "$(echo "$porc" | wc -l)" -gt 8 ] && echo "   ... and $(( $(echo "$porc" | wc -l) - 8 )) more"
  git -C "$r" add -A
  out="$(git -C "$r" commit -m "$MSG" 2>&1)"; rc=$?
  if [ $rc -eq 0 ]; then COMMIT[$name]="committed"; echo "$out" | grep -E '^  ' | head -4
  else COMMIT[$name]="BLOCKED - fix what it says, then run this command again"; BLOCKED=$((BLOCKED + 1)); echo "   BLOCKED:"; echo "$out" | head -25 | cut -c1-220 | sed 's/^/   /'; fi
done

echo; echo "######## 2. GBrain"
if [ -z "${SKIP_SYNC:-}" ]; then
  tmp="$(mktemp)"; bash "$SYNC" > "$tmp" 2>&1
  echo "   $(grep -c 'ERROR' "$tmp") error line(s); $(grep 'gbrain sync complete' "$tmp" | tail -1)"
  [ "$(grep -c 'ERROR' "$tmp")" -gt 0 ] && FAILED=$((FAILED + 1)) && grep 'ERROR' "$tmp" | head -5 | sed 's/^/   /'
  cat "$tmp" >> "$LOG"; rm -f "$tmp"
else echo "   skipped"; fi

echo; echo "######## 3. Push"
for r in "${REPOS[@]}"; do
  name="$(basename "$r")"
  out="$(git -C "$r" push 2>&1)"; rc=$?
  if [ $rc -eq 0 ]; then PUSH[$name]="$(echo "$out" | grep -q 'Everything up-to-date' && echo 'already up to date' || echo 'pushed')"
  else PUSH[$name]="FAILED"; FAILED=$((FAILED + 1)); echo "---- $name"; echo "$out" | tail -4 | cut -c1-200 | sed 's/^/   /'; fi
done

echo; echo "======== SUMMARY"
printf '   %-28s %-26s %s\n' "repository" "commit" "push"
for r in "${REPOS[@]}"; do name="$(basename "$r")"; printf '   %-28s %-26s %s\n' "$name" "${COMMIT[$name]%% -*}" "${PUSH[$name]}"; done
echo
if [ $BLOCKED -gt 0 ]; then echo "$BLOCKED repository(ies) were BLOCKED. Read the message above, fix it, and run the same command again."; fi
if [ $FAILED -gt 0 ]; then echo "$FAILED problem(s) with GBrain or the push. Paste this summary to Claude."; fi
[ $BLOCKED -eq 0 ] && [ $FAILED -eq 0 ] && echo "All done."
echo "Full log: $LOG"
[ $BLOCKED -eq 0 ] && [ $FAILED -eq 0 ]
