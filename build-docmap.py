#!/usr/bin/env python3
"""Rebuild the folder trees of the docmap from the real folders.

  python3 build-docmap.py            show what would change (changes nothing)
  python3 build-docmap.py --write    rewrite docmap.md

Only the tree blocks are rebuilt (a code block whose first line is a Windows folder such as C:\\mybizz\\).
Everything else in the docmap is left exactly as it is. In a tree:
  - an entry that still exists keeps its description and its position;
  - an entry that no longer exists is removed;
  - a folder or file that is not listed yet is added at the end of its folder, marked "(new - add a description)";
  - a folder is only searched for new entries if the docmap already lists something inside it, and not at all when
    the docmap says "(many subfolders ...)" for it.
The "**Verified:**" date is set to today."""
import argparse, datetime, os, re, sys

DOCMAP = "/mnt/c/dev/dev-root/docmap.md"
PREFIX = os.environ.get("DOCMAP_DRIVE_PREFIX", "/mnt")          # tests point this somewhere else
IGNORE = {".git", "node_modules", "__pycache__", "Thumbs.db", "desktop.ini", ".DS_Store"}
MAX_NEW = 25
NEWNOTE = "(new — add a description)"
LINE = re.compile(r"^(?P<indent>(?:│   |    )*)(?P<branch>├── |└── )(?P<rest>.*)$")


def wsl(win):
    m = re.match(r"^([A-Za-z]):[\\/](.*)$", win)
    return f"{PREFIX}/{m.group(1).lower()}/" + m.group(2).replace("\\", "/") if m else win


class Node:
    def __init__(self, raw, note=None, special=False):
        self.raw, self.note, self.special = raw, note, special
        self.children, self.parsed_children = [], False

    @property
    def name(self):
        return self.raw.rstrip("/\\")


def parse_block(lines):
    root_line, body = lines[0], lines[1:]
    root = Node(root_line)
    stack = [(-1, root)]
    for ln in body:
        m = LINE.match(ln)
        if not m:
            return None
        depth = len(m.group("indent")) // 4
        rest = m.group("rest")
        i = rest.find("←")
        raw, note = (rest[:i].rstrip(), rest[i + 1:].strip()) if i >= 0 else (rest.strip(), None)
        node = Node(raw, note, special=(i < 0 and raw.startswith("(")))
        while stack and stack[-1][0] >= depth:
            stack.pop()
        if not stack:
            return None
        stack[-1][1].children.append(node)
        stack[-1][1].parsed_children = True
        stack.append((depth, node))
    return root


def rebuild(node, path, report, rel):
    """node: a folder node; path: its real folder. Updates node.children in place."""
    real = {}
    try:
        for n in os.listdir(path):
            if n not in IGNORE and not n.startswith("."):
                real[n.lower()] = n
    except OSError:
        report["unreadable"].append(rel)
        return
    specials = [c for c in node.children if c.special]
    listed = [c for c in node.children if not c.special]
    exhaustive = not specials
    kept, seen = [], set()
    for c in listed:
        actual = real.get(c.name.lower())
        if actual is None:
            report["removed"].append(f"{rel}/{c.name}")
            continue
        seen.add(actual.lower())
        kept.append(c)
        full = os.path.join(path, actual)
        if c.children and os.path.isdir(full):
            rebuild(c, full, report, f"{rel}/{c.name}")
    new = sorted((n for k, n in real.items() if k not in seen), key=str.lower)
    if exhaustive and new:
        if len(new) > MAX_NEW:
            report["skipped"].append(f"{rel}: {len(new)} unlisted entries (too many to add)")
        else:
            for n in new:
                isdir = os.path.isdir(os.path.join(path, n))
                kept.append(Node(n + ("/" if isdir else ""), NEWNOTE))
                report["added"].append(f"{rel}/{n}")
    node.children = kept + specials


def render(root):
    out = [root.raw]
    rows = []

    def walk(node, ancestors):
        n = len(node.children)
        for i, c in enumerate(node.children):
            last = i == n - 1
            prefix = "".join("    " if a_last else "│   " for a_last in ancestors)
            rows.append((prefix + ("└── " if last else "├── "), c))
            walk(c, ancestors + [last])
    walk(root, [])
    width = max([len(p) + len(c.raw) for p, c in rows if c.note is not None] + [26]) + 2
    for p, c in rows:
        out.append(p + c.raw if c.note is None else p + c.raw.ljust(width - len(p)) + "← " + c.note)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--file", default=DOCMAP)
    a = ap.parse_args()
    text = open(a.file, encoding="utf-8", newline="").read()
    lines = text.split("\n")
    out, i, blocks = [], 0, 0
    report = {"added": [], "removed": [], "skipped": [], "unreadable": []}
    while i < len(lines):
        if lines[i].startswith("```") and i + 2 < len(lines) and re.match(r"^[A-Za-z]:\\.*\\$", lines[i + 1]) and LINE.match(lines[i + 2]):
            j = i + 1
            while j < len(lines) and not lines[j].startswith("```"):
                j += 1
            block = lines[i + 1:j]
            root = parse_block(block)
            path = wsl(block[0])
            if root is not None and os.path.isdir(path):
                rebuild(root, path, report, block[0].rstrip("\\"))
                out += [lines[i]] + render(root) + [lines[j]]
                blocks += 1
            else:
                report["unreadable"].append(block[0])
                out += lines[i:j + 1]
            i = j + 1
            continue
        out.append(lines[i])
        i += 1
    new = "\n".join(out)
    new = re.sub(r"^(\*\*Verified:\*\* ).*$", lambda m: m.group(1) + datetime.date.today().isoformat(), new, count=1, flags=re.M)
    print(f"tree blocks rebuilt: {blocks}")
    for k, label in (("added", "NEW (add a description)"), ("removed", "REMOVED (no longer exists)"), ("skipped", "NOT ADDED"), ("unreadable", "NOT CHECKED")):
        if report[k]:
            print(f"{label}: {len(report[k])}")
            for x in report[k][:40]:
                print("   ", x)
    if new == text:
        print("The docmap already matches the folders. Nothing to change.")
        return 0
    if not a.write:
        print("\nDry run. Add --write to rewrite the docmap.")
        return 0
    open(a.file, "w", encoding="utf-8", newline="").write(new)
    print("\nThe docmap was rewritten.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
