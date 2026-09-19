"""Repository intelligence queries over the index.

Each function answers one forensic question and returns a `Report` whose
findings carry explicit confidence:

- definition:  where is this symbol defined?
- references:  where is it used, and by whom?
- related:     what existing implementations look like this behaviour?
- deps:        what does this file depend on?
- dependents:  what depends on this file?
- tests_for:   which tests touch this symbol or file?
- symbols_in:  what does this file define?

Text-search hits in files the extractors do not parse are always INFERRED.
Languages without an extractor are reported as UNKNOWN, never as "none".
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from lord.index import Index
from lord.report import CONFIRMED, INFERRED, INFO, OK, UNKNOWN, WARN, Finding, Report
from lord.search import find_identifier
from lord.symbols import Symbol

# Small, explicit synonym groups used for behaviour-based search. Deliberately
# short: it must stay explainable. Extend when a real miss is observed.
SYNONYMS: tuple[frozenset[str], ...] = (
    frozenset({"validate", "validator", "validation", "check", "verify", "assert", "ensure", "is_valid"}),
    frozenset({"normalize", "normalise", "sanitize", "sanitise", "clean", "canonical", "canonicalize"}),
    frozenset({"parse", "parser", "decode", "deserialize", "read", "load"}),
    frozenset({"format", "formatter", "render", "encode", "serialize", "dump", "write", "to_string", "stringify"}),
    frozenset({"convert", "converter", "transform", "map", "translate", "adapt", "adapter"}),
    frozenset({"create", "make", "build", "builder", "factory", "new", "construct", "init"}),
    frozenset({"get", "fetch", "retrieve", "find", "lookup", "query", "search", "resolve"}),
    frozenset({"remove", "delete", "drop", "clear", "purge"}),
    frozenset({"update", "set", "modify", "change", "patch", "edit"}),
    frozenset({"email", "mail", "e_mail", "address"}),
    frozenset({"user", "account", "member", "profile"}),
    frozenset({"config", "configuration", "settings", "options", "preferences"}),
    frozenset({"helper", "util", "utils", "utility", "common", "shared", "lib"}),
    frozenset({"handler", "handle", "controller", "endpoint", "route", "view"}),
    frozenset({"cache", "memo", "memoize", "store"}),
    frozenset({"auth", "authenticate", "authentication", "login", "signin", "session", "token"}),
    frozenset({"error", "exception", "failure", "fault"}),
    frozenset({"slug", "slugify", "kebab"}),
    frozenset({"string", "str", "text"}),
)
STOPWORDS = {"a", "an", "the", "for", "to", "of", "and", "or", "in", "on", "with", "this", "that", "function", "method", "class", "add", "code", "logic", "implement", "implementation", "some", "new"}


def tokenize(text: str) -> set[str]:
    """Split identifiers and prose into lower-case terms (camelCase and snake_case aware)."""
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    spaced = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", spaced)
    terms = {t for t in re.split(r"[^A-Za-z0-9]+", spaced.lower()) if len(t) > 1 and t not in STOPWORDS}
    # light stemming: plural and -ing/-ed/-er forms
    stemmed = set()
    for t in terms:
        for suffix in ("ing", "ed", "er", "es", "s"):
            if t.endswith(suffix) and len(t) - len(suffix) >= 3:
                stemmed.add(t[: -len(suffix)])
        stemmed.add(t)
    return stemmed


def expand(terms: set[str]) -> set[str]:
    expanded = set(terms)
    for group in SYNONYMS:
        if terms & group:
            expanded |= group
    return expanded


def _sym_line(s: Symbol) -> str:
    sig = f" {s.signature}" if s.signature else ""
    return f"{s.file}:{s.line} {s.kind} {s.qualname}{sig}"


def _unknown_finding(index: Index, what: str) -> Finding | None:
    unsupported = index.unsupported_languages()
    errors = [ex.file for ex in index.extractions() if ex.error]
    if not unsupported and not errors:
        return None
    evidence = [f"{lang}: {n} file(s) without an extractor" for lang, n in sorted(unsupported.items())]
    evidence += [f"{f}: parse error" for f in errors[:10]]
    return Finding(kind="analysis-unavailable", summary=f"{what} could not be analysed in some files", severity=INFO,
                   confidence=UNKNOWN, evidence=evidence, consequence="text search still covers these files, but structural facts are unknown there")


# --- definition -----------------------------------------------------------------

def definition(index: Index, name: str) -> Report:
    report = Report(title=f"definition: {name}", meta={"root": index.root})
    exact = index.symbols_named(name)
    if not exact:
        lowered = name.lower()
        exact = [s for s in index.symbols() if s.name.lower() == lowered]
    for s in exact:
        report.add(Finding(kind="definition", summary=_sym_line(s), severity=OK, confidence=s.confidence,
                           evidence=[s.doc] if s.doc else [], data={"symbol": s.__dict__}))
    if not exact:
        report.add(Finding(kind="definition", summary=f"no indexed definition named {name!r}", severity=WARN, confidence=INFERRED,
                           recommendation="check spelling, try `lord related`, or the symbol may live in an unsupported language"))
    if unknown := _unknown_finding(index, "definitions"):
        report.add(unknown)
    return report


# --- references -----------------------------------------------------------------

def references(index: Index, root: Path, name: str, include_tests: bool = True) -> Report:
    report = Report(title=f"references: {name}", meta={"root": index.root})
    short = name.split(".")[-1]
    definitions = index.symbols_named(name)
    def_lines = {(s.file, s.line) for s in definitions}

    confirmed: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for ex in index.extractions():
        if ex.confidence != CONFIRMED:
            continue
        for ref in ex.references + ex.calls:
            if ref.name == short and (ex.file, ref.line) not in def_lines:
                confirmed[ex.file].append((ref.line, ref.scope))
        for imp in ex.imports:
            if short in imp.names or short in imp.aliases:
                confirmed[ex.file].append((imp.line, f"import from {imp.module}"))

    hits = find_identifier(root, index.inventory, short)
    inferred: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for hit in hits:
        if (hit.path, hit.line) in def_lines:
            continue
        if hit.path in confirmed and any(line == hit.line for line, _ in confirmed[hit.path]):
            continue
        inferred[hit.path].append((hit.line, hit.text))

    callers: set[str] = set()
    for path, items in confirmed.items():
        rec = index.inventory.get(path)
        if not include_tests and rec and rec.kind == "test":
            continue
        scopes = sorted({scope for _, scope in items if scope and not scope.startswith("import")})
        callers.update(f"{path}::{s}" for s in scopes)
        report.add(Finding(kind="reference", summary=f"{path}: {len(items)} confirmed use(s)" + (f" in {', '.join(scopes)}" if scopes else " at module level"),
                           severity=OK, confidence=CONFIRMED, evidence=[f"{path}:{line} {scope}".rstrip() for line, scope in sorted(items)[:15]],
                           data={"path": path, "lines": [line for line, _ in items], "scopes": scopes}))
    for path, items in sorted(inferred.items()):
        rec = index.inventory.get(path)
        if not include_tests and rec and rec.kind == "test":
            continue
        kind = rec.kind if rec else "other"
        analysed = index.extraction_for(path) is not None and index.extraction_for(path).confidence == CONFIRMED
        why = "text match in a parsed file (comment, string or attribute)" if analysed else f"text match in {kind} file without confirmed parsing"
        report.add(Finding(kind="reference", summary=f"{path}: {len(items)} text match(es)", severity=INFO, confidence=INFERRED,
                           evidence=[f"{path}:{line} {text}" for line, text in items[:10]], consequence=why,
                           data={"path": path, "lines": [line for line, _ in items]}))

    report.meta.update({
        "definitions": [_sym_line(s) for s in definitions],
        "confirmed_files": len(confirmed),
        "inferred_files": len(inferred),
        "callers": sorted(callers),
    })
    if not confirmed and not inferred:
        report.add(Finding(kind="reference", summary=f"no uses of {short!r} found in indexed text files", severity=INFO, confidence=INFERRED,
                           consequence="unindexed or excluded files (vendor, generated) were not searched"))
    if unknown := _unknown_finding(index, "references"):
        report.add(unknown)
    return report


# --- related implementations ------------------------------------------------------

def related(index: Index, query: str, limit: int = 10) -> Report:
    report = Report(title=f"related implementations: {query}", meta={"root": index.root})
    raw_terms = tokenize(query)
    terms = expand(raw_terms)
    if not terms:
        report.add(Finding(kind="related", summary="query has no searchable terms", severity=WARN, confidence=UNKNOWN))
        return report

    scored: list[tuple[float, Symbol, set[str]]] = []
    for s in index.symbols():
        if s.kind in ("variable",) and not s.exported:
            continue
        name_terms = tokenize(s.qualname)
        file_terms = tokenize(Path(s.file).stem) | tokenize(Path(s.file).parent.name)
        doc_terms = tokenize(s.doc) if s.doc else set()
        hits_name = name_terms & terms
        hits_file = file_terms & terms
        hits_doc = doc_terms & terms
        if not hits_name and not hits_doc:
            continue
        score = 3.0 * len(hits_name & raw_terms) + 2.0 * len(hits_name) + 1.0 * len(hits_doc) + 0.5 * len(hits_file)
        # precision: prefer names the query covers fully over long names with extra terms
        score += 2.0 * (len(hits_name) / len(name_terms)) if name_terms else 0.0
        if s.kind in ("function", "method", "class"):
            score += 0.5
        record = index.inventory.get(s.file)
        if record and record.kind == "test":
            score *= 0.4  # tests are evidence of behaviour, rarely reuse candidates
        scored.append((score, s, hits_name | hits_doc | hits_file))
    scored.sort(key=lambda t: (-t[0], t[1].file, t[1].line))

    for score, s, matched in scored[:limit]:
        report.add(Finding(kind="candidate", summary=_sym_line(s), severity=OK, confidence=INFERRED,
                           evidence=[f"matched terms: {', '.join(sorted(matched))}", f"score {score:.1f}"] + ([s.doc] if s.doc else []),
                           recommendation="open it and confirm whether it already covers the requested behaviour",
                           data={"score": score, "symbol": s.__dict__}))
    if not scored:
        report.add(Finding(kind="candidate", summary="no indexed symbol matches these terms", severity=INFO, confidence=INFERRED,
                           evidence=[f"terms: {', '.join(sorted(terms))}"], consequence="absence of a match is not proof that nothing similar exists"))
    if unknown := _unknown_finding(index, "related implementations"):
        report.add(unknown)
    report.meta["terms"] = sorted(terms)
    return report


# --- dependencies -------------------------------------------------------------------

def deps(index: Index, path: str) -> Report:
    report = Report(title=f"dependencies of {path}", meta={"root": index.root})
    ex = index.extraction_for(path)
    if ex is None:
        rec = index.inventory.get(path)
        report.add(Finding(kind="deps", summary=f"{path} is not analysed" + (f" ({rec.kind}, {rec.language or 'unknown language'})" if rec else " (not in inventory)"),
                           severity=WARN, confidence=UNKNOWN))
        return report
    if ex.error:
        report.add(Finding(kind="deps", summary=f"{path} could not be parsed: {ex.error}", severity=WARN, confidence=UNKNOWN))
    internal = [i for i in ex.imports if i.resolved]
    external = [i for i in ex.imports if not i.resolved]
    for imp in internal:
        names = ", ".join(imp.names) if imp.names else "(module)"
        report.add(Finding(kind="depends-on", summary=f"{imp.resolved}  <- {names}", severity=OK, confidence=imp.confidence,
                           evidence=[f"{path}:{imp.line} import {imp.module}"], data={"target": imp.resolved, "names": imp.names}))
    if external:
        report.add(Finding(kind="external", summary=f"{len(external)} external/unresolved import(s): " + ", ".join(sorted({i.module for i in external})[:15]),
                           severity=INFO, confidence=INFERRED, consequence="not workspace files (third-party, stdlib, or unresolvable alias)"))
    report.meta.update({"internal": [i.resolved for i in internal], "external": sorted({i.module for i in external})})
    return report


def dependents(index: Index, path: str) -> Report:
    report = Report(title=f"dependents of {path}", meta={"root": index.root})
    importers = index.importers_of(path)
    by_file: dict[str, list] = defaultdict(list)
    for file, imp in importers:
        by_file[file].append(imp)
    for file, imps in sorted(by_file.items()):
        names = sorted({n for i in imps for n in i.names}) or ["(module)"]
        conf = CONFIRMED if all(i.confidence == CONFIRMED for i in imps) else INFERRED
        rec = index.inventory.get(file)
        report.add(Finding(kind="used-by", summary=f"{file} imports {', '.join(names)}" + (" [test]" if rec and rec.kind == "test" else ""),
                           severity=OK, confidence=conf, evidence=[f"{file}:{i.line} import {i.module}" for i in imps], data={"file": file, "names": names}))
    if not importers:
        report.add(Finding(kind="used-by", summary=f"no indexed file imports {path}", severity=INFO, confidence=INFERRED,
                           consequence="dynamic imports, string references and unsupported languages are not visible here"))
    if unknown := _unknown_finding(index, "dependents"):
        report.add(unknown)
    report.meta["dependents"] = sorted(by_file)
    return report


# --- tests ---------------------------------------------------------------------------

def tests_for(index: Index, root: Path, target: str) -> Report:
    """Test files that import `target` (a file) or mention it (a symbol name)."""
    report = Report(title=f"tests for {target}", meta={"root": index.root})
    test_files = {f.path for f in index.inventory.files if f.kind == "test"}
    found: dict[str, list[str]] = defaultdict(list)
    if target in index.entries:
        for file, imp in index.importers_of(target):
            if file in test_files:
                found[file].append(f"{file}:{imp.line} imports {target}")
        for s in index.symbols_in(target):
            for hit in find_identifier(root, index.inventory, s.name, paths=test_files):
                found[hit.path].append(f"{hit.path}:{hit.line} {hit.text}")
    else:
        short = target.split(".")[-1]
        for hit in find_identifier(root, index.inventory, short, paths=test_files):
            found[hit.path].append(f"{hit.path}:{hit.line} {hit.text}")
    for file, evidence in sorted(found.items()):
        report.add(Finding(kind="test", summary=f"{file} ({len(evidence)} mention(s))", severity=OK, confidence=INFERRED, evidence=evidence[:10]))
    if not found:
        report.add(Finding(kind="test", summary=f"no test file mentions {target}", severity=WARN, confidence=INFERRED,
                           consequence="the target may be untested, or tests reach it indirectly", recommendation="check tests of its callers"))
    report.meta["tests"] = sorted(found)
    return report


# --- file symbols ---------------------------------------------------------------------

def symbols_in(index: Index, path: str) -> Report:
    report = Report(title=f"symbols in {path}", meta={"root": index.root})
    ex = index.extraction_for(path)
    if ex is None:
        report.add(Finding(kind="symbols", summary=f"{path} is not analysed (unsupported language or not in inventory)", severity=WARN, confidence=UNKNOWN))
        return report
    if ex.error:
        report.add(Finding(kind="symbols", summary=f"parse error: {ex.error}", severity=WARN, confidence=UNKNOWN))
    for s in ex.symbols:
        report.add(Finding(kind=s.kind, summary=f"{s.line}: {s.qualname}{(' ' + s.signature) if s.signature else ''}", severity=OK, confidence=s.confidence,
                           evidence=[s.doc] if s.doc else []))
    report.meta.update({"language": ex.language, "confidence": ex.confidence, "exports": ex.exports, "imports": [i.module for i in ex.imports]})
    return report
