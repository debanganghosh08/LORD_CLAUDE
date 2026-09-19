"""Phase 1 foundation tests: boundary, config, report model, doctor, adapter
structure, ignore policy and provider independence."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from lord.config import DEFAULT_EXCLUDE_DIRS, load_config
from lord.doctor import run_doctor
from lord.paths import BoundaryError, find_workspace_root, git_toplevel, is_within, safe_join, to_rel_posix
from lord.report import CONFIRMED, ERROR, OK, UNKNOWN, Finding, Report

ROOT = Path(__file__).resolve().parents[1]

RULE_TRIGGERS = {"always_on", "model_decision", "glob", "manual"}
RULE_CHAR_LIMIT = 12_000


def _frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert match, f"{path} has no YAML frontmatter"
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line and not line.startswith((" ", "-")):
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip()
    return fields


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


# --- workspace boundary -------------------------------------------------------

def test_workspace_root_resolves_from_subdirectory():
    assert find_workspace_root(ROOT / "lord") == ROOT


def test_git_root_equals_workspace_root():
    top = git_toplevel(ROOT)
    if top is None:
        pytest.skip("not a git checkout")
    assert top == ROOT, "Git root must be the LORD workspace, never a parent directory"


def test_safe_join_rejects_paths_escaping_the_root():
    with pytest.raises(BoundaryError):
        safe_join(ROOT, "../outside.txt")
    with pytest.raises(BoundaryError):
        safe_join(ROOT, Path("..") / ".." / "etc")


def test_safe_join_and_rel_posix_accept_inside_paths():
    inside = safe_join(ROOT, "lord/cli.py")
    assert is_within(inside, ROOT)
    assert to_rel_posix(inside, ROOT) == "lord/cli.py"
    assert not is_within(ROOT.parent, ROOT)


# --- configuration ------------------------------------------------------------

def test_default_exclusions_cover_vendor_build_and_runtime_dirs():
    for name in ("node_modules", ".venv", "dist", "build", "__pycache__", ".lord", ".claude", ".gemini"):
        assert name in DEFAULT_EXCLUDE_DIRS


def test_lord_toml_overrides_and_extends(tmp_path: Path):
    (tmp_path / "lord.toml").write_text(
        '[lord]\nexclude_dirs = ["generated"]\nextra_exclude_globs = ["*.gen.ts"]\n', encoding="utf-8"
    )
    cfg = load_config(tmp_path)
    assert cfg.exclude_dirs == ("generated",)
    assert "*.gen.ts" in cfg.exclude_globs and "*.min.js" in cfg.exclude_globs
    assert cfg.source_file == tmp_path / "lord.toml"


def test_missing_config_uses_defaults(tmp_path: Path):
    cfg = load_config(tmp_path)
    assert cfg.source_file is None and cfg.exclude_dirs == DEFAULT_EXCLUDE_DIRS


# --- report model -------------------------------------------------------------

def test_finding_requires_valid_confidence_and_severity():
    with pytest.raises(ValueError):
        Finding(kind="x", summary="y", confidence="probably")
    with pytest.raises(ValueError):
        Finding(kind="x", summary="y", severity="fatal")


def test_report_json_and_markdown_carry_confidence():
    report = Report(title="t", meta={"root": "r"})
    report.add(Finding(kind="a", summary="unsupported language", confidence=UNKNOWN, evidence=["x.rs"]))
    report.add(Finding(kind="b", summary="boom", severity=ERROR))
    data = json.loads(report.to_json())
    assert data["worst_severity"] == ERROR and data["findings"][0]["confidence"] == UNKNOWN
    md = report.to_markdown()
    assert "confidence: unknown" in md and "[ERROR] b" in md
    assert report.has_errors


# --- doctor -------------------------------------------------------------------

def test_doctor_reports_clean_environment_for_lord_itself():
    report = run_doctor(ROOT)
    kinds = {f.kind: f for f in report.findings}
    assert {"python", "tool-git", "git-root", "config", "antigravity-adapter", "state-dir", "provider-independence"} <= kinds.keys()
    assert not report.has_errors, report.to_markdown()
    assert kinds["antigravity-adapter"].severity == OK
    assert kinds["provider-independence"].confidence == CONFIRMED


def test_cli_doctor_json_is_machine_readable():
    completed = subprocess.run(
        [sys.executable, "-m", "lord", "--root", str(ROOT), "doctor", "--json"], cwd=ROOT, capture_output=True, text=True
    )
    assert completed.returncode == 0, completed.stderr
    data = json.loads(completed.stdout)
    assert data["title"] == "LORD doctor" and data["findings"]


# --- adapter structure --------------------------------------------------------

REQUIRED_PATHS = (
    ".agents/rules/lord-operating-contract.md",
    ".agents/skills/lord-pre-edit-audit/SKILL.md",
    ".agents/agents/lord-investigator.md",
    "AGENTS.md",
    "CLAUDE.md",
    "README.md",
    "CONTRIBUTING.md",
    "docs/ARCHITECTURE.md",
    "docs/ROADMAP.md",
    "docs/SECURITY.md",
    "docs/decisions",
    "docs/reports",
    "lord/cli.py",
    "pyproject.toml",
    ".gitignore",
)


@pytest.mark.parametrize("relative", REQUIRED_PATHS)
def test_required_structure_exists(relative: str):
    assert (ROOT / relative).exists(), relative


def test_rules_have_valid_frontmatter_and_size():
    rules = list((ROOT / ".agents" / "rules").glob("*.md"))
    assert rules
    for rule in rules:
        fm = _frontmatter(rule)
        assert fm.get("trigger") in RULE_TRIGGERS, rule
        assert fm.get("description"), rule
        assert len(rule.read_text(encoding="utf-8")) <= RULE_CHAR_LIMIT, rule


def test_skills_have_skill_md_with_description():
    skills = [p for p in (ROOT / ".agents" / "skills").iterdir() if p.is_dir()]
    assert skills
    for skill in skills:
        fm = _frontmatter(skill / "SKILL.md")
        assert fm.get("description"), skill
        assert fm.get("name", skill.name) == skill.name


def test_agents_have_name_description_and_are_subagents():
    agents = list((ROOT / ".agents" / "agents").glob("*.md"))
    assert agents
    for agent in agents:
        fm = _frontmatter(agent)
        assert fm.get("name") == agent.stem
        assert fm.get("description")
        assert fm.get("subagent") == "true"


def test_contract_is_referenced_not_duplicated():
    contract = (ROOT / ".agents/rules/lord-operating-contract.md").read_text(encoding="utf-8")
    agents_md = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "lord-operating-contract.md" in agents_md
    assert len(agents_md) < len(contract) / 2, "AGENTS.md must be a pointer, not a copy"
    assert "@AGENTS.md" in (ROOT / "CLAUDE.md").read_text(encoding="utf-8")


# --- ignore policy ------------------------------------------------------------

IGNORED = (".env", ".env.local", "secrets/token.txt", "server.pem", "id_rsa", ".lord/index.json",
           ".claude/settings.local.json", ".gemini/state.json", "lord/__pycache__/x.pyc", "node_modules/a/b.js", "debug.log")
TRACKED = (".agents/rules/lord-operating-contract.md", ".agents/skills/x/SKILL.md", ".agents/agents/x.md",
           ".agents/hooks.json", ".agents/plugins/lord/plugin.json", "lord/cli.py", "tests/test_foundation.py",
           "docs/ARCHITECTURE.md", "lord.toml", ".env.example")


@pytest.mark.parametrize("path", IGNORED)
def test_gitignore_blocks_secrets_and_runtime_state(path: str):
    assert _git("check-ignore", "-q", path).returncode == 0, f"{path} must be ignored"


@pytest.mark.parametrize("path", TRACKED)
def test_gitignore_keeps_lord_source(path: str):
    assert _git("check-ignore", "-q", path).returncode == 1, f"{path} must NOT be ignored"


def test_nothing_outside_workspace_is_tracked():
    files = _git("ls-files").stdout.split()
    assert files and not any(f.startswith("..") or ":" in f for f in files)


# --- provider independence ----------------------------------------------------

FORBIDDEN_IMPORTS = ("anthropic", "openai", "google.generativeai", "google.genai", "requests", "httpx", "urllib.request", "aiohttp")


def test_core_has_no_runtime_dependencies_or_provider_imports():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["dependencies"] == []
    pattern = re.compile(r"^\s*(?:import|from)\s+(" + "|".join(re.escape(m) for m in FORBIDDEN_IMPORTS) + r")\b", re.M)
    for source in (ROOT / "lord").rglob("*.py"):
        assert not pattern.search(source.read_text(encoding="utf-8")), f"{source} imports a provider/network module"


def test_core_does_not_reference_api_keys():
    pattern = re.compile(r"(ANTHROPIC|OPENAI|GEMINI|GOOGLE)_API_KEY")
    for source in (ROOT / "lord").rglob("*.py"):
        assert not pattern.search(source.read_text(encoding="utf-8")), source
