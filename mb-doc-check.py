#!/usr/bin/env python3
"""mb-doc-check - keeps the links between your documents alive, at commit time.

THE ONE LINK FORM. Every link in every document is stored in the same standard form:

    [[[source-id:page-name|Shown text]]](relative/path/File%20Name.md)

  - The part inside the brackets is what GBrain reads (source id and page name, so links also work
    between repositories). The part in round brackets is what MarkText opens when you click.
  - Anyone (you or an AI) simply writes  [[name]]  or  [[name|text]]  - the commit hook turns it into the
    standard form and keeps it correct when files are renamed, moved or deleted.
  - A name that exists in the linking document's own repository wins over the same name elsewhere.
  - A document PATH pasted into running text (C:\\..., \\\\wsl.localhost\\..., /mnt/c/..., file:///..., or a
    path relative to the document or to its repository) is turned into the same standard link. A path written
    in `backticks` or in a code block is a literal location and is never touched.

Every document carries a permanent code in its frontmatter, for example
    doc-id: "mb-3fa91c2e"
  The script adds it by itself and never changes it, so the script always knows which document is which,
  however much of a file you rewrite.

  Each time you run `git commit` (through the git hook) the script:
    1. makes the frontmatter of every committed document complete: title, permanent code and the date
       (updated: "YYYY-MM-DD"). The date becomes today's date only when the document really has something
       to commit (it is new, moved, or anything besides its date line differs from the last commit);
    2. finds every document that was renamed or moved, and rewrites the links to it;
    3. writes every link of the committed documents in the standard form (paths recomputed);
    4. turns links to a deleted document into plain words; links follow a document into obsolete/;
    5. stops the commit if a link YOU just typed points to nothing, or to a name that several files share,
       and tells you exactly which line;
    6. adds every file it repaired to the same commit.

  The script never moves, renames or deletes a file. obsolete/ folders are never scanned or changed.
  SKILL.md files (installed OpenCode skills) are never touched.

Files next to this script:
  mb-doc-check.sources   which folder is which GBrain source (one line each:  source-id = /mnt/c/path)
                         and, optionally, the line  @paths = absolute  (the path part of every link is then the
                         full Windows path, for example C:/mybizz/x/y.md; the default is relative)
                         and, optionally, the line  @eol = lf  (every committed document is stored with LF line
                         endings; without the line the endings are left as they are)
  mb-doc-check.roots     optional: further folders that may be linked to

Commands:
  hook           what git runs at commit time (add --dry-run to change nothing)
  check          read-only health report of every link in the folders given
  links-report   read-only: count the links of every repository by kind (before a rollout)
  rollout        one-time: put every link of ONE repository into the standard form (dry run unless --write)
  fix-broken     one-time: turn every link that points to nothing into plain words (dry run unless --write)
  eol            one-time: give every document of ONE repository LF line endings (dry run unless --write)
  slug-selftest  compare this script's page-name rule with GBrain's own, on your real files
  sources-check  compare mb-doc-check.sources with GBrain's own list of sources
  migrate        one-time: give every document its permanent code (needs --write)
  collisions     list file names that are used by more than one document
  install-hook   put the hook into a repository (never overwrites an existing hook)
"""
from __future__ import annotations

import argparse
import collections
import datetime
import json
import os
import re
import secrets
import subprocess
import sys
import unicodedata
from urllib.parse import quote, unquote

BOM = b"\xef\xbb\xbf"
PRUNE_DIRS = {".git", "node_modules", "__pycache__"}
TREATMENT_DIRS = {"stencils", "quarantine", "backups", "catalogue", "logs"}
OBSOLETE = "obsolete"
ID_RE = re.compile(r"^mb-[0-9a-f]{8}$")

WIKI_RE = re.compile(r"\[\[([^\[\]\n]+)\]\]")
PLAIN_RE = re.compile(r"(?<!!)\[([^\[\]\n]+)\]\(([^()\s]+)\)")
URL_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")
QUAL_RE = re.compile(r"^([A-Za-z0-9-]+):(.+)$")
DRIVE_RE = re.compile(r"^([A-Za-z]):[\\/](.*)$")
FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
# The standard stored form of every link:  [[[source-id:slug|Shown text]]](relative/path/File%20Name.md)
ABS_START = re.compile(r"(?:(?<![A-Za-z0-9_])[A-Za-z]:[\\/]|\\\\wsl(?:\.localhost|\$)\\|(?<![\w/:])/(?:mnt/[a-z]|home|tmp|root|opt|srv|var|usr|media)/|file:///)", re.I)
REL_PATH = re.compile(r"(?<![\w/\\.:@%~+-])(?:\.{1,2}[\\/])*[\w.\-+%@~]+(?:[\\/][\w.\-+%@~]+)*\.md(?![A-Za-z0-9_-])(?!\.[A-Za-z0-9])", re.I)
MD_END = re.compile(r"\.md(?![A-Za-z0-9_-])(?!\.[A-Za-z0-9])", re.I)
ANCHOR_RE = re.compile(r"#[^\s)\]>`]*")
PATHISH_INNER = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\wsl|/mnt/[a-z]/|file:///|\.{1,2}[\\/])", re.I)
CANON_RE = re.compile(r"\[\[\[([^\[\]\n]+)\]\]\]\(([^()\n]*)\)")


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def read_bytes(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def write_bytes(path: str, data: bytes) -> None:
    with open(path, "wb") as f:
        f.write(data)


def stem_of(path: str) -> str:
    b = os.path.basename(path)
    return b[:-3] if b.lower().endswith(".md") else b


def is_md(path: str) -> bool:
    return path.lower().endswith(".md")


def rel(p: str, root: str) -> str:
    try:
        return os.path.relpath(p, root)
    except ValueError:
        return p


# ---------------------------------------------------------------------------
# GBrain slugs and the map "which folder is which GBrain source"
# ---------------------------------------------------------------------------
_VS_RE = re.compile("[\uFE00-\uFE0F\U000E0100-\U000E01EF]")


def slugify_segment(seg: str) -> str:
    """Port of GBrain's slugifySegment (src/core/sync.ts). `slug-selftest` compares it with GBrain itself."""
    s = unicodedata.normalize("NFD", seg)
    s = re.sub("[\u0300-\u036f]", "", s)
    s = re.sub("[\u0591-\u05c7]", "", s)
    s = unicodedata.normalize("NFC", s)
    s = _VS_RE.sub("", s)
    s = s.lower()
    keep = []
    for ch in s:
        cat = unicodedata.category(ch)
        if cat in ("Ll", "Lm", "Lo", "Mn", "Mc", "Me", "Nd", "Nl", "No") or ch in "._-" or ch.isspace():
            keep.append(ch)
    s = "".join(keep)
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"-+", "-", s)
    return re.sub(r"^-|-$", "", s)


def slugify_path(rel_path: str) -> str:
    p = re.sub(r"\.mdx?$", "", rel_path, flags=re.I)
    p = p.replace("\\", "/")
    p = re.sub(r"^\.?/", "", p)
    return "/".join(x for x in (slugify_segment(seg) for seg in p.split("/")) if x)


class SourceMap:
    """source-id <-> folder, read from mb-doc-check.sources (next to the script) or $MB_DOC_CHECK_SOURCES.
    One line per source:  source-id = /mnt/c/path/to/repo   (# starts a comment)."""

    def __init__(self, mapping=None, paths="relative", eol="keep"):
        self.paths = paths if paths in ("relative", "absolute") else "relative"
        self.eol = eol if eol in ("keep", "lf") else "keep"
        self.by_id = {}
        for sid, path in (mapping or {}).items():
            self.by_id[sid] = os.path.abspath(path)
        self.enabled = bool(self.by_id)

    @classmethod
    def load(cls):
        path = os.environ.get("MB_DOC_CHECK_SOURCES") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "mb-doc-check.sources")
        mapping, paths, eol = {}, "relative", "keep"
        if os.path.exists(path):
            for line in open(path, encoding="utf-8"):
                line = line.split("#", 1)[0].strip()
                if "=" in line:
                    sid, p = line.split("=", 1)
                    if sid.strip() == "@paths":
                        paths = p.strip().lower()
                    elif sid.strip() == "@eol":
                        eol = p.strip().lower()
                    else:
                        mapping[sid.strip()] = win_to_wsl(p.strip())
        return cls(mapping, paths, eol)

    def knows(self, sid: str) -> bool:
        return sid in self.by_id

    def source_of(self, path: str):
        p = os.path.abspath(path)
        best = None
        for sid, root in self.by_id.items():
            if p == root or p.startswith(root + os.sep):
                if best is None or len(root) > len(self.by_id[best]):
                    best = sid
        return best

    def slug_of(self, path: str):
        sid = self.source_of(path)
        if sid is None:
            return None
        return slugify_path(os.path.relpath(os.path.abspath(path), self.by_id[sid]).replace(os.sep, "/"))

    def linkable(self, from_path: str, to_path: str) -> bool:
        """A relative path only works when both files are on the same Windows drive (/mnt/<drive>/...)."""
        if os.environ.get("MB_DOC_CHECK_ANYPATH") == "1":
            return True
        if self.paths == "absolute":
            b = os.path.abspath(to_path).split("/")
            return len(b) > 3 and b[1] == "mnt" and len(b[2]) == 1
        a, b = os.path.abspath(from_path).split("/"), os.path.abspath(to_path).split("/")
        return len(a) > 3 and len(b) > 3 and a[1] == "mnt" and b[1] == "mnt" and a[2] == b[2]


SOURCES = SourceMap()


# ---------------------------------------------------------------------------
# finding documents
# ---------------------------------------------------------------------------
def _skip_dir_name(name: str) -> bool:
    n = name.lower()
    return name.startswith(".") or name in PRUNE_DIRS or n in TREATMENT_DIRS or n.startswith("tmp-")


def scan_tree(root: str):
    """(live_files, obsolete_files). obsolete/ files are only indexed, never edited."""
    live, obs = [], []
    root = os.path.abspath(root)
    for dirpath, dirnames, filenames in os.walk(root):
        if os.path.exists(os.path.join(dirpath, "anvil.yaml")):
            dirnames[:] = []
            continue
        relp = os.path.relpath(dirpath, root)
        in_obs = any(p.lower() == OBSOLETE for p in relp.split(os.sep))
        keep = []
        for d in dirnames:
            if _skip_dir_name(d) or os.path.exists(os.path.join(dirpath, d, "anvil.yaml")):
                continue
            keep.append(d)
        dirnames[:] = sorted(keep)
        for fn in sorted(filenames):
            low = fn.lower()
            if not low.endswith(".md") or fn.startswith(".") or low.startswith("tmp-"):
                continue
            (obs if in_obs else live).append(os.path.join(dirpath, fn))
    return live, obs


