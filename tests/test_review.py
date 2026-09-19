"""Phase 5 tests: brief, verify (detection and execution), and the specialist
agent / critical-review adapter structure."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from lord.config import load_config
from lord.index import ensure_index
from lord.report import CONFIRMED, INFERRED, UNKNOWN
from lord.review import brief, detect_steps, verify

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "tests" / "fixtures" / "sample_repo"
DUP = ROOT / "tests" / "fixtures" / "dup_repo"


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    return completed.stdout


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _init_git(repo: Path) -> None:
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "core.autocrlf", "false")
    _write(repo / ".gitignore", ".lord/\n.pytest_cache/\n__pycache__/\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")


@pytest.fixture
def sample(tmp_path: Path) -> Path:
    target = tmp_path / "sample_repo"
    shutil.copytree(SAMPLE, target)
    return target


@pytest.fixture
def dup_git(tmp_path: Path) -> Path:
    target = tmp_path / "dup_repo"
    shutil.copytree(DUP, target)
    _init_git(target)
    return target


# --- brief ----------------------------------------------------------------------------

def test_brief_synthesises_impact_references_and_reuse(sample: Path):
    config = load_config(sample)
    report = brief(config, ensure_index(config), "validate_email", intent="check that an email address is valid", names=["EmailChecker"])
    kinds = [f.kind for f in report.findings]
    assert kinds[0] == "definition"
    assert "direct-reference" in kinds and "consequence" in kinds and "test" in kinds and "config" in kinds and "boundary" in kinds
    summary = next(f for f in report.findings if f.kind == "reference-summary")
    assert summary.summary.startswith("2 file(s) with confirmed uses")
    assert report.meta["reuse_decision"] == "extend" and report.meta["tests"] == ["tests/test_validators.py"]
    assert report.findings[-1].kind == "next"
    assert len(report.findings) <= 40, "a brief must stay compact"


def test_brief_unknown_target_still_reports_reuse(sample: Path):
    config = load_config(sample)
    report = brief(config, ensure_index(config), "ghost", intent="slugify a title")
    assert report.findings[0].kind == "target" and report.findings[0].confidence == UNKNOWN
    assert report.meta["reuse_decision"] in ("extend", "refactor-or-create")
    assert any(f.kind == "decision" for f in report.findings)


# --- verify: detection ------------------------------------------------------------------

def test_detect_steps_from_manifests(tmp_path: Path):
    _write(tmp_path / "pyproject.toml", "[tool.pytest.ini_options]\ntestpaths=['tests']\n[tool.ruff]\nline-length=100\n")
    _write(tmp_path / "tests" / "test_a.py", "def test_a():\n    assert True\n")
    _write(tmp_path / "package.json", json.dumps({"scripts": {"test": "echo 'Error: no test specified' && exit 1", "lint": "eslint ."}}))
    _write(tmp_path / "Cargo.toml", "[package]\nname='x'\n")
    steps = {s.name: s for s in detect_steps(tmp_path, ensure_index(load_config(tmp_path)))}
    assert "pytest" in steps and steps["pytest"].argv[1:3] == ["-m", "pytest"] and steps["pytest"].available
    assert "ruff" in steps and steps["ruff"].reason == "ruff configured"
    assert "npm test" not in steps, "npm's placeholder test script is not a verification step"
    assert "npm lint" in steps and steps["npm lint"].argv[1:3] == ["run", "lint"]
    assert "cargo test" in steps
    assert all(isinstance(s.available, bool) for s in steps.values())


def test_detect_steps_none_when_nothing_configured(tmp_path: Path):
    _write(tmp_path / "a.py", "X = 1\n")
    assert detect_steps(tmp_path, ensure_index(load_config(tmp_path))) == []


# --- verify: report ---------------------------------------------------------------------

def test_verify_without_run_lists_steps_and_is_not_verified(dup_git: Path):
    _write(dup_git / "pyproject.toml", "[project]\nname='dup'\nversion='0.0.1'\n[tool.pytest.ini_options]\ntestpaths=['tests']\n")
    api = dup_git / "app" / "api.py"
    _write(api, api.read_text(encoding="utf-8") + "\n\ndef ping():\n    return 'pong'  # TODO: real health check\n")
    config = load_config(dup_git)
    report = verify(config, ensure_index(config), scope=("app/api.py",))
    kinds = {f.kind for f in report.findings}
    assert {"change-surface", "verification-step", "unresolved-markers", "verdict"} <= kinds
    assert report.meta["verdict"] == "not verified"
    assert any("not executed" in o for o in report.meta["outstanding"]) and any("marker" in o for o in report.meta["outstanding"])
    assert report.meta["steps"] == ["pytest"]
    markers = next(f for f in report.findings if f.kind == "unresolved-markers")
    assert markers.confidence == CONFIRMED and markers.evidence[0].startswith("app/api.py: return 'pong'")


def test_verify_run_reports_real_results_and_coverage(dup_git: Path):
    _write(dup_git / "pyproject.toml", "[project]\nname='dup'\nversion='0.0.1'\n[tool.pytest.ini_options]\ntestpaths=['tests']\npythonpath=['.']\n")
    _git(dup_git, "add", "-A")
    _git(dup_git, "commit", "-q", "-m", "pytest config")
    validators = dup_git / "app" / "validators.py"
    _write(validators, validators.read_text(encoding="utf-8").replace("< 100", "< 120"))
    config = load_config(dup_git)
    report = verify(config, ensure_index(config), scope=("app/validators.py",), run=True, timeout=120)
    assert report.meta["step_results"] == {"pytest": "pass"}, report.to_markdown()
    assert report.meta["tests_to_run"] == ["tests/test_validators.py"] and report.meta["uncovered"] == []
    assert report.meta["verdict"] == "verified", report.meta["outstanding"]
    assert next(f for f in report.findings if f.kind == "verdict").confidence == CONFIRMED

    # now break the test and verify again: the failure must be reported, not hidden
    _write(validators, validators.read_text(encoding="utf-8").replace("return bool(EMAIL_RE.match(value))", "return False"))
    report2 = verify(config, ensure_index(config), scope=("app/validators.py",), run=True, timeout=120)
    assert report2.meta["step_results"] == {"pytest": "fail"} and report2.meta["verdict"] == "not verified"
    failed = next(f for f in report2.findings if f.kind == "verification-step")
    assert failed.severity == "error" and any("test_validate_email" in line or "FAILED" in line for line in failed.evidence)
    assert report2.has_errors


def test_verify_flags_untested_changed_file(dup_git: Path):
    _write(dup_git / "app" / "legacy" / "models.py", "class User:\n    def __init__(self, email, legacy=True):\n        self.email = email\n        self.legacy = legacy\n        self.flag = 1\n")
    config = load_config(dup_git)
    report = verify(config, ensure_index(config))
    assert report.meta["uncovered"] == ["app/legacy/models.py"]
    assert any(f.kind == "untested-change" and f.confidence == INFERRED for f in report.findings)


# --- adapter structure: specialists and protocol -------------------------------------------

SPECIALISTS = ("lord-investigator", "lord-reuse-auditor", "lord-impact-analyst", "lord-skeptical-reviewer", "lord-verification-reviewer")
WRITE_TOOLS = ("replace_file_content", "write_to_file", "multi_replace", "create_file", "edit_file")


def _frontmatter(path: Path) -> str:
    match = re.match(r"^---\n(.*?)\n---\n", path.read_text(encoding="utf-8"), re.S)
    assert match, path
    return match.group(1)


@pytest.mark.parametrize("name", SPECIALISTS)
def test_specialists_are_read_only_and_structured(name: str):
    path = ROOT / ".agents" / "agents" / f"{name}.md"
    assert path.is_file()
    fm = _frontmatter(path)
    assert f"name: {name}" in fm and "subagent: true" in fm and "mainAgent: false" in fm
    assert not any(tool in fm for tool in WRITE_TOOLS), f"{name} must not have write tools"
    body = path.read_text(encoding="utf-8")
    assert "## Output format" in body and "python -m lord" in body
    assert "Never edit" in body or "never edits" in body.lower()


def test_exactly_the_planned_specialists_exist():
    agents = sorted(p.stem for p in (ROOT / ".agents" / "agents").glob("*.md"))
    assert agents == sorted(SPECIALISTS), "every agent must have a genuine responsibility; no decorative agents"


def test_critical_review_skill_binds_protocol_to_specialists_and_tools():
    body = (ROOT / ".agents" / "skills" / "lord-critical-review" / "SKILL.md").read_text(encoding="utf-8")
    for step in ("Understand intent", "Validate user assumptions", "Search existing solutions", "Trace root cause", "Smallest valid change", "Verify", "Report"):
        assert step in body, step
    for specialist in SPECIALISTS:
        assert specialist in body, specialist
    assert "EVIDENCE" in body and "CONSEQUENCE" in body and "RECOMMENDATION" in body and "USER DECISION" in body
    assert "python -m lord brief" in body and "verify --run" in body


def test_cli_brief_and_verify_json(sample: Path):
    def run(*args: str) -> dict:
        completed = subprocess.run([sys.executable, "-m", "lord", "--root", str(sample), *args, "--json"], cwd=ROOT, capture_output=True, text=True)
        assert completed.returncode == 0, completed.stderr
        return json.loads(completed.stdout)

    assert run("brief", "UserService.create", "--intent", "create a user")["meta"]["reuse_decision"] in ("reuse", "extend", "refactor-or-create", "create")
    _init_git(sample)
    verified = run("verify")
    assert verified["meta"]["verdict"] == "not verified" and "pytest" in verified["meta"]["steps"]
