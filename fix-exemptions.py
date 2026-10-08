#!/usr/bin/env python3
"""Make the frontmatter ADRs and three other documents say what mb-doc-check really does: the files and folders it
skips (tmp- files, a few folders, Anvil app roots, obsolete, SKILL.md, empty files) are exempt. Each edit must match
exactly one line, or that edit is skipped and reported. Nothing is committed: run commit-all.sh afterwards."""
import os, re, sys
ADR = os.environ.get("ADR_DIR", "/mnt/c/dev/project-library-global/adr-global")
OS = os.environ.get("OS_DOCS", "/mnt/c/mybizz/mybizz-os-docs/os-reference-docs")
CFG = os.environ.get("CFG_DOCS", "/mnt/c/mybizz/mybizz-config-docs/gbrain")
NEW = "adr-document-frontmatter-and-identity.md"
OLD2 = "adr-frontmatter-exemption-transient-files.md"
SK = " The files and folders the program skips are listed in [[doc-check-config]]."

# (file, regex for the WHOLE line (re.M), replacement function or text)
EDITS = [
 (f"{ADR}/{NEW}", r"^Supersedes:.*$", lambda m: "Supersedes: [[adr-frontmatter-exemption-transient-files]] (in part: its list of frontmatter fields); [[adr-filename-and-frontmatter-numbering-policy]] (in part — see Consequences)"),
 (f"{ADR}/{NEW}", r"^4\. One rule for every document, with no prefix exemptions.*$", lambda m: "4. The exemptions are by name and by folder, never by judgment: the program applies them mechanically, so an agent never has to decide whether a file is \"transient\"."),
 (f"{ADR}/{NEW}", r"^6\. \*\*No exemption by name or prefix\.\*\*.*$", lambda m: "6. **The exemptions are exactly these.** The program applies them mechanically: files whose names start with `tmp-`; folders named `stencils`, `quarantine`, `backups`, `catalogue` or `logs`; folders whose names start with `.` or `tmp-`; any folder that contains `anvil.yaml` (an Anvil app root) and everything below it; anything inside an `obsolete` folder (indexed as a link target, never edited); installed skills (`SKILL.md`, which carry `name` and `description`); and empty files. Every other document in the eight repositories carries the three fields. Further fields (for example `state` and `date-created` on fact files) are allowed where a document type defines them; the hook leaves them alone."),
 (f"{ADR}/{NEW}", r"^- \*\*.*is superseded in full\.\*\*.*$", lambda m: "- **[[adr-frontmatter-exemption-transient-files]] is superseded in part.** Its list of frontmatter fields (`doc-id`, `state`, `date-created`) is replaced by the three fields above. Its exemption of `tmp-` files stays in force and is restated in Decision item 6; the five `tmp-*.md` files in `templates-global` still carry no frontmatter and are not treated as needing a fix."),
 (f"{ADR}/{OLD2}", r"^Status: Superseded in full by .*$", lambda m: "Status: Accepted. Its list of frontmatter fields is superseded by [[adr-document-frontmatter-and-identity]] (2026-10-01); its exemption of `tmp-` files stays in force"),
 (f"{OS}/frontmatter conventions.md", r"^(This applies to every document in the eight documentation repositories, including documentation skills\.)", lambda m: m.group(1) + SK),
 (f"{OS}/documentation-linking-explainer.md", r"^(\*\*Three frontmatter fields\.\*\* Every document starts with `title`, `doc-id` and `updated`)\.", lambda m: m.group(1) + ", except the files and folders listed in [[doc-check-config]]."),
 (f"{CFG}/gbrain-doc-contract.md", r"^(- \*\*C1\*\* — Every documentation file, including documentation skills.*by hand\.)$", lambda m: m.group(1) + SK),
]
bad = 0
by_file = {}
DONE = ["(in part: its list of frontmatter fields)", "The exemptions are by name and by folder", "The exemptions are exactly these", "is superseded in part.** Its list of frontmatter fields", "its exemption of `tmp-` files stays in force", "[[doc-check-config]]", "[[doc-check-config]]", "[[doc-check-config]]"]
assert len(DONE) == len(EDITS)
for (f, rx, rep), done in zip(EDITS, DONE): by_file.setdefault(f, []).append((rx, rep, done))
for f, edits in by_file.items():
    try:
        with open(f, encoding="utf-8", newline="") as fh: text = fh.read()
    except OSError:
        print(f"   NOT FOUND   {f}"); bad += 1; continue
    new = text
    for rx, rep, done in edits:
        if done in new:
            continue                                  # already done on an earlier run
        n = len(re.findall(rx, new, re.M))
        if n != 1:
            print(f"   NOT CHANGED {os.path.basename(f)}: expected line found {n} time(s): {rx[:50]}"); bad += 1; continue
        new = re.sub(rx, rep, new, count=1, flags=re.M)
    if new != text:
        with open(f, "w", encoding="utf-8", newline="") as fh: fh.write(new)
        print(f"   changed     {os.path.basename(f)}")
print("\n" + ("Some edits did not match. Paste this screen to Claude." if bad else "All edits done. Now run commit-all.sh."))
sys.exit(1 if bad else 0)