class Corpus:
    def __init__(self, roots, live_files=None, obs_files=None):
        self.roots = list(dict.fromkeys(os.path.abspath(r) for r in roots))     # a folder listed twice is one folder
        if live_files is None:
            live_files, obs_files = [], []
            for r in self.roots:
                lf, of = scan_tree(r)
                live_files += lf
                obs_files += of
        self.live_files = list(dict.fromkeys(live_files))                      # and a document is never counted twice
        self.obs_files = list(dict.fromkeys(obs_files or []))
        self.live, self.obs = {}, {}
        for p in self.live_files:
            self.live.setdefault(stem_of(p), []).append(p)
        for p in self.obs_files:
            self.obs.setdefault(stem_of(p), []).append(p)
        self.live_set = set(self.live_files)
        self.obs_set = set(self.obs_files)

    def slug_hits(self, source: str, slug: str, obs: bool = False):
        if not hasattr(self, "_slug_index"):
            self._slug_index = {}
            for is_obs, files in ((False, self.live_files), (True, self.obs_files)):
                for f in files:
                    sid = SOURCES.source_of(f)
                    if sid is None:
                        continue
                    self._slug_index.setdefault((is_obs, sid, SOURCES.slug_of(f)), []).append(f)
        return self._slug_index.get((obs, source, slug), [])

    def stem_hits(self, stem: str, obs: bool = False):
        """Documents with this file name. An exact-case match wins; otherwise the match ignores case,
        because GBrain slugs are lower case and Windows file names are not case sensitive."""
        table = self.obs if obs else self.live
        if stem in table:
            return table[stem]
        attr = "_obs_ci" if obs else "_live_ci"
        if not hasattr(self, attr):
            ci = {}
            for k, v in table.items():
                ci.setdefault(k.lower(), []).extend(v)
            setattr(self, attr, ci)
        return getattr(self, attr).get(stem.lower(), [])

    def lower_path(self, path: str):
        """Case-insensitive lookup (Windows paths ignore case); only when the match is unique."""
        if not hasattr(self, "_lower"):
            self._lower = {}
            for f in self.live_files + self.obs_files:
                self._lower.setdefault(f.lower(), []).append(f)
        hits = self._lower.get(path.lower(), [])
        return hits[0] if len(hits) == 1 else None

    def root_of(self, path: str):
        p = os.path.abspath(path)
        best = None
        for r in self.roots:
            if p == r or p.startswith(r + os.sep):
                if best is None or len(r) > len(best):
                    best = r
        return best

    def rel_noext(self, path: str) -> str:
        r = self.root_of(path) or os.path.dirname(path)
        relp = os.path.relpath(os.path.abspath(path), r).replace(os.sep, "/")
        return relp[:-3] if relp.lower().endswith(".md") else relp


# ---------------------------------------------------------------------------
# frontmatter: title and permanent code (everything else is left alone)
# ---------------------------------------------------------------------------
def fm_state(raw: bytes):
    """(state, lines, open_index, close_index); raw has no BOM.
    state: empty | none | ok | unclosed | nullbytes"""
    if b"\x00" in raw:
        return "nullbytes", [], None, None
    lines = raw.splitlines(keepends=True)
    first = next((i for i, l in enumerate(lines) if l.strip()), None)
    if first is None:
        return "empty", lines, None, None
    if lines[first].strip() != b"---":
        return "none", lines, None, None
    for j in range(first + 1, len(lines)):
        if lines[j].strip() == b"---":
            return "ok", lines, first, j
    return "unclosed", lines, first, None


def _nobom(raw: bytes) -> bytes:
    return raw[3:] if raw.startswith(BOM) else raw


DOCID_LINE = re.compile(rb"^doc-id\s*:")


def read_id(raw: bytes):
    state, lines, o, c = fm_state(_nobom(raw))
    if state != "ok":
        return None
    for ln in lines[o + 1:c]:
        if DOCID_LINE.match(ln):
            v = ln.split(b":", 1)[1].decode("utf-8", "replace").strip().strip("\"'").strip()
            return v if ID_RE.match(v) else None
    return None


def title_line(stem: str) -> str:
    if '"' not in stem:
        return f'title: "{stem}"'
    if "'" not in stem:
        return f"title: '{stem}'"
    return 'title: "' + stem.replace("\\", "\\\\").replace('"', '\\"') + '"'


TITLE_LINE = re.compile(rb"^title\s*:(.*)$", re.I)


def has_title(raw: bytes) -> bool:
    """True when the frontmatter has a title with a value. Only well-formed frontmatter can have one."""
    state, lines, o, c = fm_state(_nobom(raw))
    if state != "ok":
        return False
    inner = lines[o + 1:c]
    for i, ln in enumerate(inner):
        mm = TITLE_LINE.match(ln)
        if mm:
            if mm.group(1).strip() in (b"", b'""', b"''"):
                return bool(i + 1 < len(inner) and re.match(rb"^[ \t]+\S", inner[i + 1]))
            return True
    return False


UPDATED_LINE = re.compile(rb"^updated\s*:", re.I)


def today_str() -> str:
    return os.environ.get("MB_DOC_CHECK_TODAY") or datetime.date.today().isoformat()


def set_updated(raw: bytes, today: str, only_if_missing: bool = False):
    """Write  updated: "YYYY-MM-DD"  into well-formed frontmatter. Returns the new bytes (unchanged when there is
    nothing to do or the frontmatter is not well formed)."""
    bom = raw.startswith(BOM)
    body = _nobom(raw)
    state, lines, o, c = fm_state(body)
    if state != "ok":
        return raw
    eol = b"\r\n" if lines[o].endswith(b"\r\n") else b"\n"
    new_line = f'updated: "{today}"'.encode() + eol
    inner = lines[o + 1:c]
    idx = [i for i, ln in enumerate(inner) if UPDATED_LINE.match(ln)]
    if idx:
        if only_if_missing:
            return raw
        i = idx[0]
        if i + 1 < len(inner) and re.match(rb"^[ \t]+\S", inner[i + 1]):
            return raw                      # a multi-line value: not ours to rewrite
        inner = inner[:i] + [new_line] + inner[i + 1:]
        inner = [ln for k, ln in enumerate(inner) if k == i or not UPDATED_LINE.match(ln)]
    else:
        pos = next((i + 1 for i, ln in enumerate(inner) if DOCID_LINE.match(ln)), len(inner))
        while pos < len(inner) and re.match(rb"^[ \t]+\S", inner[pos]):
            pos += 1
        inner = inner[:pos] + [new_line] + inner[pos:]
    new = b"".join(lines[: o + 1] + inner + lines[c:])
    return (BOM if bom else b"") + new


def strip_date(raw: bytes) -> bytes:
    """The document with its 'updated' line taken out (only well-formed frontmatter has one)."""
    bom = raw.startswith(BOM)
    state, lines, o, c = fm_state(_nobom(raw))
    if state != "ok":
        return raw
    inner = [ln for ln in lines[o + 1:c] if not UPDATED_LINE.match(ln)]
    return (BOM if bom else b"") + b"".join(lines[: o + 1] + inner + lines[c:])


def has_date(raw: bytes) -> bool:
    state, lines, o, c = fm_state(_nobom(raw))
    return state == "ok" and any(UPDATED_LINE.match(ln) for ln in lines[o + 1:c])


def to_lf(raw: bytes) -> bytes:
    return re.sub(rb"\r\n?", b"\n", raw)


def has_cr(raw: bytes) -> bool:
    return b"\r" in raw


def date_value(raw: bytes):
    state, lines, o, c = fm_state(_nobom(raw))
    if state != "ok":
        return None
    for ln in lines[o + 1:c]:
        if UPDATED_LINE.match(ln):
            mm = re.match(rb'^updated\s*:\s*"?([^"\r\n]*?)"?\s*$', ln, re.I)
            return mm.group(1).decode("utf-8", "replace") if mm else None
    return None


def date_decision(out: bytes, base, moved: bool, today: str):
    """Decide the date of a document that is part of this commit. Returns (bytes, stamped).
    The date moves to today only when the document really has something to commit: it is new, it was
    moved or renamed, or anything other than its date line differs from the committed version."""
    if base is None or moved or to_lf(strip_date(out)) != to_lf(strip_date(base)):
        new = set_updated(out, today)
        return new, True
    if has_date(base):
        d = date_value(base)
        if d is None:
            return base, False
        # only the date line or the line endings differ: the old date stays, the (new) line endings are kept
        return set_updated(out, d), False
    return out, False             # the date is being added for the first time to a document that had none


def set_code(raw: bytes, stem: str, code: str):
    """Return (new_raw, note). Makes the frontmatter complete: a title (from the file name, only when the
    document has none) and the permanent doc-id. Every other line is left exactly as it is.
    note is 'ok' or a reason the file was not changed."""
    bom = raw.startswith(BOM)
    body = _nobom(raw)
    state, lines, o, c = fm_state(body)
    line_code = f'doc-id: "{code}"'
    if state == "none":
        block = ("---\n" + title_line(stem) + "\n" + line_code + "\n" + f'updated: "{today_str()}"' + "\n---\n").encode("utf-8", "surrogateescape")
        return block + body, "ok"
    if state != "ok":
        return None, state
    eol = b"\r\n" if lines[o].endswith(b"\r\n") else b"\n"
    new_line = line_code.encode() + eol
    out, replaced, k = [], False, o + 1
    inner = lines[o + 1:c]
    need_title = not has_title(raw)
    title_bytes = title_line(stem).encode("utf-8", "surrogateescape") + eol
    i = 0
    while i < len(inner):
        ln = inner[i]
        if need_title and TITLE_LINE.match(ln):          # an empty "title:" is filled in
            out.append(title_bytes)
            need_title = False
            i += 1
            continue
        if DOCID_LINE.match(ln):
            if i + 1 < len(inner) and re.match(rb"^[ \t]+\S", inner[i + 1]):
                return None, "multiline-doc-id"
            if not replaced:
                out.append(new_line)
                replaced = True
            i += 1
            continue
        out.append(ln)
        i += 1
    if not replaced:
        out.append(new_line)
    if need_title:
        out.insert(0, title_bytes)
    new_lines = lines[: o + 1] + out + lines[c:]
    return (BOM if bom else b"") + b"".join(new_lines), "ok"


def new_code(taken: set) -> str:
    while True:
        c = "mb-" + secrets.token_hex(4)
        if c not in taken:
            taken.add(c)
            return c


