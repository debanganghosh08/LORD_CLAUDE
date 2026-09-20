"""Reuse-first analysis and duplicate detection.

Decision ladder enforced by `reuse_report`:

    REUSE existing -> EXTEND existing -> REFACTOR into existing -> CREATE new

`duplicates_report` finds candidate duplication already present in the
repository: same-named symbols defined in several files, constants with the
same value under different names, functions with near-identical bodies
(token-shingle similarity, exact and identifier-normalised), and thin
wrappers that only forward to another function. Every finding is a
candidate with evidence and a confidence; nothing here proves semantic
equivalence.
"""

from __future__ import annotations

import ast
import builtins
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from lord.index import Index
from lord.query import related
from lord.report import CONFIRMED, INFERRED, INFO, OK, WARN, Finding, Report
from lord.search import find_identifier
from lord.symbols import Symbol

SHINGLE = 4
MIN_BODY_TOKENS = 25
MIN_SHARED_SHINGLES = 3
DUPLICATE_SIMILARITY = 0.7      # exact-token Jaccard at or above this: duplicate logic
STRUCTURAL_SIMILARITY = 0.8     # normalised Jaccard at or above this: same structure, renamed identifiers
COPY_CONTAINMENT = 0.75         # exact-token containment at or above this: a copy that was then modified
COPY_MIN_TOKENS = 40            # ... only for bodies large enough that shared exact 4-grams are not coincidence
# `related` scores are rarity-weighted (Phase 8A): strong behavioural matches land
# between roughly 5 and 8, noise below 4. Calibrated on the fixtures and the demo.
STRONG_REUSE_SCORE = 4.5        # at or above this: reuse/extend before creating
WEAK_REUSE_SCORE = 2.5          # below this a candidate is noise and does not block creation

KEYWORDS = {
    # python
    "and", "as", "assert", "async", "await", "break", "class", "continue", "def", "del", "elif", "else", "except",
    "finally", "for", "from", "global", "if", "import", "in", "is", "lambda", "nonlocal", "not", "or", "pass",
    "raise", "return", "try", "while", "with", "yield", "None", "True", "False", "self", "cls",
    # javascript / typescript
    "function", "const", "let", "var", "new", "this", "typeof", "instanceof", "switch", "case", "default", "throw",
    "catch", "export", "extends", "implements", "interface", "type", "enum", "public", "private", "static",
    "null", "undefined", "true", "false", "void", "delete", "of", "do",
}
BUILTIN_NAMES = frozenset(dir(builtins))
TOKEN_RE = re.compile(r"[A-Za-z_$][\w$]*|\d+(?:\.\d+)?|\"(?:\\.|[^\"])*\"|'(?:\\.|[^'])*'|[^\s\w]")


@dataclass
class Body:
    symbol: Symbol
    exact: set[int]
    normalized: set[int]
    tokens: int


def _tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "//", "*", "/*")):
            continue
        tokens.extend(TOKEN_RE.findall(line))
    return tokens


def _shingles(tokens: list[str]) -> set[int]:
    return {hash(tuple(tokens[i:i + SHINGLE])) for i in range(len(tokens) - SHINGLE + 1)}


def _normalize(tokens: list[str]) -> list[str]:
    return [t if (t in KEYWORDS or not re.match(r"[A-Za-z_$]", t)) else "_" for t in tokens]


