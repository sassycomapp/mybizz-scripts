#!/usr/bin/env bash
# Finish the rollout for the remaining repositories, then update GBrain and check it.
#   bash rollout-all.sh           does the work (nothing is pushed)
#   bash rollout-all.sh --push    pushes every repository to GitHub (run it after you have read the summary)
SC="${SC:-/mnt/c/mybizz/scripts/mb-doc-check.py}"
RR="${RR:-/mnt/c/mybizz/scripts/rollout-repo.sh}"
GB="${GBRAIN:-gbrain}"
if [ -n "${REPOS_OVERRIDE:-}" ]; then read -r -a REPOS <<< "$REPOS_OVERRIDE"; else
REPOS=(
  /mnt/c/dev/dev-root
  /mnt/c/data-mybizz-mgt
  /mnt/c/pdlf
  /mnt/c/dev/dev-makepdlf/makepdlf-project-library
  /mnt/c/dev/dev-mb-3-cs/mb-3-cs-project-library
  /mnt/c/dev/project-library-global
  /mnt/c/mybizz/mybizz-config-docs
)
fi
PUSHSET=("/mnt/c/mybizz/mybizz-os-docs" "${REPOS[@]}")
[ -n "${REPOS_OVERRIDE:-}" ] && PUSHSET=("${REPOS[@]}")

if [ "${1:-}" = "--push" ]; then
  for r in "${PUSHSET[@]}"; do
    echo "== pushing $(basename "$r")"; git -C "$r" push 2>&1 | tail -2
  done
  echo; echo "Done pushing."; exit 0
fi

LOGDIR="${LOGDIR:-$HOME/backups}"; mkdir -p "$LOGDIR"
LOG="$LOGDIR/rollout-all-$(date +%F-%H%M).txt"; TMP="$(mktemp -d)"
: > "$LOG"
RESULT=()
echo "Full details of this run are written to: $LOG"

for r in "${REPOS[@]}"; do
  name="$(basename "$r")"; echo; echo "---- $name"
  porc="$(git -C "$r" status --porcelain)"
  if [ "$name" = "mybizz-config-docs" ]; then
    reg="$r/mb-config-manager/config-manager-register.md"
    if ! grep -q 'retired 2026-09-30' "$reg" 2>/dev/null; then
      RESULT+=("$name: SKIPPED - save the new config-manager-register.md into mb-config-manager first"); echo "   SKIPPED: the new register is not saved yet"; continue
    fi
    if [ "$porc" = " M mb-config-manager/config-manager-register.md" ]; then
      git -C "$r" add mb-config-manager/config-manager-register.md && git -C "$r" commit -q -m "Update the config-manager register" && echo "   committed the register" && porc="$(git -C "$r" status --porcelain)"
    fi
  fi
  if [ -n "$porc" ]; then
    RESULT+=("$name: SKIPPED - it has uncommitted changes"); echo "   SKIPPED: uncommitted changes:"; echo "$porc" | head -6 | sed 's/^/      /'; continue
  fi
  if bash "$RR" "$r" > "$TMP/$name.txt" 2>&1; then
    n="$(grep -c 'committed:' "$TMP/$name.txt")"
    RESULT+=("$name: done ($n commits)"); echo "   done ($n commits)"
  else
    RESULT+=("$name: STOPPED - needs a look"); echo "   STOPPED. The last lines:"; tail -25 "$TMP/$name.txt" | cut -c1-200 | sed 's/^/      /'
  fi
  { echo "######## $name"; cat "$TMP/$name.txt"; } >> "$LOG"
done

echo; echo "---- GBrain"
if [ -z "${SKIP_SYNC:-}" ]; then
  bash "${SYNC:-/mnt/c/mybizz/scripts/sync-gbrain.sh}" > "$TMP/sync.txt" 2>&1; echo "   sync finished: $(grep -c 'ERROR' "$TMP/sync.txt") error line(s); $(grep 'gbrain sync complete' "$TMP/sync.txt" | tail -1)"
  { echo "######## sync"; cat "$TMP/sync.txt"; } >> "$LOG"
fi
VERDICT="$(python3 - "$GB" <<'PY'
import json, os, subprocess, sys, collections
gb = sys.argv[1].split()
def call(args, env=None):
    e = dict(os.environ); e.update(env or {})
    out = subprocess.run(gb + args, capture_output=True, text=True, env=e).stdout
    for i, ch in enumerate(out):
        if ch in "[{":
            try: return json.loads(out[i:])
            except ValueError: return None
    return None
src, slug = os.environ.get("CHK_SRC", "mybizz-os-docs"), os.environ.get("CHK_SLUG", "operating-procedures/daily-ops")
def rows(x):
    return [e for e in x if isinstance(e, dict)] if isinstance(x, list) else None
out = rows(call(["call", "get_links", json.dumps({"slug": slug})], {"GBRAIN_SOURCE": src}))
other = collections.Counter(e.get("to_source_id") for e in out if e.get("to_source_id") not in (None, src))
tsrc, tslug = os.environ.get("CHK_TSRC", "mybizz-config-docs"), os.environ.get("CHK_TSLUG", "gbrain/gbrain-config")
back = rows(call(["backlinks", tslug, "--source", tsrc]))
if out is None or back is None:
    print("   GBRAIN LINKS BETWEEN REPOSITORIES: COULD NOT CHECK - tell me, do not worry"); sys.exit(0)
frm = collections.Counter(e.get("from_source_id") for e in back)
n_other_in = sum(v for k, v in frm.items() if k != tsrc)
print(f"   links going from {slug} to other repositories: {sum(other.values())}  ({dict(other)})")
print(f"   links coming into {tslug} from other repositories: {n_other_in}  ({ {k: v for k, v in frm.items() if k != tsrc} })")
print("   GBRAIN LINKS BETWEEN REPOSITORIES: " + ("OK" if sum(other.values()) > 0 and n_other_in > 0 else "NOT SEEN - tell me, do not worry"))
PY
)"
echo "$VERDICT"; echo "$VERDICT" >> "$LOG"

echo; echo "======== SUMMARY"
for x in "${RESULT[@]}"; do echo "   $x"; done
echo
if printf '%s\n' "${RESULT[@]}" | grep -qE 'SKIPPED|STOPPED'; then
  echo "Some repositories need a look. Paste this summary to me. Do not push yet."
else
  echo "Everything is done. If the GBrain line above says OK, publish with:  bash /mnt/c/mybizz/scripts/rollout-all.sh --push"
fi
