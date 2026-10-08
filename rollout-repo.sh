#!/usr/bin/env bash
# One-time rollout for ONE repository. Usage:  bash rollout-repo.sh /mnt/c/path/to/repo
# It stops at the first problem. Every step is its own commit, so Git can undo any of them.
# It never pushes: you review the result and push yourself.
set -euo pipefail
REPO="${1:?Usage: bash rollout-repo.sh /mnt/c/path/to/repo}"
SC="${SC:-/mnt/c/mybizz/scripts/mb-doc-check.py}"
NAME="$(basename "$REPO")"
LOGDIR="${LOGDIR:-$HOME/backups}"; mkdir -p "$LOGDIR"
cd "$REPO"

if [ -n "$(git status --porcelain)" ]; then
  echo "STOP: $REPO has uncommitted changes. Commit or restore them first."; exit 1
fi
echo "== repository: $REPO   (starting at commit $(git rev-parse --short HEAD))"

step() { echo; echo "== $1"; }
commit_if_changed() {
  if [ -n "$(git status --porcelain)" ]; then
    git add -A
    git commit -q -m "$1"
    echo "   committed: $1"
  else
    echo "   nothing to change"
  fi
}

step "1/4  line endings (every document gets LF)"
python3 "$SC" eol --repo "$REPO" --write | tail -3
commit_if_changed "Give every document LF line endings"

step "2/4  links that point to nothing become plain words"
python3 "$SC" fix-broken --repo "$REPO" --include-ambiguous --write | tee "$LOGDIR/fix-broken-$NAME.txt" | grep -E 'links that point|rewritten|STOP' || true
commit_if_changed "Turn links that point to nothing into plain words"

step "3/4  every link in the standard form"
python3 "$SC" rollout --repo "$REPO" --write | grep -E '^==|documents:|to convert|cannot be|rewritten|STOP'
commit_if_changed "Write every link in the standard form"

step "4/4  the updated date on every document that has none"
python3 "$SC" migrate --root "$REPO" --write | grep -E 'gained|code and a title|given|STOP' || true
commit_if_changed "Give every document its updated date"

step "final check of $NAME"
python3 "$SC" check --root "$REPO" | tail -8
echo
git log --oneline -6
echo
echo "Review the result, then push with:  git -C \"$REPO\" push"
