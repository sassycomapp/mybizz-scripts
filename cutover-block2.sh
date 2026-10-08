#!/usr/bin/env bash
# GBrain upgrade, block 2: install v0.59.18.0 into the checkout and apply the database changes.
# It refuses to run unless block 1 finished within the last 12 hours. It does not start any service.
set -uo pipefail
cd /tmp
B="$HOME/backups"
GB=/home/dev-p/gbrain
TAG=v0.59.18.0
EXPECT=045a613814b1ae4b3bbed3c3dc8765e33e23ef8d
fail() { echo; echo "STOP: $*"; echo "If the message says to roll back, run: bash /mnt/c/mybizz/scripts/cutover-rollback.sh --yes"; exit 1; }

[ -f "$B/.stage1-ok" ] || fail "block 1 has not completed. Run block 1 first."
[ -z "$(find "$B/.stage1-ok" -mmin +720)" ] || fail "block 1 is older than 12 hours. Run block 1 again."
if ps aux | grep -E 'opencode|gbrain|uvicorn app.main|app\.worker' | grep -v grep >/dev/null; then
  ps aux | grep -E 'opencode|gbrain|uvicorn app.main|app\.worker' | grep -v grep | cut -c1-140
  fail "a process that uses GBrain is running (listed above)"
fi

echo "== 1. fetch the release"
# A plain 'git fetch --tags' returns an error when the floating tag 'latest-stable' has moved upstream.
# So fetch only the release tag, then verify that it is exactly the commit that was tested.
git -C "$GB" fetch origin "refs/tags/$TAG:refs/tags/$TAG" >/dev/null 2>&1 || true
COMMIT=$(git -C "$GB" rev-parse -q --verify "refs/tags/$TAG^{commit}") || fail "tag $TAG is not in the local checkout"
[ "$COMMIT" = "$EXPECT" ] || fail "tag $TAG points to $COMMIT, not to the tested commit $EXPECT"
echo "release commit: $COMMIT (the tested release)"
[ -z "$(git -C "$GB" status --short)" ] || fail "the checkout has uncommitted changes"

echo "== 2. check out $TAG and install (no install scripts)"
git -C "$GB" checkout "$TAG" || fail "checkout failed"
( cd "$GB" && bun install --ignore-scripts ) || fail "bun install failed. Roll back."
VER=$(gbrain --version 2>/dev/null | grep -o '[0-9]*\.[0-9]*\.[0-9]*\.[0-9]*' | head -1)
echo "gbrain version now: $VER"
[ "$VER" = "0.59.18.0" ] || fail "the version is not 0.59.18.0. Roll back."

echo "== 3. apply the database changes only"
gbrain apply-migrations --force-schema --yes || fail "the database changes failed. Roll back."

echo "== 4. jobs (all waiting jobs were cancelled in block 1)"
gbrain jobs stats 2>/dev/null | grep -E "Queue health|WEDGED" || true
gbrain jobs list --limit 10 2>/dev/null | head -14 || true

echo "== 5. health, before and after"
gbrain doctor > "$B/doctor-after.txt" 2>&1
echo "FAIL lines before:"; grep -E '\[FAIL\]' "$B/doctor-before.txt" | sort -u | cut -c1-140
echo "FAIL lines after:";  grep -E '\[FAIL\]' "$B/doctor-after.txt"  | sort -u | cut -c1-140
tail -6 "$B/doctor-after.txt"
gbrain sources list --json > "$B/sources-after.json" 2>/dev/null
gbrain sources list 2>/dev/null | grep -E "federated|isolated|unset" | awk '{print $1, $2}'
echo "mcp_surface: $(gbrain config get mcp_surface 2>/dev/null | tail -1)"
touch "$B/.stage2-ok"
echo
echo "BLOCK 2 COMPLETE. Do not start any service. Paste this whole output to Claude."
