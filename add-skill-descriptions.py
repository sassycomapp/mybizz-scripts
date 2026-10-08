#!/usr/bin/env python3
"""Add or refresh the "Skill Description" column in the skills catalog.

Run from WSL:
    python3 /mnt/c/mybizz/scripts/add-skill-descriptions.py

Rules:
- The description is the `description` field in the frontmatter of the skill's
  SKILL.md file.
- The file read is the first path in "Installed path". If the skill is not
  installed, the file read is "Source path".
- Windows paths (C:\\...) are read through /mnt/c/... and ~ is the WSL home.
- Line breaks in a description become single spaces and | is written as \\|
  so the table stays intact.
- Running it again replaces the column; it never adds a second one.
"""

import os
import re
import sys
import tempfile
from pathlib import Path

CATALOG = Path("/mnt/c/mybizz/mybizz-os-docs/os-reference-docs/skills-catalog.md")
COLUMN = "Skill Description"
CELL_SPLIT = re.compile(r"(?<!\\)\|")


def to_wsl_path(raw: str) -> Path:
    raw = raw.strip()
    m = re.match(r"^([A-Za-z]):\\(.*)$", raw)
    if m:
        return Path(f"/mnt/{m.group(1).lower()}/" + m.group(2).replace("\\", "/"))
    if raw.startswith("~"):
        return Path(os.path.expanduser(raw))
    return Path(raw)


def frontmatter_lines(text: str):
    lines = text.lstrip("\ufeff").replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return lines[1:i]
    return None


def read_description(lines):
    for i, line in enumerate(lines):
        m = re.match(r"^description:\s*(.*)$", line)
        if not m:
            continue
        value = m.group(1).rstrip()
        rest = lines[i + 1:]

        # Block scalar: description: | or > (any indicators)
        if re.match(r"^[|>][-+0-9]*\s*(#.*)?$", value):
            block = []
            for nxt in rest:
                if nxt.strip() == "" or nxt[:1] in (" ", "\t"):
                    block.append(nxt.strip())
                else:
                    break
            return " ".join(b for b in block if b)

        # Double-quoted, possibly spanning lines
        if value.startswith('"'):
            body = value[1:]
            k = 0
            while not re.search(r'(?<!\\)"\s*(#.*)?$', body) and k < len(rest):
                body += " " + rest[k].strip()
                k += 1
            body = re.sub(r'(?<!\\)"\s*(#.*)?$', "", body)
            return (body.replace('\\"', '"').replace("\\n", " ")
                        .replace("\\t", " ").replace("\\\\", "\\"))

        # Single-quoted, possibly spanning lines
        if value.startswith("'"):
            body = value[1:]
            k = 0
            while not re.search(r"(?<!')'(?!')\s*(#.*)?$", body) and k < len(rest):
                body += " " + rest[k].strip()
                k += 1
            body = re.sub(r"(?<!')'(?!')\s*(#.*)?$", "", body)
            return body.replace("''", "'")

        # Plain value, with any indented continuation lines
        parts = [value]
        for nxt in rest:
            if nxt[:1] in (" ", "\t") and nxt.strip():
                parts.append(nxt.strip())
            else:
                break
        return " ".join(p for p in parts if p)
    return None


def description_for(row: dict):
    installed = row["Installed path"].strip()
    if installed.lower() == "not installed":
        raw = row["Source path"]
    else:
        raw = installed.split(";")[0]
    path = to_wsl_path(raw)
    if not path.is_file():
        return "Not found", f"file not found: {path}"
    fm = frontmatter_lines(path.read_text(encoding="utf-8", errors="replace"))
    desc = read_description(fm) if fm is not None else None
    if not desc:
        return "No description", f"no description field: {path}"
    desc = re.sub(r"\s+", " ", desc).strip()
    desc = desc.replace("\\|", "|").replace("|", "\\|")
    return desc, None


def split_row(line: str):
    cells = CELL_SPLIT.split(line.strip())
    return [c.strip() for c in cells[1:-1]]


def join_row(cells):
    return "| " + " | ".join(cells) + " |"


def main():
    if sys.platform != "linux":
        sys.exit("Run this from WSL: the installed skills live in the WSL home folder.")
    catalog = Path(sys.argv[1]) if len(sys.argv) > 1 else CATALOG
    if not catalog.is_file():
        sys.exit(f"Catalog not found: {catalog}")

    lines = catalog.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n")
    start = next((i for i, l in enumerate(lines)
                  if l.startswith("|") and "Skill Name" in l and "Installed path" in l), None)
    if start is None:
        sys.exit("Skills table not found in the catalog.")

    header = split_row(lines[start])
    if COLUMN in header:
        col = header.index(COLUMN)
    else:
        header.append(COLUMN)
        col = len(header) - 1
    lines[start] = join_row(header)
    lines[start + 1] = join_row(["---"] * len(header))

    problems, count = [], 0
    i = start + 2
    while i < len(lines) and lines[i].startswith("|"):
        cells = split_row(lines[i])
        while len(cells) < len(header):
            cells.append("")
        row = dict(zip(header, cells))
        desc, problem = description_for(row)
        cells[col] = desc
        lines[i] = join_row(cells)
        if problem:
            problems.append(f"{row['Skill Name']}: {problem}")
        count += 1
        i += 1

    fd, tmp = tempfile.mkstemp(dir=catalog.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))
    os.replace(tmp, catalog)

    print(f"Updated {count} rows in {catalog}")
    if problems:
        print(f"{len(problems)} rows without a description:")
        for p in problems:
            print(f"  - {p}")


if __name__ == "__main__":
    main()
