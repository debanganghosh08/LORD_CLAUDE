"""Phase 8A tests: the demo works, the planted traps are live, LORD's analysis
of the demo matches the documented ground truth, sub-project verification is
detected, and the acceptance tooling (baseline, checks, evidence) behaves."""

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
from lord.report import CONFIRMED
from lord.reuse import reuse_report
from lord.review import detect_steps, verify

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "demo"
ORACLES = ROOT / "docs" / "acceptance" / "oracles"


@pytest.fixture(scope="module")
def index():
    return ensure_index(load_config(ROOT))


def _pytest(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *args], cwd=cwd, capture_output=True, text=True, timeout=300)


@pytest.fixture(scope="module")
def lord_clone(tmp_path_factory) -> Path:
    """A committed copy of the repository: checks that compare the working tree with HEAD need a clean base."""
    repo = tmp_path_factory.mktemp("clone") / "lord"
    for item in ("lord", "demo", "docs", "tests", "pyproject.toml", "lord.toml", ".gitignore", ".agents"):
        src = ROOT / item
        if src.is_dir():
            shutil.copytree(src, repo / item, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "evidence-test"))
        else:
            shutil.copy(src, repo / item)
    for cmd in (["init", "-q", "-b", "main"], ["config", "user.email", "t@example.com"], ["config", "user.name", "t"], ["config", "core.autocrlf", "false"], ["add", "-A"], ["commit", "-q", "-m", "base"]):
        subprocess.run(["git", *cmd], cwd=repo, check=True, capture_output=True)
    return repo


# --- the demo itself ---------------------------------------------------------------------

def test_demo_suite_passes():
    completed = _pytest(DEMO)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "passed" in completed.stdout


def test_root_cause_trap_is_live():
    """The oracle must fail on the unmodified demo: if it passes, the trap was fixed or removed."""
    completed = _pytest(ROOT, str(ORACLES))
    assert completed.returncode != 0 and completed.stdout.count("FAILED docs/acceptance/oracles") == 3, completed.stdout


def test_demo_has_no_dependencies_and_layers_flow_downward(index):
    text = (DEMO / "pyproject.toml").read_text(encoding="utf-8")
    assert "dependencies = []" in text
    for path in ("demo/app/utils/money.py", "demo/app/utils/text.py", "demo/app/utils/dates.py", "demo/app/config.py", "demo/app/models.py"):
        internal = query.deps(index, path).meta["internal"]
        assert all(i.startswith("demo/app/config.py") or i.startswith("demo/app/models.py") for i in internal), (path, internal)


# --- ground truth LORD must establish ----------------------------------------------------

def test_reuse_traps_are_discoverable(index):
    defs = {n: [f.summary for f in query.definition(index, n).findings if f.kind == "definition" and "demo/" in f.summary] for n in
            ("normalize_text", "format_amount", "month_bounds", "require_description", "validate_transaction", "DEFAULT_PAGE_SIZE")}
    assert all(len(v) == 1 for v in defs.values()), defs
    fmt = query.references(index, ROOT, "format_amount")
    confirmed = {f.data["path"] for f in fmt.findings if f.kind == "reference" and f.confidence == CONFIRMED and f.data["path"].startswith("demo/")}
    assert confirmed == {"demo/app/api/handlers.py", "demo/app/services/reports.py", "demo/tests/test_money.py"}
    assert "demo/app/services/export.py" not in confirmed, "trap A: export formats inline and must not already use the helper"
    norm = query.references(index, ROOT, "normalize_text")
    assert {f.data["path"] for f in norm.findings if f.kind == "reference" and f.confidence == CONFIRMED and f.data["path"].startswith("demo/")} == {"demo/app/utils/text.py", "demo/tests/test_text.py"}
    assert query.dependents(index, "demo/app/config.py").meta["dependents"].count("demo/app/api/handlers.py") == 1
    assert len(query.dependents(index, "demo/app/config.py").meta["dependents"]) >= 8, "trap C: the shared constants have many consumers"


def test_reuse_decisions_point_at_existing_code(index):
    t01 = reuse_report(index, ROOT, acceptance.SCENARIOS["T01"]["prompt"], names=["clean_description"])
    assert t01.meta["decision"] == "extend"
    assert any("normalize_text" in f.summary for f in t01.findings if f.kind == "candidate-reuse-or-extend")
    t02 = reuse_report(index, ROOT, "format an amount with two decimals and the currency for the CSV export", names=["format_money"])
    strong = [f.summary for f in t02.findings if f.kind == "candidate-reuse-or-extend"]
    assert t02.meta["decision"] == "extend" and "format_amount" in strong[0]
    t_val = reuse_report(index, ROOT, "reject transactions with an empty description", names=["validate_description"])
    strong = [f.summary for f in t_val.findings if f.kind == "candidate-reuse-or-extend"]
    assert t_val.meta["decision"] == "extend" and any("require_description" in s or "validate_transaction" in s for s in strong[:2])