# ---------------------------------------------------------------------------
# links
# ---------------------------------------------------------------------------
def path_to_doc(token: str, from_path: str, corpus: "Corpus"):
    """A pasted path (Windows, WSL network, /mnt/..., file:///, relative) -> ("ok"|"obsolete"|"missing", file)."""
    variants = [token]
    if "%" in token:
        variants.append(unquote(token))
    best_obs = None
    for s in variants:
        s = s.strip()
        if s.lower().startswith("file:///"):
            s = s[8:]
            if not re.match(r"^[A-Za-z]:", s) and not s.startswith("/"):
                s = "/" + s
        s = s.replace("\\", "/")
        mm = re.match(r"^//wsl(?:\.localhost|\$)/[^/]+(/.*)$", s, re.I)
        if mm:
            s = mm.group(1)
        elif re.match(r"^[A-Za-z]:/", s):
            s = "/mnt/%s/%s" % (s[0].lower(), s[3:])
        if s.startswith("/"):
            cands = [s]
        else:
            own = corpus.root_of(from_path)
            cands = [os.path.join(os.path.dirname(from_path), s)] + [os.path.join(r, s) for r in ([own] if own else []) + [r for r in corpus.roots if r != own]]
        for cand in cands:
            n = os.path.normpath(cand)
            if n in corpus.live_set:
                return "ok", n
            low = corpus.lower_path(n)
            if low is not None and low in corpus.live_set:
                return "ok", low
            if n in corpus.obs_set and best_obs is None:
                best_obs = n
    return ("obsolete", best_obs) if best_obs else ("missing", None)


def strip_target(t: str) -> str:
    t = t.strip()
    if "#" in t:
        t = t.split("#", 1)[0]
    if t.lower().endswith(".md"):
        t = t[:-3]
    return t.strip()


def parse_wikilink(inner: str):
    inner = inner.strip()
    if URL_RE.match(inner):
        return {"kind": "external"}
    inner = norm_inner(inner)
    target, _, _ = inner.partition("|")
    if PATHISH_INNER.match(target.strip()):
        return {"kind": "path", "target": target.split("#", 1)[0].strip()}
    t = strip_target(target)
    m = QUAL_RE.match(t)
    if m and "\\" not in t and "/" not in m.group(1):
        return {"kind": "qualified", "source": m.group(1), "target": m.group(2)}
    return {"kind": "dir_slug" if "/" in t else "bare", "target": t}


def protected_ranges(text: str):
    """Ranges where links must not be touched: frontmatter, fenced code blocks, and inline
    code spans (which may span several lines; an unmatched backtick run is literal text)."""
    ranges = []
    lines = text.splitlines(keepends=True)
    idx = next((i for i, l in enumerate(lines) if l.strip()), None)
    start_i = 0
    if idx is not None and lines[idx].strip() == "---":
        for j in range(idx + 1, len(lines)):
            if lines[j].strip() == "---":
                ranges.append((0, sum(len(x) for x in lines[: j + 1])))
                start_i = j + 1
                break
    pos = sum(len(x) for x in lines[:start_i])
    fence, seg = None, None
    open_run = None                       # (length, start offset) of an unclosed inline run
    for i in range(start_i, len(lines)):
        ln = lines[i]
        m = FENCE_RE.match(ln)
        if fence is None and m:
            fence, seg = (m.group(1)[0], len(m.group(1))), pos
            open_run = None               # a fence ends the paragraph: the pending run is literal
        elif fence is not None and m and m.group(1)[0] == fence[0] and len(m.group(1)) >= fence[1] and ln.strip().strip(fence[0]) == "":
            ranges.append((seg, pos + len(ln)))
            fence, seg = None, None
        elif fence is None:
            j = 0
            while j < len(ln):
                if ln[j] == "`":
                    k = j
                    while k < len(ln) and ln[k] == "`":
                        k += 1
                    n = k - j
                    if open_run is not None and n == open_run[0]:
                        ranges.append((open_run[1], pos + k))
                        open_run = None
                    elif open_run is None:
                        open_run = (n, pos + j)
                    j = k
                else:
                    j += 1
        pos += len(ln)
    if fence is not None:
        ranges.append((seg, pos))
    return ranges


def _in(ranges, a: int) -> bool:
    return any(s <= a < e for s, e in ranges)


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def wikilink_matches(text: str):
    prot = protected_ranges(text)
    return [m for m in WIKI_RE.finditer(text) if not _in(prot, m.start())]


def resolve(parsed, corpus: Corpus, from_path=None):
    """(status, hits). status: skip | ok | ok_indirect | ambiguous | obsolete | missing.
    A name that exists in the linking document's own repository wins over the same name elsewhere."""
    k = parsed["kind"]
    if k == "external":
        return "skip", []
    if k == "path":
        tp = parsed["target"] if parsed["target"].lower().endswith(".md") else parsed["target"] + ".md"
        st, hit = path_to_doc(tp, from_path or "", corpus)
        return (st, [hit]) if hit else ("missing", [])
    if k == "qualified":
        if not SOURCES.enabled or not SOURCES.knows(parsed["source"]):
            return "skip", []
        slug = slugify_path(parsed["target"])
        hits = corpus.slug_hits(parsed["source"], slug)
        if len(hits) == 1:
            return "ok", hits
        if len(hits) > 1:
            return "ambiguous", hits
        oh = corpus.slug_hits(parsed["source"], slug, obs=True)
        if oh:
            return "obsolete", oh
        return "missing", []
    t = parsed["target"]
    own = corpus.root_of(from_path) if from_path else None
    roots = ([own] if own else []) + [r for r in corpus.roots if r != own]
    if k == "dir_slug":
        for r in roots:
            cand = os.path.join(r, *t.split("/")) + ".md"
            if cand in corpus.live_set:
                return "ok", [cand]
            low = corpus.lower_path(cand)
            if low is not None and low in corpus.live_set:
                return "ok", [low]
        for r in roots:
            cand = os.path.join(r, *t.split("/")) + ".md"
            if cand in corpus.obs_set:
                return "obsolete", [cand]
            low = corpus.lower_path(cand)
            if low is not None and low in corpus.obs_set:
                return "obsolete", [low]
        slug = t.split("/")[-1]
    else:
        slug = t
    hits = corpus.stem_hits(slug)
    if len(hits) > 1 and own:
        mine = [h for h in hits if corpus.root_of(h) == own]
        if mine:
            hits = mine
    if len(hits) == 1:
        return ("ok" if k == "bare" else "ok_indirect"), hits
    if len(hits) > 1:
        return "ambiguous", hits
    ohits = corpus.stem_hits(slug, obs=True)
    if ohits:
        return "obsolete", ohits
    return "missing", []


def rebuild(inner: str, new_target: str) -> str:
    inner = norm_inner(inner)
    target, sep, disp = inner.partition("|")
    anchor = "#" + target.split("#", 1)[1].strip() if "#" in target else ""
    return new_target + anchor + (sep + disp if sep else "")


def prose_of(inner: str) -> str:
    inner = norm_inner(inner)
    target, _, disp = inner.partition("|")
    if disp.strip() and any(unicodedata.category(ch)[0] in "LN" for ch in disp):
        return disp.strip()
    t = strip_target(target)
    m = QUAL_RE.match(t)
    if m and "/" not in m.group(1) and SOURCES.knows(m.group(1)):
        t = m.group(2)
    return t.split("/")[-1] if t else inner


def convert_pasted_paths(text: str, file_path: str, corpus: "Corpus"):
    """A document path pasted into running text (not in code, not already a link) becomes the standard link.
    Returns (text, changes, unresolved)."""
    if not SOURCES.enabled:
        return text, [], []
    prot = protected_ranges(text)
    occupied = [(m.start(), m.end()) for rx in (CANON_RE, WIKI_RE, PLAIN_RE) for m in rx.finditer(text)]
    occupied += [(m.start(), m.end()) for m in re.finditer(r"<[^<>\n]*>|https?://\S+", text)]

    def busy(a: int, b: int) -> bool:
        return _in(prot, a) or any(s < b and a < e for s, e in occupied)

    edits, changes, unresolved, taken_to = [], [], [], 0

    def add(a, end, hit):
        if os.path.abspath(hit) == os.path.abspath(file_path):
            return end                      # a document naming its own path states where it lives; no link to itself
        anc = ANCHOR_RE.match(text, end)
        anchor = anc.group(0)[1:] if anc else ""
        new = canonical_link(file_path, hit, "x" + ("#" + anchor if anchor else ""))
        if new is None:
            return end
        stop = anc.end() if anc else end
        edits.append((a, stop, new))
        changes.append((line_of(text, a), text[a:stop], new))
        return stop

    for sm in ABS_START.finditer(text):
        a = sm.start()
        if a < taken_to or busy(a, a + 1):
            continue
        limit, found, first = min(len(text), a + 300), None, None
        for em in MD_END.finditer(text, a, limit):
            seg = text[a:em.start()]
            if "\n" in seg or any(ch in seg for ch in '<>"|*?[]`'):
                break
            tok = text[a:em.end()]
            first = first or tok
            st, hit = path_to_doc(tok, file_path, corpus)
            if st in ("ok", "obsolete"):
                found = (em.end(), hit)
                break
        if found:
            taken_to = add(a, found[0], found[1])
        elif first:
            unresolved.append((line_of(text, a), first))
    for rm in REL_PATH.finditer(text):
        a, e = rm.start(), rm.end()
        tok = rm.group(0)
        if a < taken_to or busy(a, e) or ("/" not in tok and "\\" not in tok):
            continue
        st, hit = path_to_doc(tok, file_path, corpus)
        if st in ("ok", "obsolete"):
            add(a, e, hit)
        else:
            unresolved.append((line_of(text, a), tok))
    # overlapping edits (an absolute path can also contain a relative-looking tail): keep the earliest
    edits.sort()
    kept, last = [], -1
    for s_, e_, n_ in edits:
        if s_ >= last:
            kept.append((s_, e_, n_))
            last = e_
    chg = [c for c in changes if any(text[s_:e_] == c[1] and n_ == c[2] for s_, e_, n_ in kept)]
    return apply_edits(text, kept), chg, unresolved


def norm_inner(inner: str) -> str:
    """A link written inside a markdown table escapes its pipe as \\| ; read it as an ordinary pipe."""
    return inner.replace("\\|", "|")


def in_table_row(text: str, pos: int) -> bool:
    ls = text.rfind("\n", 0, pos) + 1
    return text[ls:pos + 1].lstrip().startswith("|") or text[ls:].lstrip().startswith("|")


def qualified_ref(dest: str):
    """`source-id:slug` for a document, or None when the map does not know its folder."""
    if not SOURCES.enabled:
        return None
    sid = SOURCES.source_of(dest)
    return None if sid is None else f"{sid}:{SOURCES.slug_of(dest)}"