def jaccard(a: set[int], b: set[int]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def containment(a: set[int], b: set[int]) -> float:
    """Share of the smaller body's shingles present in the larger one.

    A copy that was then edited (lines added, a check changed) keeps most of
    the original's shingles, so its containment stays high while Jaccard
    drops with every added line. Independent functions that merely look alike
    share structure, not exact tokens, so exact-token containment stays low.
    """
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def function_body(root: Path, symbol: Symbol, source_lines: list[str] | None = None) -> str:
    if symbol.end_line is None:
        return ""
    if source_lines is None:
        try:
            source_lines = (root / symbol.file).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return ""
    # skip the declaration line itself so signatures do not inflate similarity
    return "\n".join(source_lines[symbol.line: symbol.end_line])


def body_of(root: Path, symbol: Symbol, source_lines: list[str] | None = None) -> Body | None:
    tokens = _tokens(function_body(root, symbol, source_lines))
    if len(tokens) < MIN_BODY_TOKENS:
        return None
    return Body(symbol, _shingles(tokens), _shingles(_normalize(tokens)), len(tokens))


def _is_code_file(index: Index, path: str) -> bool:
    rec = index.inventory.get(path)
    return bool(rec) and rec.kind in ("source", "script")


def collect_bodies(index: Index, root: Path, include_tests: bool = False) -> list[Body]:
    bodies: list[Body] = []
    cache: dict[str, list[str]] = {}
    for s in index.symbols():
        if s.kind not in ("function", "method") or s.end_line is None:
            continue
        if not include_tests and not _is_code_file(index, s.file):
            continue
        if s.file not in cache:
            try:
                cache[s.file] = (root / s.file).read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                cache[s.file] = []
        body = body_of(root, s, cache[s.file])
        if body:
            bodies.append(body)
    return bodies


def similar_pairs(bodies: list[Body], targets: list[Body] | None = None) -> list[tuple[Body, Body, float, float]]:
    """Pairs (a, b, exact_jaccard, normalized_jaccard) above either threshold.

    With `targets`, only pairs involving a target are considered (used by the
    change-surface analysis for new functions). An inverted index over
    normalised shingles keeps this well below O(n^2) in practice.
    """
    postings: dict[int, list[int]] = defaultdict(list)
    for i, body in enumerate(bodies):
        for sh in body.normalized:
            postings[sh].append(i)
    target_ids = None if targets is None else {id(t) for t in targets}
    pool = bodies if targets is None else targets
    seen: set[tuple[str, str]] = set()
    pairs = []
    for a in pool:
        counts: dict[int, int] = defaultdict(int)
        for sh in a.normalized:
            for j in postings[sh]:
                counts[j] += 1
        for j, shared in counts.items():
            b = bodies[j]
            if shared < MIN_SHARED_SHINGLES or b.symbol.id == a.symbol.id:
                continue
            if target_ids is not None and id(b) in target_ids and id(a) > id(b):
                continue
            key = tuple(sorted((a.symbol.id, b.symbol.id)))
            if key in seen:
                continue
            seen.add(key)
            exact, norm = jaccard(a.exact, b.exact), jaccard(a.normalized, b.normalized)
            if exact >= DUPLICATE_SIMILARITY or norm >= STRUCTURAL_SIMILARITY:
                pairs.append((a, b, exact, norm))
            elif min(a.tokens, b.tokens) >= COPY_MIN_TOKENS and not _nested(a, b) and containment(a.exact, b.exact) >= COPY_CONTAINMENT:
                pairs.append((a, b, exact, norm))  # modified copy: classified by `classify_pair`
    pairs.sort(key=lambda p: (-p[2], -p[3]))
    return pairs


def _nested(a: Body, b: Body) -> bool:
    """True when one symbol encloses the other (same file, qualname prefix): an
    inner function's tokens are contained in its parent's by construction."""
    if a.symbol.file != b.symbol.file:
        return False
    qa, qb = a.symbol.qualname, b.symbol.qualname
    return qa.startswith(qb + ".") or qb.startswith(qa + ".")


def classify_pair(a: Body, b: Body, exact: float, norm: float) -> tuple[str, str]:
    """(kind, description) for a similar pair: duplicate | structural | modified-copy."""
    if exact >= DUPLICATE_SIMILARITY:
        return "duplicate", f"near-identical bodies (exact similarity {exact:.2f})"
    if norm >= STRUCTURAL_SIMILARITY:
        return "structural", f"same structure with renamed identifiers (structural similarity {norm:.2f})"
    return "modified-copy", f"one contains most of the other's body (exact containment {containment(a.exact, b.exact):.2f}); a copy that was then edited"


def thin_wrappers(index: Index, root: Path) -> list[tuple[Symbol, str]]:
    """Python functions whose whole body is `return other(<same params>)`."""
    found = []
    for path, entry in index.entries.items():
        ex = entry.extraction
        if ex is None or ex.language != "python" or ex.error or not _is_code_file(index, path):
            continue
        try:
            tree = ast.parse((root / path).read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or len(node.body) != 1:
                continue
            stmt = node.body[0]
            if not isinstance(stmt, ast.Return) or not isinstance(stmt.value, ast.Call):
                continue
            call = stmt.value
            params = [a.arg for a in node.args.args if a.arg not in ("self", "cls")]
            args = [a.id for a in call.args if isinstance(a, ast.Name)]
            if len(args) != len(call.args) or args != params or call.keywords:
                continue
            callee = call.func.id if isinstance(call.func, ast.Name) else call.func.attr if isinstance(call.func, ast.Attribute) else ""
            if not callee or callee == node.name or (isinstance(call.func, ast.Name) and callee in BUILTIN_NAMES):
                continue  # `return bool(x)` is a conversion, not a wrapper
            symbol = next((s for s in ex.symbols if s.line == node.lineno and s.name == node.name), None)
            if symbol:
                found.append((symbol, callee))
    return found


def duplicates_report(index: Index, root: Path, include_tests: bool = False) -> Report:
    report = Report(title="duplicate candidates", meta={"root": index.root})
    code_symbols = [s for s in index.symbols() if _is_code_file(index, s.file) or include_tests]

    # same name, several files (functions, classes, constants, types) -- methods excluded: same-named
    # methods on different classes are normal.
    # grouped per project root: sub-projects of a monorepo legitimately reuse names
    by_key: dict[tuple[str, str, str], list[Symbol]] = defaultdict(list)
    for s in code_symbols:
        if s.kind in ("function", "class", "constant", "type", "interface", "enum") and s.exported:
            by_key[(index.inventory.project_root_of(s.file), s.kind, s.name)].append(s)
    for (_project, kind, name), group in sorted(by_key.items()):
        files = sorted({s.file for s in group})
        if len(files) < 2:
            continue
        if kind == "constant":
            values = {s.signature for s in group if s.signature}
            same_value = len(values) == 1 and bool(values)
            report.add(Finding(kind="duplicate-constant", summary=f"{name} defined in {len(files)} files" + (" with the same value" if same_value else " with DIFFERENT values"),
                               severity=WARN, confidence=CONFIRMED if same_value else INFERRED,
                               evidence=[f"{s.file}:{s.line} {name} = {s.signature}" for s in group],
                               consequence="two sources of truth for one value" if same_value else "same name, divergent meaning: callers may assume they agree",
                               recommendation="import the constant from one module" if same_value else "rename one or reconcile the values"))
        else:
            report.add(Finding(kind=f"duplicate-{kind}", summary=f"{kind} {name} defined in {len(files)} files", severity=WARN, confidence=INFERRED,
                               evidence=[f"{s.file}:{s.line} {s.qualname}" for s in group],
                               consequence="parallel definitions drift independently", recommendation="confirm whether both are needed; prefer one import path"))

    # same value, different constant names
    by_value: dict[tuple[str, str], list[Symbol]] = defaultdict(list)
    for s in code_symbols:
        if s.kind == "constant" and len(s.signature) >= 8:
            by_value[(index.inventory.project_root_of(s.file), s.signature)].append(s)
    for (_project, value), group in by_value.items():
        names = sorted({s.name for s in group})
        if len(names) < 2:
            continue
        report.add(Finding(kind="duplicate-value", summary=f"constants {', '.join(names)} share the value {value[:60]}", severity=WARN, confidence=INFERRED,
                           evidence=[f"{s.file}:{s.line} {s.name}" for s in group], consequence="the same literal maintained in several places",
                           recommendation="reuse one constant"))

    # near-duplicate function bodies
    bodies = collect_bodies(index, root, include_tests=include_tests)
    consequences = {"duplicate": "duplicated logic; a fix in one will be missed in the other",
                    "structural": "likely a copy with renames; verify before consolidating",
                    "modified-copy": "a diverging copy; the original's future fixes will not reach it"}
    for a, b, exact, norm in similar_pairs(bodies):
        kind, description = classify_pair(a, b, exact, norm)
        report.add(Finding(kind="duplicate-logic", summary=f"{a.symbol.qualname} and {b.symbol.qualname}: {description}", severity=WARN, confidence=INFERRED,
                           evidence=[f"{a.symbol.file}:{a.symbol.line}-{a.symbol.end_line} {a.symbol.qualname} ({a.tokens} tokens)",
                                     f"{b.symbol.file}:{b.symbol.line}-{b.symbol.end_line} {b.symbol.qualname} ({b.tokens} tokens)",
                                     f"exact {exact:.2f}, normalised {norm:.2f}, containment {containment(a.exact, b.exact):.2f}"],
                           consequence=consequences[kind], recommendation="open both; keep one and have the other call it, or extract the shared part",
                           data={"a": a.symbol.id, "b": b.symbol.id, "exact": exact, "normalized": norm, "containment": containment(a.exact, b.exact), "kind": kind}))

    # thin wrappers
    for symbol, callee in thin_wrappers(index, root):
        report.add(Finding(kind="thin-wrapper", summary=f"{symbol.qualname} only forwards to {callee}", severity=INFO, confidence=CONFIRMED,
                           evidence=[f"{symbol.file}:{symbol.line}"], consequence="an extra name for the same behaviour",
                           recommendation="call the target directly unless the wrapper is a deliberate seam (public API, indirection point)"))

    counts: dict[str, int] = defaultdict(int)
    for f in report.findings:
        counts[f.kind] += 1
    report.meta["counts"] = dict(counts)
    if not report.findings:
        report.add(Finding(kind="duplicates", summary="no duplicate candidates found among indexed symbols", severity=OK, confidence=INFERRED,
                           consequence="unsupported languages and functions without end lines were not compared"))
    return report


def reuse_report(index: Index, root: Path, description: str, names: list[str] | None = None, limit: int = 8) -> Report:
    """Answer: before creating <names> for <description>, what already exists?"""
    report = Report(title=f"reuse check: {description}", meta={"root": index.root, "proposed_names": names or []})
    decision = "create"
    exact_hits: list[Symbol] = []

    for name in names or []:
        hits = [s for s in index.symbols_named(name) if _is_code_file(index, s.file)]
        exact_hits.extend(hits)
        for s in hits:
            report.add(Finding(kind="exists", summary=f"{name} already exists: {s.file}:{s.line} {s.kind} {s.qualname}", severity=WARN, confidence=s.confidence,
                               evidence=[s.doc] if s.doc else [], consequence="creating another would duplicate it or shadow it",
                               recommendation=f"import and reuse {s.qualname} from {s.file}", data={"symbol": s.__dict__}))
        if not hits:
            text_hits = [h for h in find_identifier(root, index.inventory, name) if _is_code_file(index, h.path)]
            if text_hits:
                report.add(Finding(kind="exists", summary=f"{name} appears in {len({h.path for h in text_hits})} code file(s) but has no indexed definition", severity=INFO, confidence=INFERRED,
                                   evidence=[f"{h.path}:{h.line} {h.text}" for h in text_hits[:5]], consequence="possibly defined in an unsupported language, or only referenced",
                                   recommendation="open the files before creating a symbol with this name"))

    rel = related(index, description, limit=limit)
    candidates = [f for f in rel.findings if f.kind == "candidate" and f.data.get("score", 0) >= WEAK_REUSE_SCORE]
    strong = [f for f in candidates if f.data.get("score", 0) >= STRONG_REUSE_SCORE]
    for f in candidates:
        tier = "reuse-or-extend" if f in strong else "partial"
        report.add(Finding(kind=f"candidate-{tier}", summary=f.summary, severity=OK, confidence=INFERRED, evidence=f.evidence,
                           recommendation="open it; if it covers the behaviour, reuse it; if it covers most, extend it with a parameter or branch"
                           if tier == "reuse-or-extend" else "related behaviour; consider composing with it or following its pattern", data=f.data))

    if exact_hits:
        decision = "reuse"
    elif strong:
        decision = "extend"
    elif candidates:
        decision = "refactor-or-create"

    messages = {
        "reuse": "REUSE: the requested symbol already exists. Import it instead of creating a new one.",
        "extend": "EXTEND: strong candidates cover most of this behaviour. Extend one before writing a parallel implementation.",
        "refactor-or-create": "REFACTOR OR CREATE: related code exists but no strong match. Prefer fitting the new code into the existing module/pattern; a new implementation may be justified.",
        "create": "CREATE may be justified: no existing symbol or related behaviour was found for these terms. State this in the plan.",
    }
    report.add(Finding(kind="decision", summary=messages[decision], severity=WARN if decision in ("reuse", "extend") else INFO, confidence=INFERRED,
                       evidence=[f"terms searched: {', '.join(rel.meta.get('terms', []))}"],
                       consequence="lexical search only: absence of a match is not proof of absence", data={"decision": decision}))
    report.meta["decision"] = decision
    if unknown := next((f for f in rel.findings if f.kind == "analysis-unavailable"), None):
        report.add(unknown)
    return report
