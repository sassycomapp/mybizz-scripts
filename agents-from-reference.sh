#!/usr/bin/env bash
# Copies a project's reference file over its AGENTS.md (or agents.md).
#   bash agents-from-reference.sh "<reference file>" "<AGENTS file>"
# The body of the reference becomes the body of the agent file. If the agent file has a frontmatter block
# (--- ... --- at the top), that block is kept exactly. The old agent file is saved in ~/backups, and the
# reference file is deleted once the copy has been checked.
set -euo pipefail
REF="${1:-}"; TARGET="${2:-}"
[ -n "$REF" ] && [ -n "$TARGET" ] || { echo "Usage: bash agents-from-reference.sh \"<reference file>\" \"<AGENTS file>\""; exit 1; }
[ -f "$REF" ] || { echo "STOP: the reference file does not exist: $REF"; exit 1; }
case "$(basename "$TARGET")" in AGENTS.md|agents.md) ;; *) echo "STOP: the target must be named AGENTS.md or agents.md"; exit 1;; esac
python3 - "$REF" "$TARGET" <<'PYEOF'
import os, re, shutil, sys, time
ref, target = sys.argv[1], sys.argv[2]
FM = re.compile(r"\A---\r?\n.*?\r?\n---\r?\n", re.S)
r = open(ref, encoding="utf-8", newline="").read()
body = FM.sub("", r, count=1).lstrip("\r\n")
frontmatter = ""
eol = "\n"
if os.path.exists(target):
    old = open(target, encoding="utf-8", newline="").read()
    m = FM.match(old)
    if m: frontmatter = m.group(0)
    eol = "\r\n" if "\r\n" in old else "\n"
    os.makedirs(os.path.expanduser("~/backups"), exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    shutil.copy(target, os.path.expanduser(f"~/backups/{os.path.basename(os.path.dirname(os.path.abspath(target)))}-{os.path.basename(target)}.{stamp}"))
    print("old file saved in ~/backups")
body = body.replace("\r\n", "\n").replace("\n", eol)
new = frontmatter + body
if not new.endswith(eol): new += eol
open(target, "w", encoding="utf-8", newline="").write(new)
check = open(target, encoding="utf-8", newline="").read()
assert check == new
os.remove(ref)
print(f"copied: {target}\nreference file deleted: {ref}")
PYEOF
