"""Unfinished-work markers added by a change (`verify`'s marker fact).

A marker is unfinished work only in marker syntax, never as a word:

- code: a comment whose text starts with the marker (`# TODO: x`,
  `// FIXME(bob) y`, `/* XXX */`, ` * HACK ...`). Python comments are found
  with `tokenize`, so a marker inside a string literal (a test fixture
  string) is not one; other languages strip quoted strings first.
- prose (Markdown, reStructuredText, plain text): a line, outside fenced code
  blocks, that starts with the marker followed by `:` or `(`
  (`TODO: write this`, `- FIXME(x): ...`), or an HTML comment starting with it.
  Prose that discusses markers ("an added TODO marker") is not one.
- data without comments (JSON) and files under a fixtures/testdata directory
  (test input by convention) are never scanned.

`TODO/FIXME` written as a pair, or `TODO-like`, is discussion, not a marker. The
detector reads added lines only: new files count in full (untracked files
are not in `git diff`, which is how a new file's marker used to go unseen).
"""

from __future__ import annotations

import io
import re
import tokenize
from pathlib import Path, PurePosixPath

from lord.change_surface import _git

MARKER_WORDS = ("TODO", "FIXME", "XXX", "HACK")
_WORDS = "|".join(MARKER_WORDS)
_CODE_COMMENT_RE = re.compile(rf"(?:#|//|/\*|<!--|--|;|^\s*\*)\s*(?:{_WORDS})\b(?![/\w-])")
_PY_COMMENT_RE = re.compile(rf"^#+\s*(?:{_WORDS})\b(?![/\w-])")
_PROSE_LINE_RE = re.compile(rf"^\s*(?:(?:[-*+>]|#+|\d+[.)])\s+)*(?:\[[ xX]\]\s+)?(?:\*\*)?(?:{_WORDS})(?:\*\*)?\s*[:(]")
_HTML_COMMENT_RE = re.compile(rf"<!--\s*(?:{_WORDS})\b")
_STRING_RE = re.compile(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`")
_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")

PROSE_SUFFIXES = frozenset({".md", ".markdown", ".rst", ".txt", ".adoc"})
PYTHON_SUFFIXES = frozenset({".py", ".pyi"})
NO_COMMENT_SUFFIXES = frozenset({".json", ".csv", ".tsv", ".lock", ".svg"})
FIXTURE_DIRS = frozenset({"fixtures", "__fixtures__", "testdata", "test_data"})


def _skipped(path: str) -> bool:
    p = PurePosixPath(path)
    return p.suffix.lower() in NO_COMMENT_SUFFIXES or any(part in FIXTURE_DIRS for part in p.parts[:-1])


def _python_comment_lines(source: str) -> dict[int, str] | None:
    """Line -> comment text for every real comment, or None when the source
    does not tokenize (mid-edit syntax error: the caller falls back)."""
    comments: dict[int, str] = {}
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.COMMENT:
                comments[tok.start[0]] = tok.string
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return None
    return comments


def _fenced_lines(lines: list[str]) -> set[int]:
    inside, out, fence = False, set(), ""
    for number, line in enumerate(lines, 1):
        stripped = line.lstrip()
        if stripped.startswith(("```", "~~~")):
            token = stripped[:3]
            if not inside:
                inside, fence = True, token
            elif token == fence:
                inside = False
            out.add(number)
        elif inside:
            out.add(number)
    return out


def markers_in(path: str, source: str, lines: set[int] | None = None) -> list[tuple[int, str]]:
    """(line, text) of markers in `source`, restricted to `lines` when given."""
    if _skipped(path):
        return []
    text_lines = source.splitlines()
    wanted = lines if lines is not None else set(range(1, len(text_lines) + 1))
    suffix = PurePosixPath(path).suffix.lower()
    found: list[tuple[int, str]] = []
    if suffix in PROSE_SUFFIXES:
        fenced = _fenced_lines(text_lines)
        for n in sorted(wanted):
            if n <= len(text_lines) and n not in fenced:
                line = text_lines[n - 1]
                if _PROSE_LINE_RE.search(line) or _HTML_COMMENT_RE.search(line):
                    found.append((n, line.strip()))
        return found
    comments = _python_comment_lines(source) if suffix in PYTHON_SUFFIXES else None
    for n in sorted(wanted):
        if n > len(text_lines):
            continue
        line = text_lines[n - 1]
        if comments is not None:
            hit = n in comments and _PY_COMMENT_RE.search(comments[n])
        else:
            hit = _CODE_COMMENT_RE.search(_STRING_RE.sub('""', line))
        if hit:
            found.append((n, line.strip()))
    return found


def _added_lines(diff: str) -> dict[str, set[int]]:
    out: dict[str, set[int]] = {}
    current = ""
    for line in diff.splitlines():
        if line.startswith("+++ "):
            target = line[4:].strip()
            current = "" if target == "/dev/null" else target.removeprefix("b/")
            continue
        match = _HUNK_RE.match(line)
        if match and current:
            start, count = int(match.group(1)), int(match.group(2) or 1)
            out.setdefault(current, set()).update(range(start, start + count))
    return out


def added_markers(root: Path, base: str | None = None, staged: bool = False, untracked: list[str] | None = None) -> list[str]:
    """`path:line: text` for every marker the change adds (tracked hunks plus
    whole untracked files)."""
    args = ["diff", "-U0", "--no-color", "--no-ext-diff"]
    args += [base] if base else (["--cached"] if staged else ["HEAD"])
    per_file: dict[str, set[int] | None] = dict(_added_lines(_git(root, *args)))
    for path in untracked or []:
        per_file[path] = None  # a new file: every line is added
    found: list[str] = []
    for path, lines in sorted(per_file.items()):
        if _skipped(path) or lines == set():
            continue
        if staged:
            source = _git(root, "show", f":{path}")
        else:
            try:
                source = (root / path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
        for number, text in markers_in(path, source, lines):
            found.append(f"{path}:{number}: {text[:100]}")
    return found
