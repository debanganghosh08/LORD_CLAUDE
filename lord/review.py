"""Review support: the deterministic half of senior-engineer behaviour.

`brief` runs the pre-edit investigation for one target and one intent in a
single call and returns a compact synthesis (definition, callers, dependents,
tests, config, consequences, reuse decision, workspace state) so the primary
agent spends one tool call, not ten, before planning.

`verify` runs the completion check: change surface and bloat signal, tests
that cover the changed files, unresolved markers introduced by the diff, the
project's own verification commands (detected from manifests) and, with
`run=True`, their real results. It ends with a verdict that is `verified`
only when every available step passed and nothing is outstanding.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from lord.change_surface import git_changes, measure
from lord.config import LordConfig
from lord.impact import impact_report, resolve_target
from lord.index import Index
from lord.query import references
from lord.report import CONFIRMED, ERROR, INFERRED, INFO, OK, UNKNOWN, WARN, Finding, Report
from lord.reuse import reuse_report

MARKER_RE = re.compile(r"\b(TODO|FIXME|XXX|HACK)\b")
NPM_DEFAULT_TEST = "no test specified"
STEP_TIMEOUT = 600


@dataclass
class Step:
    name: str
    argv: list[str]
    reason: str
    available: bool = True
    note: str = ""
    status: str = ""          # "", pass, fail, unavailable, timeout
    exit_code: int | None = None
    seconds: float = 0.0
    tail: list[str] = field(default_factory=list)
    cwd: str = ""             # sub-project directory relative to the workspace root ("" = root)


def _module_available(name: str) -> bool:
    completed = subprocess.run([sys.executable, "-c", f"import {name}"], capture_output=True)
    return completed.returncode == 0


def detect_steps(root: Path, index: Index, subdir: str = ".") -> list[Step]:
    """Verification commands a project supports, from its manifests.

    `subdir` selects a sub-project inside the workspace (a directory that
    holds its own manifest, for example `demo/`): only its files are
    considered, its commands run from that directory, and step names carry
    the prefix so a monorepo report stays readable.
    """
    prefix = "" if subdir in (".", "") else subdir.strip("/") + "/"
    label = "" if not prefix else f"{subdir.strip('/')}: "
    base = root if not prefix else root / subdir
    steps = [Step(label + s.name, s.argv, s.reason, s.available, s.note, cwd=prefix.rstrip("/")) for s in _detect_steps_in(base, index, prefix)]
    return steps


def _detect_steps_in(root: Path, index: Index, prefix: str) -> list[Step]:
    steps: list[Step] = []
    files = {f.path[len(prefix):] for f in index.inventory.files if f.path.startswith(prefix)}
    has_py_tests = any(f.kind == "test" and f.language == "python" and f.path.startswith(prefix) for f in index.inventory.files)
    pyproject = root / "pyproject.toml"
    py_config = pyproject.is_file() and "pytest" in pyproject.read_text(encoding="utf-8", errors="replace")
    if has_py_tests or py_config or "pytest.ini" in files or "tox.ini" in files:
        available = _module_available("pytest")
        steps.append(Step("pytest", [sys.executable, "-m", "pytest", "-q", "-x", "--no-header"], "Python tests detected",
                          available=available, note="" if available else "pytest is not installed for this interpreter"))
    ruff_configured = "ruff.toml" in files or (pyproject.is_file() and "[tool.ruff" in pyproject.read_text(encoding="utf-8", errors="replace"))
    if ruff_configured:
        exe = shutil.which("ruff")
        steps.append(Step("ruff", [exe or "ruff", "check", "."], "ruff configured", available=bool(exe), note="" if exe else "ruff not on PATH"))
    mypy_configured = "mypy.ini" in files or (pyproject.is_file() and "[tool.mypy" in pyproject.read_text(encoding="utf-8", errors="replace"))
    if mypy_configured:
        available = _module_available("mypy")
        steps.append(Step("mypy", [sys.executable, "-m", "mypy", "."], "mypy configured", available=available, note="" if available else "mypy not installed"))

    package = root / "package.json"
    if package.is_file():
        try:
            scripts = json.loads(package.read_text(encoding="utf-8", errors="replace")).get("scripts", {}) or {}
        except ValueError:
            scripts = {}
        npm = shutil.which("npm")
        for script, reason in (("test", "package.json test script"), ("lint", "package.json lint script"), ("typecheck", "package.json typecheck script"), ("build", "package.json build script")):
            command = scripts.get(script, "")
            if command and NPM_DEFAULT_TEST not in command:
                argv = [npm or "npm", "run", script, "--silent"] if script != "test" else [npm or "npm", "test", "--silent"]
                steps.append(Step(f"npm {script}", argv, reason, available=bool(npm), note="" if npm else "npm not on PATH"))
        if "tsconfig.json" in files and "typecheck" not in scripts:
            tsc = shutil.which("tsc") or (str(root / "node_modules" / ".bin" / ("tsc.cmd" if sys.platform == "win32" else "tsc")) if (root / "node_modules" / ".bin").is_dir() else None)
            steps.append(Step("tsc", [tsc or "tsc", "--noEmit"], "tsconfig.json present", available=bool(tsc and Path(tsc).exists()), note="" if tsc else "tsc not found"))
    if "Cargo.toml" in files:
        exe = shutil.which("cargo")
        steps.append(Step("cargo test", [exe or "cargo", "test", "--quiet"], "Cargo.toml present", available=bool(exe), note="" if exe else "cargo not on PATH"))
    if "go.mod" in files:
        exe = shutil.which("go")
        steps.append(Step("go test", [exe or "go", "test", "./..."], "go.mod present", available=bool(exe), note="" if exe else "go not on PATH"))
    return steps


def run_steps(root: Path, steps: list[Step], timeout: int = STEP_TIMEOUT) -> None:
    for step in steps:
        if not step.available:
            step.status = "unavailable"
            continue
        started = time.time()
        try:
            completed = subprocess.run(step.argv, cwd=root / step.cwd if step.cwd else root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        except subprocess.TimeoutExpired:
            step.status, step.seconds = "timeout", time.time() - started
            continue
        except OSError as exc:
            step.status, step.note = "unavailable", str(exc)
            continue
        step.seconds = time.time() - started
        step.exit_code = completed.returncode
        step.status = "pass" if completed.returncode == 0 else "fail"
        output = (completed.stdout + "\n" + completed.stderr).strip().splitlines()
        step.tail = output[-30:]


def _added_markers(root: Path, base: str | None, staged: bool) -> list[str]:
    args = ["git", "diff", "-U0", "--no-color"]
    args += [base] if base else (["--cached"] if staged else ["HEAD"])
    try:
        out = subprocess.run(args, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    except OSError:
        return []
    found, current = [], ""
    for line in out.splitlines():
        if line.startswith("+++ "):
            current = line[4:].removeprefix("b/")
        elif line.startswith("+") and not line.startswith("+++") and MARKER_RE.search(line):
            found.append(f"{current}: {line[1:].strip()[:100]}")
    return found


def verify(config: LordConfig, index: Index, scope: tuple[str, ...] = (), run: bool = False, base: str | None = None, staged: bool = False, timeout: int = STEP_TIMEOUT) -> Report:
    root = config.root.resolve()
    report = Report(title="verification", meta={"root": str(root), "ran": run})
    outstanding: list[str] = []

    surface = measure(config, index, base=base, staged=staged, scope=scope)
    summary = surface.findings[0]
    report.add(Finding(kind="change-surface", summary=summary.summary, severity=OK, confidence=CONFIRMED, evidence=summary.evidence[:15]))
    level = surface.meta.get("bloat_level", "low")
    if level != "low":
        report.add(Finding(kind="bloat-signal", summary=f"bloat signal {level.upper()}", severity=WARN, confidence=INFERRED, evidence=surface.meta.get("bloat_reasons", []),
                           recommendation="resolve or explicitly justify each reason in the final report"))
        outstanding.append(f"bloat signal {level}")
    for f in surface.findings:
        if f.kind in ("resembles-existing", "name-collision", "potentially-unrelated"):
            report.add(f)

    # tests covering the changed code files
    changes = git_changes(root, base, staged)
    changed_code = [c.path for c in changes if c.kind in ("source", "script") and c.status != "D"]
    covered: dict[str, list[str]] = {}
    test_kind = {f.path for f in index.inventory.files if f.kind == "test"}
    for path in changed_code:
        importers = [file for file, _ in index.importers_of(path) if file in test_kind]
        covered[path] = sorted(set(importers))
    uncovered = [p for p, tests in covered.items() if not tests and index.extraction_for(p) is not None]
    tests_to_run = sorted({t for tests in covered.values() for t in tests})
    if tests_to_run:
        report.add(Finding(kind="tests-to-run", summary=f"{len(tests_to_run)} test file(s) import the changed code", severity=OK, confidence=CONFIRMED, evidence=tests_to_run[:15]))
    if uncovered:
        report.add(Finding(kind="untested-change", summary=f"{len(uncovered)} changed code file(s) are imported by no test file", severity=WARN, confidence=INFERRED, evidence=uncovered[:15],
                           consequence="a regression there would pass the suite", recommendation="add or extend a test, or state why none is needed"))
        outstanding.append(f"{len(uncovered)} changed file(s) without tests")

    markers = _added_markers(root, base, staged)
    if markers:
        report.add(Finding(kind="unresolved-markers", summary=f"{len(markers)} TODO/FIXME/XXX/HACK marker(s) added by this change", severity=WARN, confidence=CONFIRMED, evidence=markers[:10],
                           recommendation="resolve them or list them as known follow-ups in the report"))
        outstanding.append(f"{len(markers)} unresolved marker(s)")

    # verification steps come from the sub-project(s) the changed code lives in
    # (a monorepo runs the demo's tests for a demo change, not the root suite)
    project_roots = sorted({index.inventory.project_root_of(p) for p in changed_code}) or ["."]
    steps = [s for r in project_roots for s in detect_steps(root, index, r)]
    report.meta["project_roots"] = project_roots
    if run:
        run_steps(root, steps, timeout=timeout)
    for step in steps:
        if not run:
            report.add(Finding(kind="verification-step", summary=f"{step.name}: {' '.join(step.argv[-3:])}", severity=OK if step.available else WARN, confidence=CONFIRMED,
                               evidence=[step.reason] + ([step.note] if step.note else []), recommendation="" if step.available else "install it or run the equivalent manually"))
            continue
        severity = {"pass": OK, "fail": ERROR, "timeout": ERROR, "unavailable": WARN}[step.status]
        report.add(Finding(kind="verification-step", summary=f"{step.name}: {step.status.upper()}" + (f" (exit {step.exit_code}, {step.seconds:.1f}s)" if step.exit_code is not None else ""),
                           severity=severity, confidence=CONFIRMED if step.status in ("pass", "fail") else UNKNOWN,
                           evidence=(step.tail[-12:] if step.status == "fail" else ([step.note] if step.note else [])),
                           recommendation="fix before reporting completion" if step.status in ("fail", "timeout") else ""))
        if step.status in ("fail", "timeout"):
            outstanding.append(f"{step.name} {step.status}")
        elif step.status == "unavailable":
            outstanding.append(f"{step.name} could not run")
    if not steps:
        report.add(Finding(kind="verification-step", summary="no test/lint/build command detected from manifests", severity=WARN, confidence=UNKNOWN,
                           recommendation="state how the change was verified manually"))
        outstanding.append("no automated verification detected")
    if not run and steps:
        outstanding.append("verification steps not executed (use --run)")

    verdict = "verified" if not outstanding else "not verified"
    report.meta.update({"verdict": verdict, "outstanding": outstanding, "steps": [s.name for s in steps],
                        "step_results": {s.name: s.status for s in steps if s.status}, "bloat_level": level, "tests_to_run": tests_to_run, "uncovered": uncovered})
    report.add(Finding(kind="verdict", summary=f"{verdict.upper()}" + (": " + "; ".join(outstanding) if outstanding else ": all detected steps passed, nothing outstanding"),
                       severity=OK if verdict == "verified" else WARN, confidence=CONFIRMED if run else INFERRED,
                       consequence="" if verdict == "verified" else "do not report the task as done; report what remains"))
    return report


def brief(config: LordConfig, index: Index, target: str, intent: str = "", names: list[str] | None = None, depth: int = 2) -> Report:
    """One-call pre-edit synthesis for the primary agent."""
    root = config.root.resolve()
    report = Report(title=f"brief: {target}", meta={"root": str(root), "intent": intent})
    resolved = resolve_target(index, target)
    if resolved is None:
        report.add(Finding(kind="target", summary=f"{target!r} is not an indexed file or symbol", severity=WARN, confidence=UNKNOWN,
                           recommendation="use `lord related` to find the right name; the target may live in an unsupported language"))
    else:
        impact = impact_report(index, root, target, depth=depth)
        keep = {"definition": 3, "ambiguity": 1, "direct-reference": 8, "indirect-reference": 4, "related-type": 4, "test": 5, "config": 3, "boundary": 1, "consequence": 8}
        counts: dict[str, int] = {}
        for f in impact.findings:
            limit = keep.get(f.kind)
            if limit is None:
                continue
            counts[f.kind] = counts.get(f.kind, 0) + 1
            if counts[f.kind] <= limit:
                report.add(f)
        if resolved[0] == "symbol":
            refs = references(index, root, target)
            report.add(Finding(kind="reference-summary", summary=f"{refs.meta['confirmed_files']} file(s) with confirmed uses, {refs.meta['inferred_files']} with text-only matches",
                               severity=OK, confidence=CONFIRMED, evidence=refs.meta["callers"][:10]))
        report.meta.update({k: impact.meta.get(k) for k in ("direct_callers", "dependents", "tests", "config", "overall_confidence")})

    if intent:
        reuse = reuse_report(index, root, intent, names=names or [])
        for f in reuse.findings:
            if f.kind in ("exists", "decision") or f.kind.startswith("candidate-reuse"):
                report.add(f)
        report.meta["reuse_decision"] = reuse.meta["decision"]

    changes = git_changes(root)
    if changes:
        report.add(Finding(kind="workspace-state", summary=f"working tree already has {len(changes)} uncommitted change(s)", severity=INFO, confidence=CONFIRMED,
                           evidence=[f"{c.status} {c.path}" for c in changes[:10]], consequence="separate unrelated in-progress work from this task"))
    report.add(Finding(kind="next", summary="open every direct caller and the definition before planning; the brief says where to look, not what the code means",
                       severity=INFO, confidence=CONFIRMED))
    return report