def canonical_link(from_path: str, target: str, inner: str, in_table: bool = False):
    """The standard stored form of one link, or None when it cannot be written.
    Inside a markdown table row the pipe in front of the display text is written \\| so the table keeps its columns."""
    inner = norm_inner(inner)
    tgt_part, sep, disp = inner.partition("|")
    anchor = tgt_part.split("#", 1)[1].strip() if "#" in tgt_part else ""
    ref = qualified_ref(target)
    if ref is None:
        return None
    inner_out = ref + ("#" + anchor if anchor else "") + (((("\\|") if in_table else "|") + disp) if sep else "")
    if not SOURCES.linkable(from_path, target):
        return "[[" + inner_out + "]]"          # no clickable path exists (for example a WSL-only folder)
    if SOURCES.paths == "absolute":
        parts = os.path.abspath(target).split("/")
        if len(parts) > 3 and parts[1] == "mnt" and len(parts[2]) == 1:
            ap = parts[2].upper() + ":/" + "/".join(parts[3:])
        else:
            ap = os.path.abspath(target)                 # not on a Windows drive (only used by tests)
        return "[[[" + inner_out + "]]](" + quote(ap, safe="/-._~:") + ")"
    rp = os.path.relpath(os.path.abspath(target), os.path.dirname(os.path.abspath(from_path))).replace(os.sep, "/")
    return "[[[" + inner_out + "]]](" + quote(rp, safe="/-._~") + ")"


def unwrap(text: str) -> str:
    """[[[inner]]](path) -> [[inner]]. The path part is only ever a view of the inner part."""
    if not SOURCES.enabled:
        return text
    prot = protected_ranges(text)

    def repl(m):
        if _in(prot, m.start()):
            return m.group(0)
        parsed = parse_wikilink(m.group(1))
        if parsed["kind"] != "qualified" or not SOURCES.knows(parsed["source"]):
            return m.group(0)                  # not one of ours: leave it exactly as it is
        return "[[" + m.group(1) + "]]"
    return CANON_RE.sub(repl, text)


def wrap(text: str, from_path: str, corpus: Corpus):
    """[[inner]] -> the standard form, for every link that resolves; links already in the standard form
    are refreshed (their path part is recomputed). Returns (text, changes)."""
    if not SOURCES.enabled:
        return text, []
    prot = protected_ranges(text)
    edits, changes = [], []
    spans = []
    for m in CANON_RE.finditer(text):
        if _in(prot, m.start()):
            continue
        spans.append((m.start(), m.end()))
        st, hits = resolve(parse_wikilink(m.group(1)), corpus, from_path)
        if st in ("ok", "ok_indirect", "obsolete"):
            new = canonical_link(from_path, hits[0], m.group(1), in_table_row(text, m.start()))
            if new is not None and new != m.group(0):
                edits.append((m.start(), m.end(), new))
                changes.append((line_of(text, m.start()), m.group(0), new))
    for m in WIKI_RE.finditer(text):
        if _in(prot, m.start()) or any(s <= m.start() < e for s, e in spans):
            continue
        parsed = parse_wikilink(m.group(1))
        if parsed["kind"] == "external":
            continue
        st, hits = resolve(parsed, corpus, from_path)
        if st not in ("ok", "ok_indirect", "obsolete"):
            continue
        new = canonical_link(from_path, hits[0], m.group(1), in_table_row(text, m.start()))
        if new is not None and new != m.group(0):
            edits.append((m.start(), m.end(), new))
            changes.append((line_of(text, m.start()), m.group(0), new))
    return apply_edits(text, edits), changes


def apply_edits(text: str, edits):
    for s, e, new in sorted(edits, reverse=True):
        text = text[:s] + new + text[e:]
    return text


def win_to_wsl(p: str) -> str:
    m = DRIVE_RE.match(p)
    return "/mnt/%s/%s" % (m.group(1).lower(), m.group(2).replace("\\", "/")) if m else p


def convert_plain_links(text: str, file_path: str, corpus: Corpus):
    """[label](path.md#a) -> [[stem#a|label]] when the target is a live document."""
    prot = protected_ranges(text)
    edits, changes = [], []
    for m in PLAIN_RE.finditer(text):
        if _in(prot, m.start()):
            continue
        label, target = m.group(1), m.group(2)
        if URL_RE.match(target) or target.startswith(("#", "mailto:")):
            continue
        path, _, anchor = target.partition("#")
        path = unquote(path)
        if not path.lower().endswith(".md"):
            continue
        p = win_to_wsl(path)
        cand = os.path.normpath(p if os.path.isabs(p) else os.path.join(os.path.dirname(file_path), p))
        if cand not in corpus.live_set:
            continue
        stem = stem_of(cand)
        ref = stem if len(corpus.live.get(stem, [])) == 1 else corpus.rel_noext(cand)
        inner = ref + ("#" + unquote(anchor) if anchor else "")
        if label.strip() != stem:
            inner += "|" + label.strip()
        new = "[[" + inner + "]]"
        edits.append((m.start(), m.end(), new))
        changes.append((line_of(text, m.start()), m.group(0), new))
    return apply_edits(text, edits), changes


# ---------------------------------------------------------------------------
# git
# ---------------------------------------------------------------------------
def git(repo: str, *args, check=True):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True)
    if check and r.returncode != 0:
        raise RuntimeError(r.stderr.decode("utf-8", "replace").strip())
    return r.stdout


def repo_top(path: str):
    try:
        return os.path.abspath(git(path, "rev-parse", "--show-toplevel").decode().strip())
    except (RuntimeError, OSError):
        return None


def _dec(b: bytes) -> str:
    return b.decode("utf-8", "surrogateescape")


def staged_changes(top: str):
    out = git(top, "diff", "--cached", "-M", "--name-status", "-z").split(b"\0")
    res, i = [], 0
    while i < len(out) and out[i]:
        st = out[i].decode()
        if st[0] in "RC":
            res.append({"status": "R", "old": os.path.join(top, _dec(out[i + 1])), "path": os.path.join(top, _dec(out[i + 2]))})
            i += 3
        else:
            res.append({"status": st[0], "path": os.path.join(top, _dec(out[i + 1])), "old": None})
            i += 2
    return res


def unstaged_files(top: str):
    out = git(top, "diff", "--name-only", "-z").split(b"\0")
    return {os.path.join(top, _dec(o)) for o in out if o}


