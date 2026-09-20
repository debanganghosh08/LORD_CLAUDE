"""Change-surface measurement: what a diff touches and whether it looks bloated.

Deterministic facts from Git (files, lines, new/deleted files, directories,
whitespace-only churn) are combined with index facts (new symbols, name
collisions, resemblance to existing functions, import connectivity between
changed files) into a BLOAT SIGNAL with reasons. Size alone is never judged:
a large diff with no bloat reasons is reported as "low".
"""

from __future__ import annotations

import ast
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lord.config import LordConfig
from lord.extractors import SUPPORTED, extract
from lord.index import Index
from lord.inventory import classify, language_of
from lord.report import CONFIRMED, INFERRED, INFO, OK, WARN, Finding, Report
from lord.reuse import Body, DUPLICATE_SIMILARITY, _is_code_file, body_of, collect_bodies, similar_pairs
from lord.symbols import Symbol

MANIFEST_KINDS = ("manifest",)
GROWTH_RATIO = 3.0        # net growth vs removed lines that starts to look additive-only
GROWTH_MIN_LINES = 150    # ... but only when the diff is at least this big
CHURN_RATIO = 0.2         # whitespace-only share of added lines that counts as formatting churn
CHURN_MIN_LINES = 5       # ... once at least this many lines are whitespace-only
WIDE_SURFACE_DIRS = 4     # top-level directories touched that count as a wide surface
LEVELS = ("low", "elevated", "high")


@dataclass
class FileChange:
    path: str
    status: str                       # A (added), M (modified), D (deleted), R (renamed)
    added: int = 0
    removed: int = 0
    whitespace_only: int = 0          # added lines that differ only in whitespace
    kind: str = ""
    language: str = ""
    old_path: str = ""
    new_symbols: list[Symbol] = field(default_factory=list)
    removed_symbols: list[str] = field(default_factory=list)


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return completed.stdout if completed.returncode == 0 else ""


def _numstat(text: str) -> dict[str, tuple[int, int]]:
    out = {}
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        added, removed, path = parts
        if "=>" in path:  # rename: "old => new" or "dir/{old => new}"
            path = _rename_target(path)
        out[path] = (int(added) if added != "-" else 0, int(removed) if removed != "-" else 0)
    return out


def _rename_target(path: str) -> str:
    if "{" in path and "}" in path:
        pre, rest = path.split("{", 1)
        inner, post = rest.split("}", 1)
        return (pre + inner.split(" => ")[1] + post).replace("//", "/")
    return path.split(" => ")[1]


def git_changes(root: Path, base: str | None = None, staged: bool = False) -> list[FileChange]:
    """Changed files. Default: working tree (tracked + untracked) vs HEAD."""
    if base:
        diff_args = [base]
    elif staged:
        diff_args = ["--cached"]
    else:
        diff_args = ["HEAD"]
    numstat = _numstat(_git(root, "diff", "-M", "--numstat", *diff_args))
    numstat_w = _numstat(_git(root, "diff", "-M", "-w", "--numstat", *diff_args))
    changes: dict[str, FileChange] = {}
    for line in _git(root, "diff", "-M", "--name-status", *diff_args).splitlines():
        parts = line.split("\t")
        status = parts[0][0]
        path = parts[-1]
        change = FileChange(path=path, status=status, old_path=parts[1] if status == "R" else "")
        change.added, change.removed = numstat.get(path, (0, 0))
        # a file absent from the -w numstat has no non-whitespace change at all
        change.whitespace_only = max(0, change.added - numstat_w.get(path, (0, 0))[0])
        changes[path] = change
    if not base and not staged:
        for line in _git(root, "status", "--porcelain", "--untracked-files=all").splitlines():
            if line.startswith("??"):
                path = line[3:].strip().strip('"')
                try:
                    data = (root / path).read_bytes()
                except OSError:
                    continue
                if b"\x00" in data:
                    continue
                changes[path] = FileChange(path=path, status="A", added=data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0))
    for change in changes.values():
        p = Path(change.path)
        change.language = language_of(p)
        change.kind = classify(change.path, change.language, b"", True)[0]
    return sorted(changes.values(), key=lambda c: c.path)


def _old_source(root: Path, path: str, base: str | None, staged: bool) -> str | None:
    ref = base if base else "HEAD"
    if staged:
        ref = "HEAD"
    return _git(root, "show", f"{ref}:{path}") or None


