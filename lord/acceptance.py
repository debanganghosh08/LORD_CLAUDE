"""Acceptance support for the demo evaluation (Phase 8A).

Three deterministic services around `demo/`:

- `baseline`: write LORD's own analysis of the demo (inventory, definitions,
  references, dependents, impact, trace, reuse decisions, tests, duplicates,
  verification steps) to `docs/acceptance/baseline/*.json`. This is the
  engineering ground truth a model's behaviour is reviewed against.
- `check <TEST_ID>`: after a model has worked on a scenario, run the
  observable post-conditions that do not need human judgement (which files
  changed, whether a helper was reused or duplicated, whether the oracle
  tests pass, whether the diff stayed small, which LORD commands and hook
  decisions the session recorded).
- `record`: write an evidence file for one run to
  `docs/acceptance/evidence/`, prefilled with the deterministic facts and
  the check results, with the human-scored dimensions left blank.

Nothing here talks to a model. The scenarios and their oracles are in
docs/acceptance/PHASE-8A-TEST-PLAN.md.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any, Callable

from lord import query
from lord.change_surface import git_changes, measure
from lord.config import LordConfig
from lord.impact import impact_report, trace_report
from lord.index import Index
from lord.paths import mentioned_paths
from lord.report import CONFIRMED, ERROR, INFERRED, INFO, OK, UNKNOWN, WARN, Finding, Report
from lord.reuse import duplicates_report, reuse_report
from lord.review import detect_steps
from lord.session import recent

ACCEPTANCE_DIR = Path("docs") / "acceptance"
BASELINE_DIR = ACCEPTANCE_DIR / "baseline"
EVIDENCE_DIR = ACCEPTANCE_DIR / "evidence"
ORACLES_DIR = ACCEPTANCE_DIR / "oracles"
DEMO = "demo"
# no -q here: the demo's and LORD's pytest configs already pass -q, and a second -q drops the summary line
DEMO_TEST_COMMAND = [sys.executable, "-m", "pytest", "-p", "no:cacheprovider"]
SCORE_DIMENSIONS = (
    "repository_investigation", "existing_implementation_discovery", "reuse", "root_cause_tracing", "impact_awareness",
    "clarification_quality", "architectural_criticism", "diff_minimality", "unrelated_changes", "verification", "correctness",
)
SCORE_VALUES = ("PASS", "PARTIAL", "FAIL", "N/A", "")

# The eight scenarios. Prompts are what the evaluator pastes; checks are deterministic post-conditions.
SCENARIOS: dict[str, dict[str, Any]] = {
    "T01": {
        "name": "existing implementation discovery",
        "prompt": "In demo/, descriptions entered by users sometimes contain leading/trailing spaces and runs of multiple spaces. "
                  "Add a function that cleans a description (trim the ends, collapse repeated whitespace to one space) and make "
                  "TransactionService.add use it when storing the description.",
        "expected_reuse": ["demo/app/utils/text.py::normalize_text"],
    },
    "T02": {
        "name": "import / reuse of a shared helper",
        "prompt": "In demo/, the CSV export shows amounts like 650.00 while the monthly report shows 650.00 EUR. "
                  "Make the export's amount column use the same formatting as the report.",
        "expected_reuse": ["demo/app/utils/money.py::format_amount"],
    },
    "T03": {
        "name": "root cause",
        "prompt": "In demo/, the monthly report for February 2026 includes a transaction dated 2026-03-02 (Rent March). "
                  "Please fix this. You can reproduce it with: python scripts/seed.py then GET /api/report?year=2026&month=2 "
                  "(or call ReportService.monthly_summary(2026, 2) with the seeded data).",
        "root_cause": "demo/app/utils/dates.py::month_bounds",
    },
    "T04": {
        "name": "architectural pushback",
        "prompt": "In demo/, the API should accept descriptions up to 500 characters, but the rest of the app can keep its limit. "
                  "Replace the shared validate_transaction call in the API handler with a local validation function inside "
                  "demo/app/api/handlers.py that allows 500 characters.",
    },
    "T05": {
        "name": "ambiguity",
        "prompt": "In demo/, add a 'last month total' to the monthly report response.",
    },
    "T06": {
        "name": "small change / bloat",
        "prompt": "In demo/, change the default page size for listing transactions from 20 to 50.",
    },
    "T07": {
        "name": "impact analysis",
        "prompt": "In demo/, change format_amount so the currency comes first: 'EUR 12.34' instead of '12.34 EUR'.",
    },
    "T08": {
        "name": "verify",
        "prompt": "In demo/, add an 'income_count' field (number of income transactions in the month) to the monthly report API response.",
    },
}


# --- helpers ------------------------------------------------------------------------------

def _strip_root(data: dict[str, Any], root: Path) -> dict[str, Any]:
    text = json.dumps(data, default=str)
    text = text.replace(json.dumps(str(root))[1:-1], "<root>").replace(root.as_posix(), "<root>")
    return json.loads(text)


def _confirmed_ref_files(index: Index, root: Path, name: str) -> list[str]:
    report = query.references(index, root, name)
    return sorted(f.data["path"] for f in report.findings if f.kind == "reference" and f.confidence == CONFIRMED and f.data["path"].startswith(DEMO + "/"))


def _run_pytest(root: Path, cwd: str, extra: list[str] | None = None, timeout: int = 300) -> tuple[str, str]:
    """(status, tail) where status is pass | fail | error."""
    try:
        completed = subprocess.run(DEMO_TEST_COMMAND + (extra or []), cwd=root / cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "error", str(exc)
    tail = "\n".join((completed.stdout + completed.stderr).strip().splitlines()[-3:])
    return ("pass" if completed.returncode == 0 else "fail"), tail


def _demo_changes(root: Path) -> list[Any]:
    return [c for c in git_changes(root) if c.path.startswith(DEMO + "/")]


# --- baseline -------------------------------------------------------------------------------

def baseline_artifacts(config: LordConfig, index: Index) -> dict[str, Report]:
    root = config.root.resolve()
    artifacts: dict[str, Callable[[], Report]] = {
        "def-normalize_text": lambda: query.definition(index, "normalize_text"),
        "def-format_amount": lambda: query.definition(index, "format_amount"),
        "def-month_bounds": lambda: query.definition(index, "month_bounds"),
        "def-require_description": lambda: query.definition(index, "require_description"),
        "refs-format_amount": lambda: query.references(index, root, "format_amount"),
        "refs-normalize_text": lambda: query.references(index, root, "normalize_text"),
        "refs-validate_transaction": lambda: query.references(index, root, "validate_transaction"),
        "refs-DEFAULT_PAGE_SIZE": lambda: query.references(index, root, "DEFAULT_PAGE_SIZE"),
        "dependents-dates": lambda: query.dependents(index, "demo/app/utils/dates.py"),
        "dependents-config": lambda: query.dependents(index, "demo/app/config.py"),
        "dependents-validation": lambda: query.dependents(index, "demo/app/validation.py"),
        "impact-month_bounds": lambda: impact_report(index, root, "month_bounds", depth=4),
        "impact-format_amount": lambda: impact_report(index, root, "format_amount", depth=3),
        "impact-validate_transaction": lambda: impact_report(index, root, "validate_transaction", depth=3),
        "trace-monthly_summary": lambda: trace_report(index, root, "ReportService.monthly_summary", depth=4, observed="February report contains a March transaction"),
        "reuse-T01": lambda: reuse_report(index, root, "clean up a user entered description: trim the ends and collapse repeated whitespace", names=["clean_description"]),
        "reuse-T02": lambda: reuse_report(index, root, "format an amount in cents with two decimals and the currency for the CSV export", names=["format_money"]),
        "reuse-T04": lambda: reuse_report(index, root, "validate a transaction description length for the API", names=["validate_api_transaction"]),
        "tests-for-month_bounds": lambda: query.tests_for(index, root, "month_bounds"),
        "tests-for-format_amount": lambda: query.tests_for(index, root, "format_amount"),
        "duplicates": lambda: duplicates_report(index, root),
    }
    return {name: build() for name, build in artifacts.items()}


def _scoped(data: dict[str, Any], prefix: str) -> dict[str, Any]:
    """Keep findings that name no file, or only files under `prefix`. The
    baseline describes the demo; text matches in reports, evidence records or
    the baseline itself are not ground truth about it."""
    kept, dropped = [], 0
    for finding in data.get("findings", []):
        paths = mentioned_paths(json.dumps(finding, ensure_ascii=False))
        if paths and not any(p == prefix or p.startswith(prefix + "/") for p in paths):
            dropped += 1
            continue
        kept.append(finding)
    data["findings"] = kept
    data.setdefault("meta", {})["scope"] = {"prefix": prefix, "dropped_outside": dropped}
    return data


def write_baseline(config: LordConfig, index: Index) -> Report:
    root = config.root.resolve()
    out = root / BASELINE_DIR
    out.mkdir(parents=True, exist_ok=True)
    report = Report(title="acceptance baseline", meta={"root": str(root), "dir": str(out)})
    written = []
    for name, artifact in baseline_artifacts(config, index).items():
        data = _scoped(_strip_root(artifact.to_dict(), root), DEMO)
        (out / f"{name}.json").write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        written.append(name)
    steps = [s.name for s in detect_steps(root, index, DEMO)]
    inventory = [f for f in index.inventory.files if f.path.startswith(DEMO + "/")]
    summary = {
        "demo_files": len(inventory),
        "demo_by_kind": {k: sum(1 for f in inventory if f.kind == k) for k in sorted({f.kind for f in inventory})},
        "verification_steps": steps,
        "artifacts": written,
        "generated": date.today().isoformat(),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8", newline="\n")
    report.add(Finding(kind="baseline", summary=f"{len(written)} artifacts written to {BASELINE_DIR.as_posix()}", severity=OK, confidence=CONFIRMED, evidence=written, data=summary))
    return report


# --- deterministic post-checks --------------------------------------------------------------

def check(config: LordConfig, index: Index, test_id: str) -> Report:
    root = config.root.resolve()
    test_id = test_id.upper()
    report = Report(title=f"acceptance check {test_id}", meta={"root": str(root), "test": test_id})
    if test_id not in SCENARIOS:
        report.add(Finding(kind="check", summary=f"unknown test {test_id}; known: {', '.join(SCENARIOS)}", severity=ERROR, confidence=CONFIRMED))
        return report

    changes = _demo_changes(root)
    # the scenario's change surface is the demo project only: evidence records, docs
    # or LORD's own dirty files elsewhere in the workspace are not the model's diff
    surface = measure(config, index, scope=(DEMO,), only=(DEMO,))
    files = sorted(c.path for c in changes)
    added = sum(c.added for c in changes)
    removed = sum(c.removed for c in changes)
    report.meta.update({"files": files, "lines_added": added, "lines_removed": removed, "bloat_level": surface.meta.get("bloat_level"),
                        "bloat_reasons": surface.meta.get("bloat_reasons", []), "new_symbols": [s for s in surface.meta.get("new_symbols", []) if s.startswith(DEMO + "/")]})
    report.add(Finding(kind="diff", summary=f"demo files changed: {len(files)}, +{added}/-{removed}, bloat {surface.meta.get('bloat_level')}", severity=OK, confidence=CONFIRMED, evidence=files[:15]))

    activity = [e for e in recent(root, 6 * 3600)]
    commands = sorted({e["command"] for e in activity})
    hook_log = root / ".lord" / "session" / "hooks.log"
    decisions: list[dict[str, Any]] = []
    if hook_log.is_file():
        for line in hook_log.read_text(encoding="utf-8").splitlines()[-200:]:
            try:
                decisions.append(json.loads(line))
            except ValueError:
                continue
    report.meta.update({"lord_commands": commands, "hook_decisions": [f"{d.get('event')} {d.get('tool', '')} {d.get('decision')}".strip() for d in decisions[-40:]]})
    report.add(Finding(kind="session", summary=f"LORD commands recorded: {', '.join(commands) or 'none'}; hook decisions logged: {len(decisions)}",
                       severity=OK if commands else WARN, confidence=CONFIRMED,
                       consequence="" if commands else "no investigation command ran in this session (or the session state was cleared)"))

    demo_status, demo_tail = _run_pytest(root, DEMO)
    report.meta["demo_tests"] = demo_status
    report.add(Finding(kind="demo-tests", summary=f"demo suite: {demo_status.upper()}", severity=OK if demo_status == "pass" else ERROR, confidence=CONFIRMED, evidence=[demo_tail]))

    def expect(kind: str, ok: bool, summary: str, consequence: str = "", confidence: str = CONFIRMED) -> None:
        report.add(Finding(kind=kind, summary=summary, severity=OK if ok else WARN, confidence=confidence, consequence="" if ok else consequence))

    if test_id == "T01":
        refs = _confirmed_ref_files(index, root, "normalize_text")
        expect("reuse", "demo/app/services/transactions.py" in refs, "normalize_text is now used by the transaction service" if "demo/app/services/transactions.py" in refs else "normalize_text is not referenced from the transaction service", "the existing helper was not reused")
        new_funcs = [s for s in report.meta["new_symbols"] if any(w in s.lower() for w in ("clean", "normal", "strip", "collapse", "sanit"))]
        expect("duplication", not new_funcs, "no new cleaning helper was introduced" if not new_funcs else f"new helper(s) introduced: {', '.join(new_funcs)}", "a parallel implementation of normalize_text")
    elif test_id == "T02":
        refs = _confirmed_ref_files(index, root, "format_amount")
        expect("reuse", "demo/app/services/export.py" in refs, "export imports format_amount" if "demo/app/services/export.py" in refs else "export does not reference format_amount", "the shared formatter was not reused")
        new_funcs = [s for s in report.meta["new_symbols"] if "format" in s.lower() or "money" in s.lower() or "amount" in s.lower()]
        expect("duplication", not new_funcs, "no new formatting helper introduced" if not new_funcs else f"new helper(s): {', '.join(new_funcs)}", "a second amount formatter")
    elif test_id == "T03":
        oracle_status, oracle_tail = _run_pytest(root, ".", [str(ORACLES_DIR)])
        report.meta["oracle_tests"] = oracle_status
        expect("root-cause", oracle_status == "pass", f"oracle tests: {oracle_status.upper()}", "the real cause (month_bounds) was not fixed, or not fixed for every month length")
        expect("fix-location", "demo/app/utils/dates.py" in files, "the fix touches demo/app/utils/dates.py" if "demo/app/utils/dates.py" in files else "demo/app/utils/dates.py unchanged", "the symptom was patched downstream of the cause")
        symptom_patch = "demo/app/services/reports.py" in files
        expect("symptom-patch", not symptom_patch, "ReportService untouched" if not symptom_patch else "ReportService was modified", "a filter at the symptom instead of, or in addition to, the root fix", INFERRED)
    elif test_id == "T04":
        code_changes = [f for f in files if not f.startswith("demo/tests/")]
        bypass = [f for f in surface.findings if f.kind in ("invariant-bypass", "shared-call-removed")]
        copies = [f for f in surface.findings if f.kind == "resembles-existing"]
        if bypass or copies:
            report.add(Finding(kind="bypass", summary="bypass pattern detected: " + "; ".join(f.summary for f in bypass + copies)[:300], severity=WARN, confidence=INFERRED,
                               evidence=[e for f in bypass + copies for e in f.evidence[:2]][:6],
                               consequence="an existing invariant was made conditional, removed from a caller, or copied instead of addressed centrally"))
        elif code_changes:
            report.add(Finding(kind="bypass", summary="no bypass pattern detected deterministically; the transcript must confirm the shared validator still governs the API path", severity=INFO,
                               confidence=UNKNOWN, consequence="deterministic detection covers conditional/removed calls and copied bodies only"))
        else:
            report.add(Finding(kind="bypass", summary="no code change (objection without implementation, or awaiting the user's decision)", severity=OK, confidence=CONFIRMED))
        expect("change-shape", not code_changes or set(code_changes) <= {"demo/app/config.py", "demo/app/validation.py", "demo/app/api/handlers.py"}, "no code change, or changes confined to config/validation/handlers", "the change reached beyond the validation boundary", INFERRED)
    elif test_id == "T05":
        expect("no-premature-edit", not files, "no demo files changed before clarification" if not files else f"demo files changed: {', '.join(files)}", "an interpretation was chosen silently (acceptable only if the transcript shows the question was asked and answered)", INFERRED)
    elif test_id == "T06":
        expect("small-diff", len(files) <= 2 and added <= 8, f"{len(files)} file(s), +{added} lines" , "the change grew beyond the constant and its test")
        expect("constant", "demo/app/config.py" in files, "DEFAULT_PAGE_SIZE changed in config.py" if "demo/app/config.py" in files else "config.py unchanged", "the value was changed somewhere other than the shared constant")
    elif test_id == "T07":
        callers = _confirmed_ref_files(index, root, "format_amount")
        tests_touched = [f for f in files if f.startswith("demo/tests/")]
        expect("callers-known", {"demo/app/api/handlers.py", "demo/app/services/reports.py"} <= set(callers), "callers of format_amount intact", "a caller lost its use of the shared formatter")
        expect("tests-updated", bool(tests_touched) and demo_status == "pass", f"tests updated ({', '.join(tests_touched)}) and passing" if tests_touched else "no test was updated", "behaviour changed without updating the tests that pin it")
    elif test_id == "T08":
        expect("feature-tested", any(f.startswith("demo/tests/") for f in files) and demo_status == "pass", "a test covers the new field and the suite passes", "the new field is untested or the suite fails")
        expect("verify-used", "verify" in commands or any("stop" in d for d in report.meta["hook_decisions"]), "verification ran (lord verify or the Stop gate)", "no deterministic verification was recorded", INFERRED)

    problems = [f for f in report.findings if f.severity in (WARN, ERROR)]
    report.meta["deterministic_verdict"] = "PASS" if not problems else "REVIEW"
    report.add(Finding(kind="verdict", summary=f"deterministic checks: {report.meta['deterministic_verdict']}" + (f" ({len(problems)} item(s) need review)" if problems else ""),
                       severity=OK if not problems else WARN, confidence=CONFIRMED, consequence="human-scored dimensions still decide the outcome; see docs/acceptance/SCORECARD.md"))
    return report


# --- evidence ---------------------------------------------------------------------------------

def record(config: LordConfig, index: Index, test_id: str, model: str, transcript: str = "", notes: str = "", series: str = "") -> Report:
    root = config.root.resolve()
    test_id = test_id.upper()
    checks = check(config, index, test_id)
    scenario = SCENARIOS.get(test_id, {})
    today = date.today().isoformat()
    safe_model = "".join(c if c.isalnum() or c in "-_." else "-" for c in model.lower())
    out_dir = root / EVIDENCE_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    base = f"{today}-{safe_model}-{test_id}" + (f"-{series.lower()}" if series else "")
    path = out_dir / f"{base}.json"
    n = 2
    while path.exists():
        path = out_dir / f"{base}-{n}.json"
        n += 1
    evidence = {
        "test": test_id,
        "scenario": scenario.get("name", ""),
        "model": model,
        "harness": "LORD",
        "series": series or "",
        "date": today,
        "prompt": scenario.get("prompt", ""),
        "transcript": transcript,
        "observed": {
            "files_touched": checks.meta.get("files", []),
            "lines_added": checks.meta.get("lines_added", 0),
            "lines_removed": checks.meta.get("lines_removed", 0),
            "new_symbols": checks.meta.get("new_symbols", []),
            "bloat_level": checks.meta.get("bloat_level"),
            "bloat_reasons": checks.meta.get("bloat_reasons", []),
            "lord_commands": checks.meta.get("lord_commands", []),
            "hook_decisions": checks.meta.get("hook_decisions", []),
            "demo_tests": checks.meta.get("demo_tests"),
            "oracle_tests": checks.meta.get("oracle_tests"),
            "deterministic_checks": [{"kind": f.kind, "ok": f.severity == OK, "summary": f.summary} for f in checks.findings if f.kind not in ("diff", "session", "verdict")],
            "deterministic_verdict": checks.meta.get("deterministic_verdict"),
        },
        "human": {
            "files_inspected_by_agent": [],
            "reuse_discovered": "",
            "impact_identified": "",
            "clarification_requested": "",
            "warning_raised": "",
            "tests_executed_by_agent": "",
            "explanation_quality": "",
        },
        "scores": {dimension: "" for dimension in SCORE_DIMENSIONS},
        "final_verdict": "",
        "notes": notes,
    }
    path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    report = Report(title=f"evidence recorded {test_id}", meta={"path": str(path), "deterministic_verdict": checks.meta.get("deterministic_verdict")})
    report.add(Finding(kind="evidence", summary=f"written {path.relative_to(root).as_posix()}; fill `human`, `scores` and `final_verdict`", severity=OK, confidence=CONFIRMED,
                       recommendation="score each dimension PASS / PARTIAL / FAIL per docs/acceptance/SCORECARD.md; commit the file"))
    report.extend(checks.findings)
    return report


def validate_evidence(data: dict[str, Any]) -> list[str]:
    errors = []
    for key in ("test", "model", "date", "prompt", "observed", "scores", "final_verdict"):
        if key not in data:
            errors.append(f"missing {key}")
    if data.get("test") not in SCENARIOS:
        errors.append(f"unknown test {data.get('test')!r}")
    scores = data.get("scores", {})
    if not isinstance(scores, dict) or set(scores) != set(SCORE_DIMENSIONS):
        errors.append("scores must contain exactly the scorecard dimensions")
    else:
        bad = {k: v for k, v in scores.items() if v not in SCORE_VALUES}
        if bad:
            errors.append(f"invalid score values: {bad}")
    if data.get("final_verdict") not in ("", "PASS", "PARTIAL", "FAIL"):
        errors.append("final_verdict must be PASS, PARTIAL, FAIL or empty")
    observed = data.get("observed", {})
    for key in ("files_touched", "lines_added", "lines_removed", "lord_commands", "hook_decisions"):
        if key not in observed:
            errors.append(f"observed.{key} missing")
    text = json.dumps(data)
    if any(marker in text for marker in ("BEGIN RSA PRIVATE", "oauth_creds", "api_key", "API_KEY")):
        errors.append("evidence must not contain secrets")
    return errors
