#!/usr/bin/env python3
"""Move a business's project context into its project library (PDLF Step 11, route B).

    python3 /mnt/c/mybizz/scripts/migrate-project-context.py <slug> --check   changes nothing; reports problems
    python3 /mnt/c/mybizz/scripts/migrate-project-context.py <slug> --run     checks again, then moves and repairs

The migration map is {slug}-project-library/wip/context-migration-map.md. Each row of its table is
    | `context path` | `library path` |
with paths relative to the two repositories. A library path of `not moved` removes the file from the
context without copying it; it stays in the context's Git history.

Every file the context's Git repository tracks, except .gitignore, must have exactly one row.
Every document keeps its doc-id, so the mb-doc-check commit hook recognises each move and rewrites
the links to it in every repository at the next commit-all.
Both repositories must be fully committed before --run, so every file stays recoverable from Git.
The sources are removed from the context only after every copy is verified and repaired.
"""
import os, re, subprocess, sys, datetime

SOURCES = "/mnt/c/mybizz/scripts/mb-doc-check.sources"
NOT_MOVED = "not moved"
PLACEHOLDER_MAX_LINES = 40

LINK = re.compile(r"\[\[\[[^\]]*\]\]\]\([^)]*\)|\[\[[^\]]*\]\]")
ID = re.compile(r'^doc-id:\s*"?(mb-[0-9a-f]{8})"?\s*$', re.M)
ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*`?([^`|]+?)`?\s*\|\s*$")


def stem(p):
    return os.path.splitext(os.path.basename(p))[0]


def read_id(path):
    with open(path, "rb") as f:
        m = ID.search(f.read(4000).decode("utf-8", "replace"))
    return m.group(1) if m else None


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)


def read_map(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = ROW.match(line.strip())
            if m and not set(m.group(1)) <= set("-: "):
                rows.append((m.group(1).strip(), m.group(2).strip()))
    return rows


def other_roots(ctx):
    roots = []
    with open(SOURCES) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith(("#", "@")):
                path = line.split("=", 1)[1].strip()
                if os.path.abspath(path) != os.path.abspath(ctx) and os.path.isdir(path):
                    roots.append(path)
    return roots


def ids_elsewhere(ctx):
    found = {}
    for root in other_roots(ctx):
        for d, dirs, files in os.walk(root):
            dirs[:] = [x for x in dirs if x != ".git"]
            for n in files:
                if n.endswith(".md"):
                    p = os.path.join(d, n)
                    x = read_id(p)
                    if x:
                        found.setdefault(x, []).append(p)
    return found


def check(ctx, lib, map_path):
    problems = []
    for repo in (ctx, lib):
        if not os.path.isdir(os.path.join(repo, ".git")):
            problems.append(f"not a Git repository: {repo}")
        elif git(repo, "status", "--porcelain").stdout.strip():
            problems.append(f"has uncommitted changes (run commit-all first): {repo}")
    if not os.path.isfile(map_path):
        return problems + [f"migration map missing: {map_path}"]
    rows = read_map(map_path)
    if not rows:
        return problems + ["the migration map has no rows"]
    tracked = {p for p in git(ctx, "ls-files").stdout.splitlines() if p != ".gitignore"}
    mapped = [s for s, _ in rows]
    for p in sorted({s for s in mapped if mapped.count(s) > 1}):
        problems.append(f"context file mapped more than once: {p}")
    for p in sorted(tracked - set(mapped)):
        problems.append(f"context file not in the map: {p}")
    for p in sorted(set(mapped) - tracked):
        problems.append(f"mapped file not in the context: {p}")
    targets = [d for _, d in rows if d != NOT_MOVED]
    for p in sorted({d for d in targets if targets.count(d) > 1}):
        problems.append(f"library path used more than once: {p}")
    elsewhere = ids_elsewhere(ctx)
    for src, dst in rows:
        if dst == NOT_MOVED or src not in tracked:
            continue
        s, t = os.path.join(ctx, src), os.path.join(lib, dst)
        if src.endswith(".md"):
            x = read_id(s)
            if x and x in elsewhere:
                problems.append(f"doc-id {x} of {src} already used by: {', '.join(elsewhere[x])}")
        if os.path.isfile(t):
            with open(t, "rb") as f:
                lines = f.read().count(b"\n")
            if lines > PLACEHOLDER_MAX_LINES:
                problems.append(f"target is not a placeholder ({lines} lines): {dst}")
        elif os.path.exists(t):
            problems.append(f"target is a folder: {dst}")
    return problems


def replacements(slug, rows):
    ctx_id, lib_id = f"{slug}-project-context", f"{slug}-project-library"
    moved = [(s, d) for s, d in rows if d != NOT_MOVED]
    pairs = []
    for src, dst in moved:
        for sep in ("/", "\\"):
            pairs.append((re.escape(ctx_id + sep + src.replace("/", sep)), lib_id + sep + dst.replace("/", sep)))
    for src, dst in moved:
        if src != dst:
            for sep in ("/", "\\"):
                pairs.append((r"(?<![A-Za-z0-9_-])" + re.escape(src.replace("/", sep)), dst.replace("/", sep)))
    pairs.append((re.escape(ctx_id), lib_id))
    for src, dst in moved:
        if src.endswith(".md") and stem(src) != stem(dst):
            pairs.append((r"(?<![A-Za-z0-9_-])" + re.escape(stem(src)) + r"(?![A-Za-z0-9_-])", stem(dst)))
    return [(re.compile(a), (lambda m, s=b: s)) for a, b in pairs]


def repair_text(text, pairs):
    out, pos, n = [], 0, 0
    for m in list(LINK.finditer(text)) + [None]:
        seg = text[pos:m.start()] if m else text[pos:]
        for rx, new in pairs:
            seg, k = rx.subn(new, seg)
            n += k
        out.append(seg)
        if m:
            out.append(m.group(0))
            pos = m.end()
    return "".join(out), n


def set_title(text, new_stem):
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            head = re.sub(r'^title:.*$', f'title: "{new_stem}"', text[:end], count=1, flags=re.M)
            return head + text[end:]
    return text


def run(slug, ctx, lib, rows, log):
    moved = [(s, d) for s, d in rows if d != NOT_MOVED]
    for src, dst in moved:
        s, t = os.path.join(ctx, src), os.path.join(lib, dst)
        with open(s, "rb") as f:
            data = f.read()
        os.makedirs(os.path.dirname(t), exist_ok=True)
        with open(t, "wb") as f:
            f.write(data)
        with open(t, "rb") as f:
            if f.read() != data:
                log(f"STOPPED: the copy of {src} does not match. The context is untouched.")
                sys.exit(1)
        log(f"copied   {src}  ->  {dst}")
    pairs = replacements(slug, rows)
    for src, dst in moved:
        if not dst.endswith(".md"):
            continue
        t = os.path.join(lib, dst)
        with open(t, encoding="utf-8", newline="") as f:
            text = f.read()
        new, n = repair_text(text, pairs)
        if stem(src) != stem(dst):
            new = set_title(new, stem(dst))
        if new != text:
            with open(t, "w", encoding="utf-8", newline="") as f:
                f.write(new)
            log(f"repaired {dst} ({n} mentions)")
    for src, _ in rows:
        os.remove(os.path.join(ctx, src))
    log(f"removed  {len(rows)} files from the context ({len(rows) - len(moved)} not moved)")


def main():
    if len(sys.argv) != 3 or sys.argv[2] not in ("--check", "--run") or not re.fullmatch(r"[a-z0-9-]+", sys.argv[1]):
        print(__doc__)
        sys.exit(2)
    slug, mode = sys.argv[1], sys.argv[2]
    base = f"/mnt/c/dev/dev-{slug}"
    ctx, lib = f"{base}/{slug}-project-context", f"{base}/{slug}-project-library"
    map_path = f"{lib}/wip/context-migration-map.md"
    log_path = os.path.expanduser(f"~/backups/migrate-{slug}-project-context-log.txt")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    lines = [f"{datetime.datetime.now():%Y-%m-%d %H:%M} {slug} {mode}"]

    def log(msg):
        print(msg)
        lines.append(msg)

    problems = check(ctx, lib, map_path)
    for p in problems:
        log(f"PROBLEM: {p}")
    rows = read_map(map_path) if os.path.isfile(map_path) else []
    if problems:
        log(f"{len(problems)} problem(s). Nothing was changed.")
    elif mode == "--check":
        moved = sum(1 for _, d in rows if d != NOT_MOVED)
        log(f"Check passed: {moved} files to move, {len(rows) - moved} not moved. Nothing was changed.")
    else:
        run(slug, ctx, lib, rows, log)
        log("Done. Next: run commit-all.")
    with open(log_path, "w") as f:
        f.write("\n".join(lines) + "\n")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