def untracked_files(top: str):
    out = git(top, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0")
    return {os.path.join(top, _dec(o)) for o in out if o}


def head_listing(top: str):
    try:
        out = git(top, "ls-tree", "-r", "-z", "HEAD")
    except RuntimeError:
        return {}
    res = {}
    for rec in out.split(b"\0"):
        if not rec or b"\t" not in rec:
            continue
        meta, path = rec.split(b"\t", 1)
        parts = meta.split()
        if len(parts) == 3 and parts[1] == b"blob":
            res[_dec(path)] = parts[2].decode()
    return res


def read_blobs(top: str, shas):
    shas = sorted(set(shas))
    if not shas:
        return {}
    p = subprocess.run(["git", "-C", top, "cat-file", "--batch"], input=("\n".join(shas) + "\n").encode(), capture_output=True)
    out, pos, res = p.stdout, 0, {}
    for sha in shas:
        nl = out.index(b"\n", pos)
        header = out[pos:nl].split()
        size = int(header[2])
        pos = nl + 1
        res[sha] = out[pos:pos + size]
        pos += size + 1
    return res


def head_path_skipped(relp: str, anvil_dirs) -> bool:
    parts = relp.split("/")
    for d in parts[:-1]:
        if _skip_dir_name(d) or d.lower() == OBSOLETE:
            return True
    fn = parts[-1]
    if fn.startswith(".") or fn.lower().startswith("tmp-"):
        return True
    for i in range(len(parts)):
        if "/".join(parts[:i]) in anvil_dirs:
            return True
    return False


class OldView:
    """The documents as they were at the last commit (HEAD) of this repository,
    plus the current documents of any other folders."""

    def __init__(self, top, other_live_files, roots):
        listing = head_listing(top)
        anvil_dirs = {os.path.dirname(p) for p in listing if os.path.basename(p) == "anvil.yaml"}
        self.sha, paths = {}, []
        for relp, sha in listing.items():
            if not is_md(relp) or head_path_skipped(relp, anvil_dirs):
                continue
            ab = os.path.join(top, relp.replace("/", os.sep))
            self.sha[ab] = sha
            paths.append(ab)
        self.blobs = read_blobs(top, self.sha.values())
        self.id = {ab: read_id(self.blobs[s]) for ab, s in self.sha.items()}
        self.id_paths = {}
        for ab, c in self.id.items():
            if c:
                self.id_paths.setdefault(c, []).append(ab)
        self.corpus = Corpus(roots, live_files=paths + list(other_live_files), obs_files=[])

    def text(self, path):
        s = self.sha.get(path)
        return _dec(self.blobs[s]) if s else None


# ---------------------------------------------------------------------------
# the commit-time job
# ---------------------------------------------------------------------------
class Report:
    def __init__(self):
        self.codes_added = []
        self.titles_added = []
        self.dated = []
        self.eol_fixed = []
        self.reverted = []
        self.empty_commit = False
        self.pasted_converted = []
        self.pasted_unresolved = []
        self.repointed = []
        self.made_specific = []
        self.to_words = []
        self.converted_plain = []
        self.blocks = []
        self.old_problems = 0
        self.notes = []
        self.canonicalized = []
        self.changed = []
        self.other_repo_changed = []
        self.skipped_unstaged = []
        self.not_in_commit = 0


def load_roots_file():
    roots = []
    env = os.environ.get("MB_DOC_CHECK_ROOTS")
    if env:
        roots += [r for r in env.split(os.pathsep) if r]
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mb-doc-check.roots")
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#"):
                roots.append(win_to_wsl(line))
    return roots


def run_hook(top: str, extra_roots, dry=False, delete_ok=False):
    top = os.path.abspath(top)
    roots = [top] + [os.path.abspath(r) for r in extra_roots if os.path.abspath(r) != top]
    rep = Report()
    new = Corpus(roots)
    others = [p for p in new.live_files if not p.startswith(top + os.sep)]
    old = OldView(top, others, roots)
    changes = staged_changes(top)
    unstaged = unstaged_files(top)

    added, modified, deleted, renamed = set(), set(), set(), {}
    for ch in changes:
        np_, op_ = ch["path"], ch["old"]
        if not (is_md(np_) or (op_ and is_md(op_))):
            continue
        if ch["status"] == "A":
            added.add(np_)
        elif ch["status"] == "D":
            deleted.add(np_)
        elif ch["status"] == "R":
            renamed[op_] = np_
            deleted.add(op_)
            added.add(np_)
        else:
            modified.add(np_)
    staged_all = {p for p in (added | modified) if os.path.exists(p)}
    targets = sorted(p for p in staged_all if p in new.live_set and os.path.basename(p).upper() != "SKILL.MD"
                     and read_bytes(p).strip())

    # untracked / unstaged notice
    loose = {p for p in (unstaged | untracked_files(top)) if is_md(p) and (p in new.live_set or p in old.corpus.live_set)}
    rep.not_in_commit = len(loose)

    # --- step 1: codes ------------------------------------------------------
    raws, ids_now = {}, {}
    for p in targets:
        raws[p] = read_bytes(p)
        ids_now[p] = read_id(raws[p])
    taken = set(old.id_paths) | {c for c in ids_now.values() if c}
    holders = collections.defaultdict(list)
    for p, c in ids_now.items():
        if c:
            holders[c].append(p)
    final = {}

    def choose_owner(cur, p, candidates):
        old_paths = old.id_paths.get(cur, [])
        for q in old_paths:
            if q in candidates:
                return q  # still sits where it sat at the last commit
        stems = {stem_of(q) for q in old_paths}
        same = [q for q in sorted(candidates) if stem_of(q) in stems]
        return same[0] if same else min(candidates)

    for p in targets:
        cur = ids_now[p]
        if cur:
            candidates = set(holders[cur]) | {p} | {q for q in old.id_paths.get(cur, []) if q in new.live_set and q not in ids_now}
            if len(candidates) > 1:
                final[p] = cur if choose_owner(cur, p, candidates) == p else new_code(taken)
            else:
                final[p] = cur
        else:
            prev = old.id.get(p)
            clash = [q for q in holders.get(prev, []) if q != p] + [q for q in old.id_paths.get(prev, []) if q != p and q in new.live_set]
            final[p] = prev if (prev and not clash) else new_code(taken)

    fm_broken = []
    edited = {}
    for p in targets:
        raw = raws[p]
        if final[p] != ids_now[p] or fm_state(_nobom(raw))[0] == "none" or (fm_state(_nobom(raw))[0] == "ok" and not has_title(raw)):
            newraw, note = set_code(raw, stem_of(p), final[p])
            if newraw is None:
                fm_broken.append((p, note))
                final[p] = ids_now[p] or ""
                continue
            edited[p] = newraw
            if ids_now[p] is None or final[p] != ids_now[p]:
                rep.codes_added.append(p)
            if not has_title(raw) and has_title(newraw):
                rep.titles_added.append(p)
        else:
            st = fm_state(_nobom(raw))[0]
            if st in ("unclosed", "nullbytes"):
                fm_broken.append((p, st))

    # --- step 2: where did each old document go? ---------------------------
    where = {}
    for p in staged_all:
        c = final.get(p) or read_id(read_bytes(p))
        if c:
            where[c] = p
    moved, moved_legacy, retired, deleted_docs = {}, {}, {}, {}
    for a in sorted(deleted):
        if a not in old.corpus.live_set:
            continue
        x = old.id.get(a)
        if x and x in where and where[x] != a:
            dest = where[x]
            if dest in new.live_set:
                moved[x] = dest
            elif dest in new.obs_set:
                retired[x] = dest
            else:
                rep.notes.append(f"{rel(a, top)} moved to a skipped folder ({rel(dest, top)}); links to it were left alone")
                retired[x] = dest
        elif a in renamed:
            dest = renamed[a]
            if dest in new.live_set:
                moved_legacy[a] = dest
            else:
                retired[a] = dest
        else:
            deleted_docs[a] = x
    brand_new = [p for p in targets if p in added and p not in renamed.values() and final.get(p) and final[p] not in old.id_paths]
    unclear_delete = bool(deleted_docs and brand_new and not delete_ok)

    # --- step 3: links -------------------------------------------------------
    noedit = set(unstaged) | untracked_files(top)
    global_scan = bool(moved or moved_legacy or retired or deleted_docs) or any(
        stem_of(a) in old.corpus.live for a in added if is_md(a))
    scope = set(targets)
    if global_scan:
        scope |= set(new.live_files)
    old_path_of = {}
    for p in targets:
        if p in old.sha:
            old_path_of[p] = p
    for a, b in renamed.items():
        old_path_of[b] = a
    for x, dest in moved.items():
        for a in old.id_paths.get(x, []):
            old_path_of.setdefault(dest, a)

    def ref_for(dest, bare):
        s = stem_of(dest)
        if bare and len(new.live.get(s, [])) == 1:
            return s
        return new.rel_noext(dest)

    pending_unclear = {}
    for path in sorted(scope):
        is_target = path in targets
        in_commit = is_target or path in staged_all
        editable = path not in noedit
        if not editable and not is_target:
            if path in unstaged:
                rep.skipped_unstaged.append(path)
            continue
        raw = edited.get(path)
        if raw is None:
            raw = raws[path] if path in raws else read_bytes(path)
        bom = raw.startswith(BOM)
        orig_text = _dec(_nobom(raw))
        text = unwrap(orig_text)
        edits = []
        seen = collections.Counter()
        old_counts = None
        for m in wikilink_matches(text):
            inner, rawlink = m.group(1), m.group(0)
            parsed = parse_wikilink(inner)
            if parsed["kind"] == "external":
                continue
            seen[rawlink] += 1
            ostatus, ohits = resolve(parsed, old.corpus, path)
            nstatus, nhits = resolve(parsed, new, path)
            otarget = ohits[0] if ostatus in ("ok", "ok_indirect") else None
            ln = line_of(text, m.start())
            if otarget is not None:
                if otarget in new.live_set:
                    if nstatus == "ambiguous" and editable:
                        newl = "[[" + rebuild(inner, qualified_ref(otarget) or new.rel_noext(otarget)) + "]]"
                        edits.append((m.start(), m.end(), newl))
                        rep.made_specific.append((path, ln, rawlink, newl))
                    continue
                x = old.id.get(otarget)
                if not editable and (x in moved or otarget in moved_legacy or otarget in deleted_docs):
                    continue
                if x and x in moved:
                    newl = "[[" + rebuild(inner, qualified_ref(moved[x]) or ref_for(moved[x], parsed["kind"] == "bare")) + "]]"
                    edits.append((m.start(), m.end(), newl))
                    rep.repointed.append((path, ln, rawlink, newl))
                elif otarget in moved_legacy:
                    newl = "[[" + rebuild(inner, qualified_ref(moved_legacy[otarget]) or ref_for(moved_legacy[otarget], parsed["kind"] == "bare")) + "]]"
                    edits.append((m.start(), m.end(), newl))
                    rep.repointed.append((path, ln, rawlink, newl))
                elif (x and x in retired) or otarget in retired or nstatus == "obsolete":
                    dest = (retired.get(x) if x else None) or retired.get(otarget)
                    ref = qualified_ref(dest) if (dest and dest in new.obs_set) else None
                    if ref and editable:      # the link follows the document into obsolete/
                        newl = "[[" + rebuild(inner, ref) + "]]"
                        edits.append((m.start(), m.end(), newl))
                        rep.repointed.append((path, ln, rawlink, newl))
                    continue
                elif otarget in deleted_docs:
                    if unclear_delete:
                        pending_unclear.setdefault(otarget, []).append((path, ln, rawlink))
                    else:
                        edits.append((m.start(), m.end(), prose_of(inner)))
                        rep.to_words.append((path, ln, rawlink, prose_of(inner)))
                continue
            if nstatus in ("ok", "ok_indirect", "obsolete", "skip"):
                continue
            # a link that pointed nowhere before and points nowhere now
            if old_counts is None:
                op = old_path_of.get(path)
                otext = old.text(op) if op else None
                old_counts = collections.Counter(mm.group(0) for mm in wikilink_matches(unwrap(otext))) if otext else collections.Counter()
            if in_commit and seen[rawlink] > old_counts[rawlink]:
                if nstatus == "missing":
                    why = "points to no document"
                else:
                    opts = [qualified_ref(h) for h in nhits[:6]]
                    why = "is a name shared by several documents (%d)" % len(nhits)
                    if all(opts):
                        why += "; write the one you mean, for example " + " or ".join("[[" + o + "]]" for o in opts[:3])
                rep.blocks.append((path, ln, rawlink, why))
            else:
                rep.old_problems += 1
        new_text = apply_edits(text, edits)
        if is_target and editable:
            new_text, ch = convert_plain_links(new_text, path, new)
            rep.converted_plain += [(path, a, b, c) for a, b, c in ch]
        if editable:
            before_wrap = new_text
            new_text, wch = wrap(new_text, path, new)
            real = [c for c in wch if c[2] not in orig_text]
            if real:
                rep.canonicalized.append((path, len(real)))
            new_text, pch, pun = convert_pasted_paths(new_text, path, new)
            rep.pasted_converted += [(path, a, b, c) for a, b, c in pch]
            if in_commit:
                rep.pasted_unresolved += [(path, a, b) for a, b in pun]
        out = (BOM if bom else b"") + new_text.encode("utf-8", "surrogateescape")
        if editable and SOURCES.eol == "lf" and path.startswith(top + os.sep) and os.path.basename(path).upper() != "SKILL.MD" and (is_target or out != read_bytes(path)) and has_cr(out):
            out = to_lf(out)
            rep.eol_fixed.append(path)
        if editable and path.startswith(top + os.sep) and os.path.basename(path).upper() != "SKILL.MD" and (is_target or out != read_bytes(path)):
            op = old_path_of.get(path) or (path if path in old.sha else None)
            base = old.blobs[old.sha[op]] if op else None
            disk = read_bytes(path)
            out, stamped = date_decision(out, base, bool(op and op != path), today_str())
            if stamped:
                rep.dated.append(path)                               # the date follows a real change, nothing else
            elif base is not None and out == base and disk != base:
                rep.reverted.append(path)                            # only its date differed: the committed version is put back
        if not editable:
            if path in unstaged and (out != read_bytes(path) or path in edited):
                rep.skipped_unstaged.append(path)
            continue
        if out != read_bytes(path):
            rep.changed.append(path)
            if not dry:
                write_bytes(path, out)

    for a, links in pending_unclear.items():
        x = old.id.get(a)
        rep.blocks.append((a, 0, "", "UNCLEAR"))
        rep.notes.append(("unclear", a, x, links, [p for p in brand_new]))
    for p, why in fm_broken:
        rep.blocks.append((p, 0, "", "its frontmatter is broken (%s); GBrain cannot read it" % why))

    rep.codes_added = [p for p in rep.codes_added if p in rep.changed or dry and p not in noedit]
    rep.titles_added = [p for p in rep.titles_added if p in rep.changed or dry and p not in noedit]
    if not dry and rep.changed:
        inside = [p for p in rep.changed if p.startswith(top + os.sep)]
        rep.other_repo_changed = [p for p in rep.changed if not p.startswith(top + os.sep)]
        if inside:
            git(top, "add", "--", *[os.path.relpath(p, top) for p in inside])
    if not dry and rep.reverted and not rep.blocks:
        if subprocess.run(["git", "-C", top, "diff", "--cached", "--quiet"]).returncode == 0:
            rep.empty_commit = True
    return rep


def print_report(rep: Report, top: str, dry: bool):
    out = []
    head = "mb-doc-check" + (" (dry run - nothing was changed)" if dry else "")
    out.append(head)
    did = False

    def line(txt):
        nonlocal did
        did = True
        out.append("  " + txt)

    if rep.codes_added:
        line(f"documents given a permanent code: {len(rep.codes_added)}")
    if rep.titles_added:
        line(f"documents given a title (the frontmatter is now complete): {len(rep.titles_added)}")
    if rep.dated and rep.changed:
        n = len([x for x in rep.dated if x in rep.changed])
        if n:
            line(f"'updated' date set to today on documents that really changed: {n}")
    if rep.eol_fixed:
        n = len([x for x in rep.eol_fixed if x in rep.changed])
        if n:
            line(f"line endings changed to LF (one rule for every document): {n}")
    if rep.pasted_converted:
        line(f"pasted document paths turned into links: {len(rep.pasted_converted)}")
    if rep.pasted_unresolved:
        line(f"pasted paths left as text (no such document in the documentation repositories): {len(rep.pasted_unresolved)}")
        for pth, ln, tok in rep.pasted_unresolved[:5]:
            line(f"    {rel(pth, top)} line {ln}: {tok}")
    if rep.repointed:
        line(f"links repaired after a rename or move: {len(rep.repointed)}")
        for p, ln, o, n in rep.repointed[:10]:
            out.append(f"      {rel(p, top)} line {ln}: {o} -> {n}")
    if rep.made_specific:
        line(f"links made specific because two documents now share a name: {len(rep.made_specific)}")
        for p, ln, o, n in rep.made_specific[:10]:
            out.append(f"      {rel(p, top)} line {ln}: {o} -> {n}")
    if rep.to_words:
        line(f"links to deleted documents turned into plain words: {len(rep.to_words)}")
        for p, ln, o, n in rep.to_words[:10]:
            out.append(f"      {rel(p, top)} line {ln}: {o} -> {n}")
    if rep.converted_plain:
        line(f"plain links converted to the standard form: {len(rep.converted_plain)}")
    if rep.canonicalized:
        line(f"links written in the standard form [[[source:page]]](path): {sum(n for _, n in rep.canonicalized)} in {len(rep.canonicalized)} document(s)")
    for note in rep.notes:
        if isinstance(note, str):
            line(note)
    if rep.other_repo_changed:
        line(f"files changed in OTHER repositories (commit them there): {len(rep.other_repo_changed)}")
        for p in rep.other_repo_changed[:10]:
            out.append("      " + p)
    if rep.skipped_unstaged:
        line(f"documents left alone because they have changes you have not added yet: {len(rep.skipped_unstaged)}")
    if rep.old_problems:
        line(f"older broken links elsewhere (not from this commit, not blocking): {rep.old_problems}")
    if rep.not_in_commit:
        line(f"documents with changes that are NOT in this commit: {rep.not_in_commit}. Use 'git add -A' first if that is not what you want.")
    real = [b for b in rep.blocks if b[3] != "UNCLEAR"]
    unclear = [n for n in rep.notes if isinstance(n, tuple)]
    if not did and not (real or unclear):
        out.append("  all links are fine")
    if real or unclear:
        out.append("")
        out.append("THE COMMIT IS STOPPED. Please fix the following, then commit again:" if not dry else "THE COMMIT WOULD BE STOPPED for these reasons:")
        n = 0
        for p, ln, raw, why in real:
            n += 1
            where = f"{rel(p, top)}" + (f", line {ln}" if ln else "")
            out.append(f"  {n}. {where}: {raw + ' ' if raw else ''}{why}")
        for _, a, x, links, newfiles in unclear:
            n += 1
            out.append(f"  {n}. '{rel(a, top)}' was deleted and new document(s) were added in the same commit, and {len(links)} link(s) point to the deleted one.")
            out.append("     I cannot tell whether the new document is the same one under a new name.")
            if x:
                out.append(f"     If it is, put this line inside the frontmatter of the new document:  doc-id: \"{x}\"")
            else:
                out.append("     (This old document had no permanent code, so run 'migrate' first.)")
            out.append("     If the old document is really deleted, commit again with:  MB_DELETE_OK=1 git commit ...")
            for lp, lln, lraw in links[:5]:
                out.append(f"       linked from {rel(lp, top)} line {lln}: {lraw}")
    if rep.empty_commit:
        out.append("")
        out.append("NOTHING TO COMMIT. The only difference in the staged document(s) was the 'updated' date, so they were put back")
        out.append("exactly as they were at the last commit:")
        for p in rep.reverted[:8]:
            out.append(f"  {rel(p, top)}")
        out.append("No commit was made. Change a document for real, then commit again.")
    return "\n".join(out), bool(real or unclear or rep.empty_commit)


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------
def cmd_hook(args):
    try:
        top = repo_top(os.getcwd())
        if not top:
            print("mb-doc-check: not inside a git repository, skipped")
            return 0
        extra = load_roots_file() + list(SOURCES.by_id.values()) + [os.path.abspath(r) for r in (args.also_root or [])]
        rep = run_hook(top, extra, dry=args.dry_run, delete_ok=os.environ.get("MB_DELETE_OK") == "1")
        text, blocked = print_report(rep, top, args.dry_run)
        print(text)
        return 1 if (blocked and not args.dry_run) else 0
    except Exception as e:  # a bug must never block your work
        print(f"mb-doc-check: skipped because of an internal problem ({type(e).__name__}: {e})")
        return 0


def cmd_check(args):
    primary = [os.path.abspath(r) for r in args.root] if args.root else [repo_top(os.getcwd()) or os.getcwd()]
    pool = primary + [os.path.abspath(r) for r in (load_roots_file() + list(SOURCES.by_id.values()) + list(args.also_root or [])) if os.path.abspath(r) not in primary]
    corpus = Corpus(pool)
    mine = [p for p in corpus.live_files if any(p == r or p.startswith(r + os.sep) for r in primary)]
    dangling, ambiguous, no_code, no_title, no_date, no_lf, broken, dup = [], [], [], [], [], [], [], collections.defaultdict(list)
    plain = 0
    nonstd = 0
    for p in mine:
        raw = read_bytes(p)
        st = fm_state(_nobom(raw))[0]
        if st in ("unclosed", "nullbytes"):
            broken.append((p, st))
        code = read_id(raw)
        if code:
            dup[code].append(p)
        elif os.path.basename(p).upper() != "SKILL.MD" and raw.strip():
            no_code.append(p)
        if SOURCES.eol == "lf" and os.path.basename(p).upper() != "SKILL.MD" and has_cr(raw):
            no_lf.append(p)
        if os.path.basename(p).upper() != "SKILL.MD" and raw.strip() and st == "ok" and not has_title(raw):
            no_title.append(p)
        if os.path.basename(p).upper() != "SKILL.MD" and raw.strip() and st == "ok" and set_updated(raw, "x", only_if_missing=True) != raw:
            no_date.append(p)
        text = _dec(_nobom(raw))
        for m in wikilink_matches(text):
            parsed = parse_wikilink(m.group(1))
            status, hits = resolve(parsed, corpus, p)
            if status == "missing":
                dangling.append((p, line_of(text, m.start()), m.group(0)))
            elif status == "ambiguous":
                ambiguous.append((p, line_of(text, m.start()), m.group(0), len(hits)))
        plain += len(convert_plain_links(text, p, corpus)[1])
        if SOURCES.enabled:
            t1, c1 = convert_plain_links(text, p, corpus)
            t2, c2 = wrap(t1, p, corpus)
            t3, c3, _un = convert_pasted_paths(t2, p, corpus)
            nonstd += len(c1) + len(c2) + len(c3)
    roots = primary
    dups = {c: v for c, v in dup.items() if len(v) > 1}
    root0 = roots[0]
    print(f"mb-doc-check (read-only report) - {', '.join(roots)}")
    print(f"documents looked at: {len(mine)}; links were checked against documents in {len(pool)} folder(s) (obsolete folders skipped)")

    def section(title, items, fmt, limit=12):
        if not items:
            return
        print(f"{title}: {len(items)}")
        for it in (items if args.all else items[:limit]):
            print("  " + fmt(it))
        if not args.all and len(items) > limit:
            print(f"  ... and {len(items) - limit} more (add --all to see every line)")

    section("documents without a permanent code yet", no_code, lambda p: rel(p, root0))
    section("documents with CRLF or mixed line endings (the next commit makes them LF)", no_lf, lambda p: rel(p, root0))
    section("documents with frontmatter but no title yet (the next commit adds it)", no_title, lambda p: rel(p, root0))
    section("documents without an 'updated' date yet (the next commit adds it)", no_date, lambda p: rel(p, root0))
    section("documents sharing the same permanent code (copies)", list(dups.items()), lambda t: f"{t[0]}: " + ", ".join(rel(x, root0) for x in t[1]))
    section("documents with broken frontmatter", broken, lambda t: f"{rel(t[0], root0)} [{t[1]}]")
    section("links that point to no document", dangling, lambda t: f"{rel(t[0], root0)} line {t[1]}: {t[2]}")
    section("links to a name shared by several documents", ambiguous, lambda t: f"{rel(t[0], root0)} line {t[1]}: {t[2]} ({t[3]} documents)")
    if plain and not SOURCES.enabled:
        print(f"plain links that could become [[links]]: {plain}")
    if SOURCES.enabled:
        print(f"links not yet in the standard form (they would be rewritten at the next commit or by 'rollout'): {nonstd}")
    if not (no_code or no_title or no_date or no_lf or dups or broken or dangling or ambiguous or plain or nonstd):
        print("all clear")
    return 0


def cmd_migrate(args):
    roots = [os.path.abspath(r) for r in args.root] if args.root else [repo_top(os.getcwd()) or os.getcwd()]
    corpus = Corpus(roots)
    taken, todo, skipped, kept, titled, dated = set(), [], [], 0, [], []
    reads = {}
    for p in corpus.live_files:
        raw = read_bytes(p)
        reads[p] = raw
        c = read_id(raw)
        if c and c in taken:
            reads[p] = None  # duplicate code: give this copy a new one below
        elif c:
            taken.add(c)
    for p in corpus.live_files:
        raw = read_bytes(p)
        if os.path.basename(p).upper() == "SKILL.MD" or not raw.strip():
            continue
        c = read_id(raw)
        if c and reads[p] is not None:
            newraw, note = raw, "ok"
            if fm_state(_nobom(raw))[0] == "ok" and not has_title(raw):
                newraw, note = set_code(raw, stem_of(p), c)      # keeps its code, gains the missing title
                if newraw is None:
                    skipped.append((p, note))
                    continue
                titled.append(p)
            if fm_state(_nobom(newraw))[0] == "ok":
                dated_raw = set_updated(newraw, today_str(), only_if_missing=True)
                if dated_raw != newraw:
                    newraw = dated_raw
                    dated.append(p)
            if newraw != raw:
                if args.write:
                    write_bytes(p, newraw)
                continue
            kept += 1
            continue
        newraw, note = set_code(raw, stem_of(p), new_code(taken))
        if newraw is not None:
            newraw = set_updated(newraw, today_str(), only_if_missing=True)
        if newraw is None:
            skipped.append((p, note))
            continue
        todo.append(p)
        if args.write:
            write_bytes(p, newraw)
    print(f"migrate ({'WRITE' if args.write else 'dry run'})")
    print(f"documents that {'received' if args.write else 'would receive'} a permanent code: {len(todo)}")
    print(f"documents that already have one, and gained a missing title: {len(titled)}")
    print(f"documents that gained the missing date (updated: today): {len(dated)}")
    print(f"documents that already have a code and a title (unchanged): {kept}")
    if skipped:
        print(f"documents skipped, please look by hand: {len(skipped)}")
        for p, n in skipped[:12]:
            print(f"  {p}  [{n}]")
    if not args.write:
        print("dry run - nothing was changed. Add --write to do it.")
    return 0


def cmd_collisions(args):
    roots = [os.path.abspath(r) for r in args.root] if args.root else [repo_top(os.getcwd()) or os.getcwd()]
    corpus = Corpus(roots)
    dup = {s: p for s, p in corpus.live.items() if len(p) > 1}
    print(f"file names used by more than one document: {len(dup)}")
    for s in sorted(dup):
        print(f"  {s}  x{len(dup[s])}")
        if args.all:
            for p in dup[s]:
                print("      " + p)
    return 0


# ---------------------------------------------------------------------------
# rollout: put every link of a repository into the standard form
# ---------------------------------------------------------------------------
def rollout_plan(corpus: Corpus, repo_root: str, detail=None):
    stats, unresolved, files = collections.Counter(), [], []
    if detail is None:
        detail = {}
    detail.setdefault("pasted_ok", [])
    detail.setdefault("pasted_left", [])
    for p in corpus.live_files:
        if not (p == repo_root or p.startswith(repo_root + os.sep)) or os.path.basename(p).upper() == "SKILL.MD":
            continue
        raw = read_bytes(p)
        if not raw.strip():
            continue
        bom = raw.startswith(BOM)
        text = _dec(_nobom(raw))
        stats["documents"] += 1
        prot = protected_ranges(text)
        spans = [(m.start(), m.end()) for m in CANON_RE.finditer(text) if not _in(prot, m.start())]
        for m in CANON_RE.finditer(text):
            if _in(prot, m.start()):
                continue
            stats["links"] += 1
            st, hits = resolve(parse_wikilink(m.group(1)), corpus, p)
            if st in ("ok", "ok_indirect", "obsolete"):
                new = canonical_link(p, hits[0], m.group(1), in_table_row(text, m.start()))
                stats["standard_ok" if new == m.group(0) else "standard_refresh"] += 1
            elif st == "skip":
                stats["skipped"] += 1
            else:
                stats["unresolved_" + st] += 1
                unresolved.append((p, line_of(text, m.start()), m.group(0), st))
        for m in WIKI_RE.finditer(text):
            if _in(prot, m.start()) or any(s <= m.start() < e for s, e in spans):
                continue
            parsed = parse_wikilink(m.group(1))
            if parsed["kind"] == "external":
                continue
            stats["links"] += 1
            st, hits = resolve(parsed, corpus, p)
            if st in ("ok", "ok_indirect", "obsolete"):
                stats["to_convert_other_repo" if corpus.root_of(hits[0]) != corpus.root_of(p) else "to_convert_same_repo"] += 1
                if corpus.root_of(hits[0]) != corpus.root_of(p):
                    stats["xrepo:" + str(SOURCES.source_of(hits[0]))] += 1
                if not SOURCES.linkable(p, hits[0]):
                    stats["no_clickable_path"] += 1
            elif st == "skip":
                stats["skipped"] += 1
            else:
                stats["unresolved_" + st] += 1
                unresolved.append((p, line_of(text, m.start()), m.group(0), st))
        n_plain = len(convert_plain_links(text, p, corpus)[1])
        stats["links"] += n_plain
        stats["to_convert_plain_markdown"] += n_plain
        t0 = unwrap(text)
        t1, _c = convert_plain_links(t0, p, corpus)
        t2, _c = wrap(t1, p, corpus)
        t2, pch, pun = convert_pasted_paths(t2, p, corpus)
        stats["to_convert_pasted_path"] += len(pch)
        stats["links"] += len(pch)
        stats["pasted_unresolved"] += len(pun)
        detail["pasted_ok"] += [(p, ln, old) for ln, old, _new in pch]
        detail["pasted_left"] += [(p, ln, tok) for ln, tok in pun]
        unresolved += [(p, ln, tok, "pasted path, no such document") for ln, tok in pun] if False else []
        if t2 != text:
            files.append((p, (BOM if bom else b"") + t2.encode("utf-8", "surrogateescape")))
    return stats, unresolved, files


def print_rollout(sid, root, stats, unresolved, files, show_all, detail=None):
    print(f"== {sid}  ({root})")
    print(f"   documents: {stats['documents']}   links: {stats['links']}   documents that would change: {len(files)}")
    print(f"   already in the standard form: {stats['standard_ok']}   (with a stale path, to be refreshed: {stats['standard_refresh']})")
    print(f"   to convert: inside this repository {stats['to_convert_same_repo']}, to another repository {stats['to_convert_other_repo']}, plain markdown links {stats['to_convert_plain_markdown']}, pasted document paths {stats['to_convert_pasted_path']}")
    xr = sorted(((k[6:], v) for k, v in stats.items() if k.startswith("xrepo:")), key=lambda kv: -kv[1])
    if xr:
        print("   links to other repositories go to: " + ", ".join(f"{k} {v}" for k, v in xr))
    if stats["pasted_unresolved"]:
        print(f"   pasted paths that point to no document (left as text, not an error): {stats['pasted_unresolved']}")
    if stats["no_clickable_path"]:
        print(f"   with no clickable path possible (target folder outside the C: drive): {stats['no_clickable_path']}")
    print(f"   cannot be converted: target not found {stats['unresolved_missing']}, name shared by several documents {stats['unresolved_ambiguous']}, unknown qualifier {stats['skipped']}")
    for pth, ln, raw, st in (unresolved if show_all else unresolved[:8]):
        print(f"      {rel(pth, root)} line {ln}: {raw}   [{st}]")
    if not show_all and len(unresolved) > 8:
        print(f"      ... and {len(unresolved) - 8} more (add --all)")
    if show_all and detail:
        if detail.get("pasted_ok"):
            print(f"   pasted document paths that WOULD BECOME LINKS ({len(detail['pasted_ok'])}):")
            for pth, ln, old in detail["pasted_ok"]:
                print(f"      {rel(pth, root)} line {ln}: {old}")
        if detail.get("pasted_left"):
            print(f"   pasted paths LEFT AS TEXT, no such document in the documentation repositories ({len(detail['pasted_left'])}):")
            for pth, ln, tok in detail["pasted_left"]:
                print(f"      {rel(pth, root)} line {ln}: {tok}")


def _pool_corpus():
    return Corpus(sorted(set(SOURCES.by_id.values())))


def cmd_links_report(args):
    if not SOURCES.enabled:
        print("mb-doc-check.sources was not found: there is no map of folders to GBrain sources. Nothing to report.")
        return 2
    corpus = _pool_corpus()
    total = collections.Counter()
    for sid, root in sorted(SOURCES.by_id.items()):
        detail = {}
        stats, unresolved, files = rollout_plan(corpus, root, detail)
        print_rollout(sid, root, stats, unresolved, files, args.all, detail)
        total.update(stats)
    print(f"== all repositories: links {total['links']}, already standard {total['standard_ok']}, to convert {total['to_convert_same_repo'] + total['to_convert_other_repo'] + total['to_convert_plain_markdown'] + total['to_convert_pasted_path']}, cannot be converted {total['unresolved_missing'] + total['unresolved_ambiguous'] + total['skipped']}")
    print("read-only report - nothing was changed")
    return 0


def cmd_rollout(args):
    if not SOURCES.enabled:
        print("mb-doc-check.sources was not found: there is no map of folders to GBrain sources.")
        return 2
    root = os.path.abspath(args.repo) if args.repo else (repo_top(os.getcwd()) or os.getcwd())
    sid = SOURCES.source_of(root)
    if sid is None or SOURCES.by_id[sid] != root:
        print(f"{root} is not a folder listed in mb-doc-check.sources.")
        return 2
    corpus = _pool_corpus()
    detail = {}
    stats, unresolved, files = rollout_plan(corpus, root, detail)
    print_rollout(sid, root, stats, unresolved, files, args.all, detail)
    if not args.write:
        print("dry run - nothing was changed. Add --write to rewrite the documents (then commit).")
        return 0
    if not args.force and repo_top(root) == root and git(root, "status", "--porcelain").strip():
        print("STOP: this repository has uncommitted changes. Commit or restore them first, so that the rollout is one clean commit (or use --force).")
        return 1
    for pth, data in files:
        write_bytes(pth, data)
    print(f"rewritten: {len(files)} document(s). Review with 'git diff --stat', then commit.")
    return 0


def cmd_slug_selftest(args):
    """Compare this script's slug function with GBrain's own, for every document (or the paths in --paths)."""
    import shutil
    import tempfile
    if args.paths:
        rels = [l.rstrip("\n") for l in open(args.paths, encoding="utf-8") if l.strip()]
    else:
        rels = []
        corpus = _pool_corpus()
        for f in corpus.live_files + corpus.obs_files:
            sid = SOURCES.source_of(f)
            if sid:
                rels.append(os.path.relpath(f, SOURCES.by_id[sid]).replace(os.sep, "/"))
    gb = os.environ.get("MB_GBRAIN_DIR", "/home/dev-p/gbrain")
    bun = shutil.which("bun") or os.path.expanduser("~/.bun/bin/bun")
    if not os.path.exists(os.path.join(gb, "src/core/sync.ts")) or not os.path.exists(bun):
        print(f"cannot run the comparison: GBrain source not found in {gb} or bun not found")
        return 2
    js = f"import {{ slugifyPath }} from '{gb}/src/core/sync.ts';\nconst lines = (await Bun.stdin.text()).split('\\n').filter(l => l.length);\nconsole.log(JSON.stringify(lines.map(l => slugifyPath(l))));\n"
    with tempfile.NamedTemporaryFile("w", suffix=".ts", delete=False, dir=gb) as f:
        f.write(js)
        tmp = f.name
    try:
        r = subprocess.run([bun, "run", tmp], input="\n".join(rels).encode("utf-8", "surrogateescape"), capture_output=True)
    finally:
        os.unlink(tmp)
    out = r.stdout.decode("utf-8", "replace").strip().splitlines()
    if r.returncode != 0 or not out:
        print("GBrain's slug function could not be run:", r.stderr.decode("utf-8", "replace")[:300])
        return 2
    theirs = json.loads(out[-1])
    bad = [(r_, slugify_path(r_), g) for r_, g in zip(rels, theirs) if slugify_path(r_) != g]
    print(f"slug self-test: {len(rels)} path(s) compared, {len(bad)} difference(s)")
    for r_, mine, g in bad[:20]:
        print(f"  {r_}\n     this script: {mine}\n     GBrain:      {g}")
    return 1 if bad else 0


def cmd_sources_check(args):
    """Compare mb-doc-check.sources with GBrain's own list of sources (a wrong source id would silently lose links)."""
    import shutil
    if not SOURCES.enabled:
        print("mb-doc-check.sources was not found or is empty.")
        return 2
    gb = os.environ.get("MB_GBRAIN_BIN") or shutil.which("gbrain") or os.path.expanduser("~/.bun/bin/gbrain")
    r = subprocess.run([gb, "sources", "list", "--json"], capture_output=True)
    out = r.stdout.decode("utf-8", "replace")
    try:
        data = json.loads(out[out.index("{"):]) if "{" in out else json.loads(out)
    except ValueError:
        print("could not read GBrain's source list:", (r.stderr.decode("utf-8", "replace") or out)[:300])
        return 2
    items = data.get("sources", data) if isinstance(data, dict) else data
    theirs = {}
    for s in items:
        theirs[s.get("id")] = os.path.abspath(win_to_wsl(s.get("local_path") or s.get("path") or "")) if (s.get("local_path") or s.get("path")) else None
    problems = 0
    for sid, path in sorted(SOURCES.by_id.items()):
        if sid not in theirs:
            print(f"PROBLEM  {sid}: listed in mb-doc-check.sources but GBrain has no source with this id")
            problems += 1
        elif theirs[sid] and theirs[sid] != path:
            print(f"PROBLEM  {sid}: folder differs - file says {path}, GBrain says {theirs[sid]}")
            problems += 1
        else:
            print(f"ok       {sid}  {path}")
    for sid in sorted(set(theirs) - set(SOURCES.by_id)):
        print(f"note     GBrain source '{sid}' is not in mb-doc-check.sources (fine for code sources; documentation sources should be listed)")
    print("sources check: " + ("everything matches" if not problems else f"{problems} problem(s)"))
    return 1 if problems else 0


def cmd_fix_broken(args):
    """One-time cleanup: every link that points to nothing becomes plain words (its display text, or its name)."""
    root = os.path.abspath(args.repo) if args.repo else (repo_top(os.getcwd()) or os.getcwd())
    corpus = Corpus(sorted(set([root] + list(SOURCES.by_id.values()) + [os.path.abspath(r) for r in load_roots_file()])))
    changes, files, ambiguous_left = [], [], 0
    for p in corpus.live_files:
        if not (p == root or p.startswith(root + os.sep)) or os.path.basename(p).upper() == "SKILL.MD":
            continue
        raw = read_bytes(p)
        if not raw.strip():
            continue
        bom = raw.startswith(BOM)
        text = _dec(_nobom(raw))
        prot = protected_ranges(text)
        spans = [(m.start(), m.end()) for m in CANON_RE.finditer(text)]
        edits = []
        for m in WIKI_RE.finditer(text):
            if _in(prot, m.start()) or any(s <= m.start() < e for s, e in spans):
                continue
            parsed = parse_wikilink(m.group(1))
            if parsed["kind"] == "external":
                continue
            st, hits = resolve(parsed, corpus, p)
            if st == "missing" or (st == "ambiguous" and args.include_ambiguous):
                new = prose_of(m.group(1))
                edits.append((m.start(), m.end(), new))
                changes.append((p, line_of(text, m.start()), m.group(0), new, st))
            elif st == "ambiguous":
                ambiguous_left += 1
        if edits:
            out = (BOM if bom else b"") + apply_edits(text, edits).encode("utf-8", "surrogateescape")
            files.append((p, out))
    print(f"== fix-broken  ({root})")
    print(f"   links that point to nothing{' or to a shared name' if args.include_ambiguous else ''}: {len(changes)} in {len(files)} document(s)")
    if ambiguous_left:
        print(f"   links to a shared name, NOT touched (add --include-ambiguous to turn them into words too): {ambiguous_left}")
    for p, ln, old, new, st in changes:
        print(f"      {rel(p, root)} line {ln}: {old}  ->  {new}   [{st}]")
    if not args.write:
        print("dry run - nothing was changed. Add --write to do it (then commit).")
        return 0
    if not args.force and repo_top(root) == root and git(root, "status", "--porcelain").strip():
        print("STOP: this repository has uncommitted changes. Commit or restore them first (or use --force).")
        return 1
    for p, data in files:
        write_bytes(p, data)
    print(f"rewritten: {len(files)} document(s). Review with 'git diff --stat', then commit.")
    return 0


def cmd_eol(args):
    """One-time: give every document of one repository the same line ending (LF)."""
    root = os.path.abspath(args.repo) if args.repo else (repo_top(os.getcwd()) or os.getcwd())
    corpus = Corpus([root])
    crlf, mixed, lf, files = 0, 0, 0, []
    for p in corpus.live_files:
        if not (p == root or p.startswith(root + os.sep)) or os.path.basename(p).upper() == "SKILL.MD":
            continue
        raw = read_bytes(p)
        if not has_cr(raw):
            lf += 1
            continue
        if re.search(rb"(?<!\r)\n", raw):
            mixed += 1
        else:
            crlf += 1
        files.append((p, to_lf(raw)))
    print(f"== eol  ({root})")
    print(f"   documents with LF: {lf}   with CRLF: {crlf}   with a mix of both: {mixed}   (SKILL.md files and obsolete folders are never touched)")
    for p, _ in files[:args.show]:
        print(f"      {rel(p, root)}")
    if len(files) > args.show:
        print(f"      ... and {len(files) - args.show} more (add --show 1000)")
    if not args.write:
        print("dry run - nothing was changed. Add --write to convert them (then commit).")
        return 0
    if not args.force and repo_top(root) == root and git(root, "status", "--porcelain").strip():
        print("STOP: this repository has uncommitted changes. Commit or restore them first (or use --force).")
        return 1
    for p, data in files:
        write_bytes(p, data)
    print(f"rewritten: {len(files)} document(s). Review with 'git diff --stat', then commit.")
    return 0


HOOK = """#!/bin/sh
# installed by mb-doc-check: keeps [[links]] alive at commit time
if ! command -v python3 >/dev/null 2>&1; then
  echo "mb-doc-check: python3 not found, skipped"
  exit 0
fi
python3 "{tool}" hook
exit $?
"""


def cmd_install_hook(args):
    top = repo_top(os.path.abspath(args.repo or os.getcwd()))
    if not top:
        print("not a git repository")
        return 2
    hook = os.path.join(top, ".git", "hooks", "pre-commit")
    if os.path.exists(hook):
        print(f"A pre-commit hook already exists in {top}. I did not touch it.")
        print(f'To use mb-doc-check, add this line to that file:  python3 "{os.path.abspath(__file__)}" hook || exit 1')
        return 1
    with open(hook, "w", newline="\n") as f:
        f.write(HOOK.format(tool=os.path.abspath(__file__)))
    os.chmod(hook, 0o755)
    print(f"hook installed: {hook}")
    return 0


def build_parser():
    ap = argparse.ArgumentParser(prog="mb-doc-check", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    h = sub.add_parser("hook", help="what git runs at commit time")
    h.add_argument("--dry-run", action="store_true", help="show what would happen, change nothing")
    h.add_argument("--also-root", action="append", help="another folder whose documents may be linked to")
    c = sub.add_parser("check", help="read-only report")
    c.add_argument("--root", action="append")
    c.add_argument("--also-root", action="append", help="another folder whose documents may be linked to")
    c.add_argument("--all", action="store_true")
    m = sub.add_parser("migrate", help="one-time: give every document a permanent code")
    m.add_argument("--root", action="append")
    m.add_argument("--write", action="store_true")
    k = sub.add_parser("collisions", help="file names used more than once")
    k.add_argument("--root", action="append")
    k.add_argument("--all", action="store_true")
    lr = sub.add_parser("links-report", help="read-only: count the links of every repository by kind")
    lr.add_argument("--all", action="store_true")
    fb = sub.add_parser("fix-broken", help="one-time: turn every link that points to nothing into plain words")
    fb.add_argument("--repo")
    fb.add_argument("--write", action="store_true")
    fb.add_argument("--include-ambiguous", action="store_true")
    fb.add_argument("--force", action="store_true")
    eo = sub.add_parser("eol", help="one-time: give every document of one repository LF line endings")
    eo.add_argument("--repo")
    eo.add_argument("--write", action="store_true")
    eo.add_argument("--force", action="store_true")
    eo.add_argument("--show", type=int, default=15)
    ro = sub.add_parser("rollout", help="one-time: put every link of one repository into the standard form")
    ro.add_argument("--repo")
    ro.add_argument("--write", action="store_true")
    ro.add_argument("--all", action="store_true")
    ro.add_argument("--force", action="store_true")
    sub.add_parser("sources-check", help="compare mb-doc-check.sources with GBrain's list of sources")
    st = sub.add_parser("slug-selftest", help="compare the slug function with GBrain's own")
    st.add_argument("--paths", help="a text file with one repository-relative path per line")
    i = sub.add_parser("install-hook", help="install the git pre-commit hook")
    i.add_argument("--repo")
    return ap


def main(argv=None):
    global SOURCES
    args = build_parser().parse_args(argv)
    if os.environ.get("MB_DOC_CHECK_KEEP_SOURCES") != "1":
        SOURCES = SourceMap.load()
    return {"hook": cmd_hook, "check": cmd_check, "migrate": cmd_migrate, "collisions": cmd_collisions,
            "install-hook": cmd_install_hook, "links-report": cmd_links_report, "fix-broken": cmd_fix_broken, "eol": cmd_eol, "sources-check": cmd_sources_check, "rollout": cmd_rollout,
            "slug-selftest": cmd_slug_selftest}[args.cmd](args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        sys.exit(0)