def test_root_cause_chain_is_traceable(index):
    impact = impact_report(index, ROOT, "month_bounds", depth=4)
    assert impact.meta["direct_callers"] == ["demo/app/services/transactions.py::TransactionService.in_month", "demo/tests/test_dates.py::test_month_bounds_march"]
    indirect = set(impact.meta["indirect_callers"])
    assert {"demo/app/services/reports.py::ReportService.monthly_summary", "demo/app/services/export.py::ExportService.monthly_csv", "demo/app/api/handlers.py::monthly_report"} <= indirect
    assert "docs/acceptance/oracles/test_root_cause_oracle.py" not in " ".join(impact.meta["tests"]), "oracles must be excluded from the index"
    trace = trace_report(index, ROOT, "ReportService.monthly_summary", depth=4, observed="February report contains a March transaction")
    causes = trace.meta["candidate_causes"]
    assert causes[0] == "demo/app/services/transactions.py::TransactionService.in_month"
    assert "demo/app/utils/dates.py::month_bounds" in causes
    chain = next(f.evidence[0] for f in trace.findings if f.kind == "candidate-cause" and f.summary.startswith("demo/app/utils/dates.py::month_bounds"))
    assert chain == "demo/app/services/reports.py::ReportService.monthly_summary -> demo/app/services/transactions.py::TransactionService.in_month -> demo/app/utils/dates.py::month_bounds"
    assert not any(c.startswith("lord/") for c in causes), "unknown-receiver resolution must stay inside the demo project"


def test_impact_of_shared_formatter_lists_callers_and_tests(index):
    impact = impact_report(index, ROOT, "format_amount", depth=3)
    direct = [c for c in impact.meta["direct_callers"] if c.startswith("demo/app/")]
    assert direct == ["demo/app/api/handlers.py::monthly_report", "demo/app/services/reports.py::ReportService.render"]
    assert impact.meta["tests"] == ["demo/tests/test_money.py"]


def test_verification_steps_detected_per_project(index):
    steps = detect_steps(ROOT, index, "demo")
    assert [s.name for s in steps] == ["demo: pytest"] and steps[0].cwd == "demo"
    assert steps[0].argv[-3:] == ["-q", "-x", "--no-header"]


def test_check_on_committed_unmodified_demo_reports_review_items(lord_clone: Path):
    config = load_config(lord_clone)
    report = acceptance.check(config, ensure_index(config), "T02")
    assert report.meta["files"] == [] and report.meta["demo_tests"] == "pass", report.to_markdown()
    kinds = {f.kind: f for f in report.findings}
    assert kinds["reuse"].severity == "warn" and kinds["verdict"].summary.startswith("deterministic checks: REVIEW")


def test_verify_runs_demo_tests_for_a_demo_change(lord_clone: Path):
    target = lord_clone / "demo" / "app" / "utils" / "text.py"
    original = target.read_text(encoding="utf-8")
    target.write_text(original + "\n\ndef shout(value: str) -> str:\n    return normalize_text(value).upper()\n", encoding="utf-8", newline="\n")
    try:
        config = load_config(lord_clone)
        report = verify(config, ensure_index(config), run=True, timeout=240)
        assert report.meta["project_roots"] == ["demo"] and report.meta["steps"] == ["demo: pytest"]
        assert report.meta["step_results"] == {"demo: pytest": "pass"}, report.to_markdown()
    finally:
        target.write_text(original, encoding="utf-8", newline="\n")


# --- acceptance tooling --------------------------------------------------------------------

def test_baseline_writes_root_free_artifacts(index):
    config = load_config(ROOT)
    artifacts = acceptance.baseline_artifacts(config, index)
    assert set(artifacts) >= {"refs-format_amount", "impact-month_bounds", "trace-monthly_summary", "reuse-T01", "reuse-T02", "duplicates"}
    stripped = acceptance._strip_root(artifacts["impact-month_bounds"].to_dict(), ROOT)
    assert "<root>" in json.dumps(stripped) and str(ROOT) not in json.dumps(stripped)
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


def test_check_rejects_unknown_test(index):
    assert acceptance.check(load_config(ROOT), index, "T99").has_errors


def test_record_and_validate_evidence(index, monkeypatch):
    monkeypatch.setattr(acceptance, "EVIDENCE_DIR", Path("docs") / "acceptance" / "evidence-test")
    out = ROOT / acceptance.EVIDENCE_DIR
    try:
        report = acceptance.record(load_config(ROOT), index, "T06", "gemini-test", transcript="conv-123", notes="dry run")
        path = Path(report.meta["path"])
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["test"] == "T06" and data["model"] == "gemini-test" and data["transcript"] == "conv-123"
        assert set(data["scores"]) == set(acceptance.SCORE_DIMENSIONS) and all(v == "" for v in data["scores"].values())
        assert data["observed"]["demo_tests"] == "pass" and isinstance(data["observed"]["hook_decisions"], list)
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


def test_cli_acceptance_commands(index):
    def run(*args: str) -> dict:
        completed = subprocess.run([sys.executable, "-m", "lord", "--root", str(ROOT), "acceptance", *args, "--json"], cwd=ROOT, capture_output=True, text=True, timeout=600)
        assert completed.returncode in (0, 1), completed.stderr
        return json.loads(completed.stdout)

    prompts = run("prompts")
    assert [f["kind"] for f in prompts["findings"]] == list(acceptance.SCENARIOS)
    assert run("check", "--test", "T06")["meta"]["test"] == "T06"
