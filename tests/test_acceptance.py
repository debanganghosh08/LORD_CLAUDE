"""Acceptance tests (Phase 8A; separate workspace since 8B): the demo works,
the planted traps are live, LORD's analysis of the demo matches the documented
ground truth, sub-project verification is detected, and the acceptance
tooling (workspace export, baseline, checks, evidence) behaves.

The demo is analysed only as a separate Git repository exported from the
template in tests/fixtures/demo_workspace/, never as part of LORD."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from lord import acceptance, query
from lord.config import load_config
from lord.impact import impact_report, trace_report
from lord.index import ensure_index
from lord.memory import Store
from lord.report import CONFIRMED
from lord.reuse import reuse_report
from lord.review import detect_steps, verify

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "tests" / "fixtures" / "demo_workspace"
ORACLES = ROOT / "docs" / "acceptance" / "oracles"


@pytest.fixture(scope="module")
def workspace(tmp_path_factory) -> Path:
    """The separate acceptance workspace, exactly as an evaluator creates it."""
    out = tmp_path_factory.mktemp("acceptance") / "ledger-workspace"
    report = acceptance.export_workspace(out)
    assert not report.has_errors, report.to_markdown()
    return out


@pytest.fixture(scope="module")
def index(workspace: Path):
    return ensure_index(load_config(workspace))


def _pytest(cwd: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    import os

    return subprocess.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *args], cwd=cwd, capture_output=True, text=True, timeout=300,
                          env={**os.environ, **(env or {})})


# --- the separate workspace ------------------------------------------------------------------

def test_workspace_is_a_separate_repository_without_lord(workspace: Path):
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=workspace, capture_output=True, text=True).stdout.strip()
    assert Path(top).resolve() == workspace.resolve()
    assert subprocess.run(["git", "status", "--porcelain"], cwd=workspace, capture_output=True, text=True).stdout == "", "the baseline is committed"
    present = {p.name for p in workspace.iterdir()} - {".lord"}   # LORD's runtime state, self-ignored
    assert present == {".git", ".gitignore", "demo"}, present
    if (workspace / ".lord").is_dir():
        assert subprocess.run(["git", "check-ignore", "-q", ".lord/index.json"], cwd=workspace).returncode == 0, ".lord/ ignores itself"
    for absent in ("lord", "plugin", ".agents", "docs", "lord.toml", "AGENTS.md", "CLAUDE.md"):
        assert not (workspace / absent).exists(), absent
    files = subprocess.run(["git", "ls-files"], cwd=workspace, capture_output=True, text=True).stdout.split()
    assert files and all(f.startswith("demo/") or f == ".gitignore" for f in files)
    assert not any("oracle" in f or "__pycache__" in f or f.startswith("demo/data/") for f in files)


def test_export_refuses_the_lord_repository_and_non_empty_directories(tmp_path: Path):
    inside = acceptance.export_workspace(ROOT / ".lord" / "ws-inside")
    assert inside.has_errors and "inside the LORD repository" in inside.findings[0].summary
    busy = tmp_path / "busy"
    busy.mkdir()
    (busy / "keep.txt").write_text("user file", encoding="utf-8")
    refused = acceptance.export_workspace(busy)
    assert refused.has_errors and (busy / "keep.txt").read_text(encoding="utf-8") == "user file" and len(list(busy.iterdir())) == 1


def test_lord_does_not_index_the_template_or_see_the_demo():
    lord_index = ensure_index(load_config(ROOT))
    assert not [f.path for f in lord_index.inventory.files if f.path.startswith("tests/fixtures/demo_workspace/")]
    assert not [f.path for f in lord_index.inventory.files if f.path.startswith("demo/")]
    missing = acceptance.check(load_config(ROOT), lord_index, "T01")
    assert missing.has_errors and "separate workspace" in missing.findings[0].summary


def test_workspace_memory_is_isolated_from_lord(workspace: Path):
    """LORD's own durable memory (docs/state in the LORD repository) never
    reaches the evaluated workspace; the workspace starts with none."""
    assert (ROOT / "docs" / "state" / "memory.jsonl").is_file()
    assert Store(workspace).load().items == {}
    completed = subprocess.run([sys.executable, "-m", "lord", "--root", str(workspace), "context", "demo/app/utils/text.py", "--json"],
                               cwd=ROOT, capture_output=True, text=True, timeout=300)
    data = json.loads(completed.stdout)
    kinds = {f["kind"] for f in data["findings"]}
    assert not kinds & {"decision", "fact", "discovery", "trap", "convention", "unresolved", "handoff"}, kinds
    assert "M-00" not in completed.stdout


# --- the demo itself ---------------------------------------------------------------------

def test_demo_suite_passes(workspace: Path):
    completed = _pytest(workspace / "demo")
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "passed" in completed.stdout


def test_root_cause_trap_is_live(workspace: Path):
    """The oracle must fail on the unmodified demo: if it passes, the trap was fixed or removed."""
    for env in ({acceptance.ORACLE_ENV: str(workspace / "demo")}, {}):  # the exported demo, and the template by default
        completed = _pytest(ROOT, str(ORACLES), env=env)
        assert completed.returncode != 0 and completed.stdout.count("FAILED docs/acceptance/oracles") == 3, completed.stdout


def test_demo_has_no_dependencies_and_layers_flow_downward(workspace: Path, index):
    text = (workspace / "demo" / "pyproject.toml").read_text(encoding="utf-8")
    assert "dependencies = []" in text
    for path in ("demo/app/utils/money.py", "demo/app/utils/text.py", "demo/app/utils/dates.py", "demo/app/config.py", "demo/app/models.py"):
        internal = query.deps(index, path).meta["internal"]
        assert all(i.startswith("demo/app/config.py") or i.startswith("demo/app/models.py") for i in internal), (path, internal)


# --- ground truth LORD must establish ----------------------------------------------------

def test_reuse_traps_are_discoverable(workspace: Path, index):
    defs = {n: [f.summary for f in query.definition(index, n).findings if f.kind == "definition" and "demo/" in f.summary] for n in
            ("normalize_text", "format_amount", "month_bounds", "require_description", "validate_transaction", "DEFAULT_PAGE_SIZE")}
    assert all(len(v) == 1 for v in defs.values()), defs
    fmt = query.references(index, workspace, "format_amount")
    confirmed = {f.data["path"] for f in fmt.findings if f.kind == "reference" and f.confidence == CONFIRMED and f.data["path"].startswith("demo/")}
    assert confirmed == {"demo/app/api/handlers.py", "demo/app/services/reports.py", "demo/tests/test_money.py"}
    assert "demo/app/services/export.py" not in confirmed, "trap A: export formats inline and must not already use the helper"
    norm = query.references(index, workspace, "normalize_text")
    assert {f.data["path"] for f in norm.findings if f.kind == "reference" and f.confidence == CONFIRMED and f.data["path"].startswith("demo/")} == {"demo/app/utils/text.py", "demo/tests/test_text.py"}
    assert query.dependents(index, "demo/app/config.py").meta["dependents"].count("demo/app/api/handlers.py") == 1
    assert len(query.dependents(index, "demo/app/config.py").meta["dependents"]) >= 8, "trap C: the shared constants have many consumers"


def test_reuse_decisions_point_at_existing_code(workspace: Path, index):
    t01 = reuse_report(index, workspace, acceptance.SCENARIOS["T01"]["prompt"], names=["clean_description"])
    assert t01.meta["decision"] == "extend"
    assert any("normalize_text" in f.summary for f in t01.findings if f.kind == "candidate-reuse-or-extend")
    t02 = reuse_report(index, workspace, "format an amount with two decimals and the currency for the CSV export", names=["format_money"])
    strong = [f.summary for f in t02.findings if f.kind == "candidate-reuse-or-extend"]
    assert t02.meta["decision"] == "extend" and "format_amount" in strong[0]
    t_val = reuse_report(index, workspace, "reject transactions with an empty description", names=["validate_description"])
    strong = [f.summary for f in t_val.findings if f.kind == "candidate-reuse-or-extend"]
    assert t_val.meta["decision"] == "extend" and any("require_description" in s or "validate_transaction" in s for s in strong[:2])


def test_root_cause_chain_is_traceable(workspace: Path, index):
    impact = impact_report(index, workspace, "month_bounds", depth=4)
    assert impact.meta["direct_callers"] == ["demo/app/services/transactions.py::TransactionService.in_month", "demo/tests/test_dates.py::test_month_bounds_march"]
    indirect = set(impact.meta["indirect_callers"])
    assert {"demo/app/services/reports.py::ReportService.monthly_summary", "demo/app/services/export.py::ExportService.monthly_csv", "demo/app/api/handlers.py::monthly_report"} <= indirect
    assert "oracle" not in " ".join(impact.meta["tests"]), "oracles never reach the evaluated workspace"
    trace = trace_report(index, workspace, "ReportService.monthly_summary", depth=4, observed="February report contains a March transaction")
    causes = trace.meta["candidate_causes"]
    assert causes[0] == "demo/app/services/transactions.py::TransactionService.in_month"
    assert "demo/app/utils/dates.py::month_bounds" in causes
    chain = next(f.evidence[0] for f in trace.findings if f.kind == "candidate-cause" and f.summary.startswith("demo/app/utils/dates.py::month_bounds"))
    assert chain == "demo/app/services/reports.py::ReportService.monthly_summary -> demo/app/services/transactions.py::TransactionService.in_month -> demo/app/utils/dates.py::month_bounds"


def test_impact_of_shared_formatter_lists_callers_and_tests(workspace: Path, index):
    impact = impact_report(index, workspace, "format_amount", depth=3)
    direct = [c for c in impact.meta["direct_callers"] if c.startswith("demo/app/")]
    assert direct == ["demo/app/api/handlers.py::monthly_report", "demo/app/services/reports.py::ReportService.render"]
    assert impact.meta["tests"] == ["demo/tests/test_money.py"]


def test_verification_steps_detected_per_project(workspace: Path, index):
    steps = detect_steps(workspace, index, "demo")
    assert [s.name for s in steps] == ["demo: pytest"] and steps[0].cwd == "demo"
    assert steps[0].argv[-3:] == ["-q", "-x", "--no-header"]


def test_check_on_committed_unmodified_demo_reports_review_items(workspace: Path, index):
    report = acceptance.check(load_config(workspace), index, "T02")
    assert report.meta["files"] == [] and report.meta["demo_tests"] == "pass" and report.meta["separate_workspace"] is True, report.to_markdown()
    kinds = {f.kind: f for f in report.findings}
    assert kinds["reuse"].severity == "warn" and kinds["verdict"].summary.startswith("deterministic checks: REVIEW")


def test_every_check_states_its_basis(workspace: Path, index):
    """An acceptance check never presents a heuristic as a fact."""
    for test_id in ("T01", "T04", "T05", "T06", "T08"):
        report = acceptance.check(load_config(workspace), index, test_id)
        for f in report.findings:
            if f.kind in ("diff", "session", "demo-tests", "verdict"):
                continue
            basis = (f.data or {}).get("basis")
            assert basis in (acceptance.FACT, acceptance.HEURISTIC, acceptance.HUMAN), (test_id, f.kind)
            assert f.summary.startswith(f"[{basis}]"), (test_id, f.summary)
            assert f.confidence == {acceptance.FACT: "confirmed", acceptance.HEURISTIC: "inferred", acceptance.HUMAN: "unknown"}[basis], (test_id, f.kind)
    t05 = acceptance.check(load_config(workspace), index, "T05")
    assert {f.kind: (f.data or {}).get("basis") for f in t05.findings}["no-premature-edit"] == acceptance.HUMAN


def test_verify_runs_demo_tests_for_a_demo_change(workspace: Path):
    target = workspace / "demo" / "app" / "utils" / "text.py"
    original = target.read_text(encoding="utf-8")
    target.write_text(original + "\n\ndef shout(value: str) -> str:\n    return normalize_text(value).upper()\n", encoding="utf-8", newline="\n")
    try:
        config = load_config(workspace)
        report = verify(config, ensure_index(config), run=True, timeout=240)
        assert report.meta["project_roots"] == ["demo"] and report.meta["steps"] == ["demo: pytest"]
        assert report.meta["step_results"] == {"demo: pytest": "pass"}, report.to_markdown()
    finally:
        target.write_text(original, encoding="utf-8", newline="\n")


# --- acceptance tooling --------------------------------------------------------------------

def test_baseline_writes_root_free_artifacts(workspace: Path, index):
    config = load_config(workspace)
    artifacts = acceptance.baseline_artifacts(config, index)
    assert set(artifacts) >= {"refs-format_amount", "impact-month_bounds", "trace-monthly_summary", "reuse-T01", "reuse-T02", "duplicates"}
    stripped = acceptance._strip_root(artifacts["impact-month_bounds"].to_dict(), workspace)
    assert "<root>" in json.dumps(stripped) and str(workspace) not in json.dumps(stripped)
    committed = ROOT / "docs" / "acceptance" / "baseline" / "summary.json"
    assert committed.is_file()
    summary = json.loads(committed.read_text(encoding="utf-8"))
    assert summary["verification_steps"] == ["demo: pytest"] and summary["demo_files"] >= 30


def test_scenarios_have_prompts_and_documented_oracles():
    plan = (ROOT / "docs" / "acceptance" / "PHASE-8A-TEST-PLAN.md").read_text(encoding="utf-8")
    for test_id, scenario in acceptance.SCENARIOS.items():
        assert f"## {test_id}" in plan, test_id
        assert scenario["prompt"].split(".")[0] in plan, f"{test_id} prompt drifted from the plan"
    for heading in ("USER PROMPT", "EXPECTED FILE INVESTIGATION", "EXPECTED REUSE BEHAVIOR", "EXPECTED ARCHITECTURAL WARNING", "EXPECTED DIFF CHARACTERISTICS", "EXPECTED VERIFICATION", "FAILURE CONDITIONS"):
        assert plan.count(heading) >= 8, heading


def test_check_rejects_unknown_test(workspace: Path, index):
    assert acceptance.check(load_config(workspace), index, "T99").has_errors


def test_record_and_validate_evidence(workspace: Path, index, monkeypatch):
    monkeypatch.setattr(acceptance, "EVIDENCE_DIR", Path("docs") / "acceptance" / "evidence-test")
    out = ROOT / acceptance.EVIDENCE_DIR
    try:
        reply = "Changed: nothing.\n\nVerification:\n  python -m pytest -q (demo) - PASS\n  LORD verify - VERIFIED\n"
        report = acceptance.record(load_config(workspace), index, "T06", "gemini-test", transcript="conv-123", notes="dry run", reply=reply)
        path = Path(report.meta["path"])
        assert path.parent == out
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["test"] == "T06" and data["model"] == "gemini-test" and data["transcript"] == "conv-123"
        assert data["workspace"] == "separate repository" and str(workspace) not in json.dumps(data), "no machine path in tracked evidence"
        assert set(data["scores"]) == set(acceptance.SCORE_DIMENSIONS) and all(v == "" for v in data["scores"].values())
        assert data["observed"]["demo_tests"] == "pass" and isinstance(data["observed"]["hook_decisions"], list)
        # the reply claims success but LORD never ran in this workspace: a claim, not a fact
        assert data["observed"]["verification"]["status"] == "UNVERIFIED CLAIM" and data["observed"]["verification"]["basis"] == "model-reported"
        assert all(c["basis"] in (acceptance.FACT, acceptance.HEURISTIC, acceptance.HUMAN) for c in data["observed"]["deterministic_checks"])
        assert acceptance.validate_evidence(data) == []
        data["scores"]["reuse"] = "GREAT"
        data["test"] = "T42"
        assert len(acceptance.validate_evidence(data)) == 2
    finally:
        shutil.rmtree(out, ignore_errors=True)


def test_committed_evidence_files_are_valid():
    evidence_dir = ROOT / "docs" / "acceptance" / "evidence"
    for path in evidence_dir.glob("*.json"):
        if path.name == "TEMPLATE.json":
            continue
        errors = acceptance.validate_evidence(json.loads(path.read_text(encoding="utf-8")))
        assert errors == [], (path.name, errors)


def test_cli_acceptance_commands(workspace: Path, tmp_path: Path):
    def run(*args: str) -> dict:
        completed = subprocess.run([sys.executable, "-m", "lord", "acceptance", *args, "--json"], cwd=ROOT, capture_output=True, text=True, timeout=600)
        assert completed.returncode in (0, 1), completed.stderr
        return json.loads(completed.stdout)

    prompts = run("prompts")
    assert [f["kind"] for f in prompts["findings"]] == list(acceptance.SCENARIOS)
    assert run("check", "--workspace", str(workspace), "--test", "T06")["meta"]["test"] == "T06"
    created = run("workspace", "--out", str(tmp_path / "second"))
    assert created["meta"]["files"] >= 30 and (tmp_path / "second" / "demo" / "app" / "config.py").is_file()