def _symbol_delta(root: Path, change: FileChange, base: str | None, staged: bool) -> None:
    if change.language not in SUPPORTED or change.status == "D":
        return
    try:
        new_src = (root / change.path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    new_ex = extract(root, change.path, change.language, new_src)
    old_src = None if change.status == "A" else _old_source(root, change.old_path or change.path, base, staged)
    old_names: set[str] = set()
    if old_src:
        old_names = {s.qualname for s in extract(root, change.path, change.language, old_src).symbols}
    change.new_symbols = [s for s in new_ex.symbols if s.qualname not in old_names]
    change.removed_symbols = sorted(old_names - {s.qualname for s in new_ex.symbols})


def _inline_guards(stmt: ast.stmt) -> list[tuple[ast.expr, set[ast.AST]]]:
    """(test, nodes-under-a-conditional-branch) for every ternary or boolean
    operator inside a statement: the nodes evaluated only when the test allows."""
    out: list[tuple[ast.expr, set[ast.AST]]] = []
    for node in ast.walk(stmt):
        if isinstance(node, ast.IfExp):
            out.append((node.test, set(ast.walk(node.body)) | set(ast.walk(node.orelse))))
        elif isinstance(node, ast.BoolOp) and len(node.values) > 1:
            out.append((node.values[0], {n for v in node.values[1:] for n in ast.walk(v)}))
    return out


def _guarded_calls(tree: ast.AST) -> dict[str, dict[str, set[str] | bool]]:
    """Per function: call names, whether each is unconditional at the function's
    top level, and the names tested by the conditions guarding it."""
    out: dict[str, dict[str, Any]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        calls: dict[str, dict[str, Any]] = {}

        def visit(body: list[ast.stmt], guards: list[ast.expr]) -> None:
            for stmt in body:
                for sub in ast.walk(stmt) if not isinstance(stmt, (ast.If, ast.Try, ast.While, ast.For, ast.With)) else [stmt]:
                    if isinstance(sub, ast.Call):
                        name = sub.func.id if isinstance(sub.func, ast.Name) else sub.func.attr if isinstance(sub.func, ast.Attribute) else ""
                        if name:
                            # a call inside a ternary (`x if flag else call()`) or a short-circuit
                            # (`flag or call()`) is guarded by that expression's test as well
                            inline = [t for t, branch in _inline_guards(stmt) if sub in branch]
                            entry = calls.setdefault(name, {"unconditional": False, "guards": set()})
                            if not guards and not inline:
                                entry["unconditional"] = True
                            for g in guards + inline:
                                entry["guards"].update(n.id for n in ast.walk(g) if isinstance(n, ast.Name))
                if isinstance(stmt, ast.If):
                    visit(stmt.body, guards + [stmt.test])
                    visit(stmt.orelse, guards + [stmt.test])
                elif isinstance(stmt, ast.Try):
                    visit(stmt.body, guards + [ast.Name(id="__try__", ctx=ast.Load())])
                    for handler in stmt.handlers:
                        visit(handler.body, guards + [ast.Name(id="__except__", ctx=ast.Load())])
                    visit(stmt.orelse, guards)
                    visit(stmt.finalbody, guards)
                elif isinstance(stmt, (ast.While, ast.For)):
                    visit(stmt.body, guards)
                elif isinstance(stmt, ast.With):
                    visit(stmt.body, guards)

        visit(node.body, [])
        params = {a.arg for a in node.args.args + node.args.kwonlyargs}
        out[node.name] = {"calls": calls, "params": params}
    return out


def invariant_bypasses(index: Index, path: str, old_src: str, new_src: str) -> list[Finding]:
    """Deterministic signals that an existing check was bypassed instead of addressed:

    - a call that was unconditional in a function at HEAD is now guarded by a
      condition that tests a parameter the function did not have before
      (`if not skip_validation: validate(...)`, `unless force`);
    - a call to a workspace symbol with other callers was removed from a
      function while the symbol still exists.
    Both are advisory (inferred): a refactor can legitimately do either, but
    then the plan and the report must say so.
    """
    findings: list[Finding] = []
    try:
        old = _guarded_calls(ast.parse(old_src)) if old_src else {}
        new = _guarded_calls(ast.parse(new_src))
    except (SyntaxError, ValueError):
        return findings
    known = {s.name for s in index.symbols() if s.kind in ("function", "method")}
    for func, after in new.items():
        before = old.get(func)
        if not before:
            continue
        new_params = after["params"] - before["params"]
        for name, info in before["calls"].items():
            if not info["unconditional"] or name not in known:
                continue
            now = after["calls"].get(name)
            if now is None:
                findings.append(Finding(kind="shared-call-removed", summary=f"{path}::{func} no longer calls {name}", severity=WARN, confidence=INFERRED,
                                        evidence=[f"{path}: {name}() was called unconditionally in {func} at HEAD"],
                                        consequence="a check or behaviour other callers still rely on is skipped here", recommendation="state why the call is no longer needed, or keep it"))
            elif not now["unconditional"]:
                guards = sorted(now["guards"] & new_params)
                if guards:
                    findings.append(Finding(kind="invariant-bypass", summary=f"{path}::{func}: call to {name} is now conditional on new parameter {', '.join(guards)}", severity=WARN,
                                            confidence=INFERRED, evidence=[f"{path}: {name}() unconditional at HEAD; now guarded by {', '.join(guards)}"],
                                            consequence="callers can switch the check off; two behaviours exist where one invariant did",
                                            recommendation="address the need centrally (parameterise the check, extend it) or make the bypass an explicit, justified decision"))
    return findings


def _in_scope(change: FileChange, scope: tuple[str, ...]) -> bool:
    lowered = change.path.lower()
    for item in scope:
        item_l = item.replace("\\", "/").lower()
        if lowered == item_l or lowered.startswith(item_l.rstrip("/") + "/"):
            return True
        if item_l in lowered or any(item_l in s.qualname.lower() for s in change.new_symbols):
            return True
    return False


def _components(paths: list[str], index: Index) -> list[set[str]]:
    """Connected components of changed files under import relations (both directions)."""
    parent = {p: p for p in paths}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    changed = set(paths)
    for path in paths:
        ex = index.extraction_for(path)
        if ex is None:
            continue
        for imp in ex.imports:
            if imp.resolved in changed:
                parent[find(path)] = find(imp.resolved)
    groups: dict[str, set[str]] = defaultdict(set)
    for p in paths:
        groups[find(p)].add(p)
    return sorted(groups.values(), key=len, reverse=True)


def measure(config: LordConfig, index: Index, base: str | None = None, staged: bool = False, scope: tuple[str, ...] = (), only: tuple[str, ...] = ()) -> Report:
    """Measure the change surface.

    `scope` says what the task is about (files outside it are reported as
    potentially unrelated). `only` restricts the *measured set* to paths under
    the given prefixes: a sub-project's task should not be judged by unrelated
    dirty files elsewhere in the workspace (evidence records, docs, another
    project). Both are optional; without them the whole tree is measured.
    """
    root = config.root.resolve()
    report = Report(title="change surface", meta={"root": str(root), "base": base or ("staged" if staged else "working tree vs HEAD"), "only": list(only)})
    if not _git(root, "rev-parse", "--show-toplevel"):
        report.add(Finding(kind="git", summary="not a Git repository: change surface unavailable", severity=WARN, confidence=CONFIRMED))
        return report

    changes = git_changes(root, base, staged)
    if only:
        prefixes = tuple(p.replace("\\", "/").strip("/") + "/" for p in only)
        changes = [c for c in changes if c.path.startswith(prefixes) or c.path in {p.rstrip("/") for p in prefixes}]
    for change in changes:
        _symbol_delta(root, change, base, staged)

    added = sum(c.added for c in changes)
    removed = sum(c.removed for c in changes)
    new_files = [c for c in changes if c.status == "A"]
    deleted = [c for c in changes if c.status == "D"]
    dirs = sorted({c.path.split("/")[0] if "/" in c.path else "." for c in changes})
    by_kind: dict[str, int] = defaultdict(int)
    for c in changes:
        by_kind[c.kind] += 1
    new_symbols = [(c, s) for c in changes for s in c.new_symbols]
    whitespace = sum(c.whitespace_only for c in changes)

    report.meta.update({
        "files": len(changes), "new_files": len(new_files), "deleted_files": len(deleted), "renamed_files": sum(1 for c in changes if c.status == "R"),
        "lines_added": added, "lines_removed": removed, "net_growth": added - removed, "directories": dirs, "by_kind": dict(by_kind),
        "new_symbols": [f"{c.path}::{s.qualname}" for c, s in new_symbols], "removed_symbols": [f"{c.path}::{q}" for c in changes for q in c.removed_symbols],
        "whitespace_only_lines": whitespace, "bloat_level": "low", "bloat_reasons": [],
    })
    report.add(Finding(kind="summary", severity=OK, confidence=CONFIRMED,
                       summary=f"files: {len(changes)} (+{len(new_files)} new, -{len(deleted)} deleted), +{added}/-{removed} lines, net {added - removed:+d}, new symbols: {len(new_symbols)}",
                       evidence=[f"{c.status} {c.path} +{c.added}/-{c.removed}" + (f" [{c.kind}]" if c.kind not in ("source", "") else "") for c in changes[:25]]
                       + ([f"... and {len(changes) - 25} more files"] if len(changes) > 25 else [])))
    if not changes:
        return report

    reasons: list[tuple[str, str]] = []  # (level, reason)

    # new files: a question, not a verdict. Only code files are questioned; new
    # tests, docs and package markers (empty __init__.py) are not bloat signals.
    for c in new_files:
        if c.kind not in ("source", "script"):
            continue
        symbols = [s for s in c.new_symbols if not s.parent]
        thin = len(symbols) == 1 and c.added <= 40
        report.add(Finding(kind="new-file", summary=f"{c.path}: new {c.kind} file with {len(symbols)} top-level symbol(s), {c.added} lines", severity=INFO, confidence=CONFIRMED,
                           evidence=[f"{s.kind} {s.qualname}" for s in symbols[:10]],
                           consequence="a new file is a new responsibility only if nothing existing owns this behaviour",
                           recommendation="answer: does this represent a genuinely new responsibility? if it wraps existing code, place it there instead"))
        if thin:
            reasons.append(("elevated", f"{c.path} is a new file holding a single small symbol"))

    # new symbols colliding with existing definitions elsewhere (code files only;
    # nested symbols and methods are scoped by their parent and never collide)
    code_new_symbols = [(c, s) for c, s in new_symbols if c.kind in ("source", "script") and not s.parent]
    for c, s in code_new_symbols:
        if not s.exported:
            continue
        project = index.inventory.project_root_of(c.path)
        clashes = [e for e in index.symbols_named(s.name) if e.file != c.path and e.kind == s.kind and not e.parent and _is_code_file(index, e.file)
                   and index.inventory.project_root_of(e.file) == project]
        if clashes:
            report.add(Finding(kind="name-collision", summary=f"new {s.kind} {s.qualname} in {c.path} has the same name as {len(clashes)} existing definition(s)", severity=WARN, confidence=INFERRED,
                               evidence=[f"{e.file}:{e.line} {e.qualname}" for e in clashes[:5]], consequence="a parallel definition; callers may pick either",
                               recommendation="reuse the existing one or justify the new name"))
            reasons.append(("elevated", f"{s.qualname} duplicates an existing {s.kind} name"))

    # new functions resembling existing ones
    targets: list[Body] = []
    for c, s in new_symbols:
        if c.kind in ("source", "script") and s.kind in ("function", "method") and s.end_line:
            body = body_of(root, s)
            if body:
                targets.append(body)
    if targets:
        existing = [b for b in collect_bodies(index, root) if not any(b.symbol.id == t.symbol.id for t in targets)]
        for a, b, exact, norm in similar_pairs(existing + targets, targets=targets):
            other = b if a.symbol.id in {t.symbol.id for t in targets} else a
            new = a if other is b else b
            level = "high" if exact >= DUPLICATE_SIMILARITY else "elevated"
            report.add(Finding(kind="resembles-existing", summary=f"new {new.symbol.qualname} resembles existing {other.symbol.qualname} (exact {exact:.2f}, structural {norm:.2f})",
                               severity=WARN, confidence=INFERRED, evidence=[f"{new.symbol.file}:{new.symbol.line}", f"{other.symbol.file}:{other.symbol.line}"],
                               consequence="duplicated logic entering the codebase", recommendation="call or extend the existing function instead"))
            reasons.append((level, f"new {new.symbol.qualname} resembles existing {other.symbol.qualname}"))

    # existing calls made conditional or removed: a bypass of an invariant must be explicit
    for c in changes:
        if c.language != "python" or c.status not in ("M", "R"):
            continue
        old_src = _old_source(root, c.old_path or c.path, base, staged)
        try:
            new_src = (root / c.path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for finding in invariant_bypasses(index, c.path, old_src or "", new_src):
            report.add(finding)
            reasons.append(("elevated", finding.summary))

    # growth shape
    if added - removed >= GROWTH_MIN_LINES and removed > 0 and (added / removed) >= GROWTH_RATIO:
        reasons.append(("elevated", f"additive-heavy diff: +{added} vs -{removed} lines"))
    elif added - removed >= GROWTH_MIN_LINES and removed == 0 and not new_files:
        reasons.append(("elevated", f"{added} lines added to existing files with nothing removed"))

    # formatting churn
    changed_lines = added + removed
    if changed_lines and whitespace / max(added, 1) >= CHURN_RATIO and whitespace >= CHURN_MIN_LINES:
        churn_files = [c.path for c in changes if c.whitespace_only]
        report.add(Finding(kind="formatting-churn", summary=f"{whitespace} added line(s) differ only in whitespace", severity=WARN, confidence=CONFIRMED,
                           evidence=churn_files[:10], consequence="review noise that hides the real change", recommendation="revert formatting-only edits or land them separately"))
        reasons.append(("elevated", "formatting-only churn"))

    # manifests / dependencies
    for c in changes:
        if c.kind in MANIFEST_KINDS:
            report.add(Finding(kind="dependency-change", summary=f"{c.path} changed (+{c.added}/-{c.removed})", severity=INFO, confidence=CONFIRMED,
                               consequence="a dependency or build change rides along with this diff", recommendation="confirm the task requires it"))
            if scope and not _in_scope(c, scope):
                reasons.append(("elevated", f"manifest {c.path} changed outside the stated scope"))

    # scope / unrelated changes
    unrelated: list[str] = []
    if scope:
        in_scope = {c.path for c in changes if _in_scope(c, scope)}
        # files import-connected to an in-scope file count as related
        related_paths: set[str] = set()
        for c in changes:
            ex = index.extraction_for(c.path)
            if ex and any(imp.resolved in in_scope for imp in ex.imports):
                related_paths.add(c.path)
            if any(imp.resolved == c.path for p in in_scope for imp in (index.extraction_for(p).imports if index.extraction_for(p) else [])):
                related_paths.add(c.path)
        unrelated = sorted(c.path for c in changes if c.path not in in_scope and c.path not in related_paths)
    elif len(changes) > 1:
        code_paths = [c.path for c in changes if c.kind in ("source", "test", "script") and c.status != "D"]
        if len(code_paths) > 1:
            comps = _components(code_paths, index)
            if len(comps) > 1:
                unrelated = sorted(p for comp in comps[1:] for p in comp)
    if unrelated:
        report.add(Finding(kind="potentially-unrelated", summary=f"{len(unrelated)} changed file(s) are not connected to the main change" + (" or the stated scope" if scope else ""),
                           severity=WARN, confidence=INFERRED, evidence=unrelated[:15],
                           consequence="drive-by edits widen review and blast radius", recommendation="confirm each is required by the task; otherwise revert or split it out"))
        reasons.append(("elevated", f"{len(unrelated)} file(s) unrelated to the main change"))

    code_dirs = sorted({c.path.split("/")[0] for c in changes if "/" in c.path and c.kind in ("source", "script")})
    if len(code_dirs) >= WIDE_SURFACE_DIRS:
        reasons.append(("elevated", f"code changed in {len(code_dirs)} top-level directories: {', '.join(code_dirs)}"))

    level = max((lvl for lvl, _ in reasons), key=LEVELS.index, default="low")
    report.meta["bloat_level"] = level
    report.meta["bloat_reasons"] = [r for _, r in reasons]
    report.add(Finding(kind="bloat-signal", summary=f"bloat signal: {level.upper()}" + ("" if reasons else " (size alone is not judged)"),
                       severity={"low": OK, "elevated": WARN, "high": WARN}[level], confidence=INFERRED, evidence=[r for _, r in reasons],
                       consequence="" if level == "low" else "the diff may be larger or wider than the task requires",
                       recommendation="" if level == "low" else "before presenting: look for the missed abstraction, the duplicated logic, or the unrelated file"))
    return report
