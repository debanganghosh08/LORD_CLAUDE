"""Phase 3 tests: reuse decision ladder, duplicate detection, change-surface
measurement and the bloat signal. Change-surface tests build a real Git
repository in a temp directory. Files are written with newline="\\n" so
Windows text-mode CRLF translation cannot turn every line into a whitespace
change."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from lord.change_surface import git_changes, measure
from lord.config import load_config
from lord.extractors.js_ts import extract_js_ts
from lord.extractors.python_ast import extract_python
from lord.index import ensure_index
from lord.report import CONFIRMED, INFERRED
from lord.reuse import duplicates_report, jaccard, reuse_report, thin_wrappers

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "dup_repo"


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    return completed.stdout


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    target = tmp_path / "dup_repo"
    shutil.copytree(FIXTURE, target)
    return target


@pytest.fixture
def git_repo(repo: Path) -> Path:
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "core.autocrlf", "false")
    _write(repo / ".gitignore", ".lord/\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    return repo


@pytest.fixture
def index(repo: Path):
    return ensure_index(load_config(repo))


# --- extractor upgrades used by phase 3 --------------------------------------------

def test_python_constants_carry_their_value():
    ex = extract_python(FIXTURE, "app/validators.py", _read(FIXTURE / "app/validators.py"))
    values = {s.name: s.signature for s in ex.symbols if s.kind == "constant"}
    assert values["MAX_EMAIL_LENGTH"] == "254" and values["EMAIL_RE"].startswith("re.compile(")


def test_js_symbols_get_end_lines(tmp_path: Path):
    src = "function a() {\n  return 1;\n}\nclass K {\n  m() {\n    return 2;\n  }\n}\n"
    ex = extract_js_ts(tmp_path, "x.js", src, "javascript")
    ends = {s.qualname: s.end_line for s in ex.symbols}
    assert ends == {"a": 3, "K": 8, "K.m": 7}


# --- reuse decision ladder ------------------------------------------------------------

def test_reuse_detects_existing_symbol_by_name(index, repo: Path):
    report = reuse_report(index, repo, "validate an email address", names=["validate_email"])
    assert report.meta["decision"] == "reuse"
    exists = next(f for f in report.findings if f.kind == "exists")
    assert "app/validators.py:8" in exists.summary and exists.confidence == CONFIRMED
    assert "import and reuse validate_email" in exists.recommendation


def test_reuse_recommends_extend_for_strong_behavioural_match(index, repo: Path):
    report = reuse_report(index, repo, "check whether an e-mail address is valid", names=["EmailChecker"])
    assert report.meta["decision"] == "extend"
    strong = [f for f in report.findings if f.kind == "candidate-reuse-or-extend"]
    # validate_email and its legacy near-duplicate check_email are both strong; either may lead
    assert strong and any("validate_email" in f.summary for f in strong[:2])


def test_reuse_allows_create_when_nothing_matches(index, repo: Path):
    report = reuse_report(index, repo, "compress video frames with wavelet transform", names=["compress_frames"])
    assert report.meta["decision"] == "create"
    decision = next(f for f in report.findings if f.kind == "decision")
    assert decision.confidence == INFERRED and "not proof of absence" in decision.consequence


# --- duplicates -----------------------------------------------------------------------

def test_duplicates_report_finds_each_kind(index, repo: Path):
    report = duplicates_report(index, repo)
    kinds = {f.kind: [g for g in report.findings if g.kind == f.kind] for f in report.findings}

    constants = {f.summary for f in kinds["duplicate-constant"]}
    assert any("MAX_EMAIL_LENGTH" in s and "DIFFERENT values" in s for s in constants)
    assert any("EMAIL_PATTERN, EMAIL_RE" in f.summary for f in kinds["duplicate-value"])
    assert any("validate_name" in f.summary for f in kinds["duplicate-function"])
    assert any("class User" in f.summary and "2 files" in f.summary for f in kinds["duplicate-class"])

    logic = kinds["duplicate-logic"]
    assert len(logic) == 1
    assert {"app/validators.py::validate_email", "app/legacy/checks.py::check_email"} == {logic[0].data["a"], logic[0].data["b"]}
    assert logic[0].data["normalized"] >= 0.8 and "renamed identifiers" in logic[0].summary

    wrappers = kinds["thin-wrapper"]
    assert [f.summary for f in wrappers] == ["is_valid_email only forwards to validate_email"] and wrappers[0].confidence == CONFIRMED
    assert not any("test_validate_email" in f.summary for f in report.findings), "tests are excluded by default"


def test_thin_wrapper_requires_identical_argument_forwarding(tmp_path: Path):
    _write(tmp_path / "w.py", "def a(x):\n    return b(x)\n\ndef c(x):\n    return b(x, 1)\n\ndef d(x, y):\n    return b(y, x)\n\ndef e(x):\n    return str(x)\n")
    index = ensure_index(load_config(tmp_path))
    assert [(s.name, callee) for s, callee in thin_wrappers(index, tmp_path)] == [("a", "b")]


def test_jaccard_edge_cases():
    assert jaccard(set(), {1}) == 0.0 and jaccard({1, 2}, {1, 2}) == 1.0 and jaccard({1, 2}, {2, 3}) == pytest.approx(1 / 3)


# --- change surface -------------------------------------------------------------------

def test_git_changes_sees_tracked_and_untracked(git_repo: Path):
    _write(git_repo / "app" / "validators.py", _read(git_repo / "app/validators.py") + "X = 1\n")
    _write(git_repo / "app" / "brand_new.py", "def fresh():\n    return 1\n")
    (git_repo / "docs" / "notes.md").unlink()
    changes = {c.path: c for c in git_changes(git_repo)}
    assert changes["app/validators.py"].status == "M" and changes["app/validators.py"].added == 1 and changes["app/validators.py"].whitespace_only == 0
    assert changes["app/brand_new.py"].status == "A" and changes["app/brand_new.py"].added == 2 and changes["app/brand_new.py"].kind == "source"
    assert changes["docs/notes.md"].status == "D"


def test_measure_reports_low_bloat_for_a_small_focused_change(git_repo: Path):
    path = git_repo / "app" / "validators.py"
    _write(path, _read(path).replace("< 100", "< 120"))
    report = measure(load_config(git_repo), ensure_index(load_config(git_repo)))
    assert report.meta["bloat_level"] == "low" and report.meta["files"] == 1 and report.meta["new_symbols"] == []
    assert report.findings[0].summary.startswith("files: 1 (+0 new, -0 deleted), +1/-1 lines")


def test_measure_flags_duplicate_new_function_and_thin_new_file(git_repo: Path):
    original = _read(git_repo / "app" / "validators.py")
    body = original.split("def validate_email")[1].split("def validate_name")[0]
    _write(git_repo / "app" / "email_utils.py", "from app.validators import EMAIL_RE, MAX_EMAIL_LENGTH\n\n\ndef verify_email" + body)
    config = load_config(git_repo)
    report = measure(config, ensure_index(config), scope=("email",))
    kinds = {f.kind for f in report.findings}
    assert {"new-file", "resembles-existing", "bloat-signal"} <= kinds
    resemble = next(f for f in report.findings if f.kind == "resembles-existing")
    assert "verify_email" in resemble.summary and "validate_email" in resemble.summary
    assert report.meta["bloat_level"] == "high"
    assert "app/email_utils.py::verify_email" in report.meta["new_symbols"]


def test_measure_flags_name_collision_churn_manifest_and_unrelated(git_repo: Path):
    # name collision: a second validate_name in a new module
    _write(git_repo / "app" / "extra.py", "def validate_name(value):\n    return len(value) > 1\n")
    # formatting churn: re-indent legacy/checks.py without changing tokens
    checks = git_repo / "app" / "legacy" / "checks.py"
    _write(checks, "\n".join(line.replace("    ", "  ") if line.startswith("    ") else line for line in _read(checks).splitlines()) + "\n")
    # manifest change
    _write(git_repo / "pyproject.toml", _read(git_repo / "pyproject.toml").replace("dependencies = []", 'dependencies = ["requests"]'))
    # unrelated docs change
    _write(git_repo / "docs" / "notes.md", "# Notes\n\nchanged\n")

    config = load_config(git_repo)
    report = measure(config, ensure_index(config), scope=("app/extra.py",))
    kinds = {f.kind: f for f in report.findings}
    assert "validate_name" in kinds["name-collision"].summary
    assert kinds["formatting-churn"].confidence == CONFIRMED and "app/legacy/checks.py" in kinds["formatting-churn"].evidence
    assert kinds["dependency-change"].summary.startswith("pyproject.toml")
    unrelated = kinds["potentially-unrelated"].evidence
    assert "docs/notes.md" in unrelated and "app/legacy/checks.py" in unrelated and "app/extra.py" not in unrelated
    assert report.meta["bloat_level"] == "elevated"
    assert any("manifest" in r for r in report.meta["bloat_reasons"])


def test_measure_without_scope_uses_import_connectivity(git_repo: Path):
    api = git_repo / "app" / "api.py"
    _write(api, _read(api) + "\n\ndef ping():\n    return 'pong'\n")
    validators = git_repo / "app" / "validators.py"
    _write(validators, _read(validators) + "\nPING = 1\n")
    legacy = git_repo / "app" / "legacy" / "models.py"
    _write(legacy, _read(legacy) + "\nLEGACY = 1\n")
    config = load_config(git_repo)
    report = measure(config, ensure_index(config))
    unrelated = next(f for f in report.findings if f.kind == "potentially-unrelated")
    assert unrelated.evidence == ["app/legacy/models.py"]  # api.py imports validators.py; legacy/models.py is disconnected


def test_measure_against_base_ref_and_staged(git_repo: Path):
    _write(git_repo / "app" / "new_module.py", "VALUE = 1\n")
    _git(git_repo, "add", "app/new_module.py")
    config = load_config(git_repo)
    staged = measure(config, ensure_index(config), staged=True)
    assert staged.meta["files"] == 1 and staged.meta["new_files"] == 1 and "app/new_module.py::VALUE" in staged.meta["new_symbols"]
    _git(git_repo, "commit", "-q", "-m", "add module")
    based = measure(config, ensure_index(config), base="HEAD~1")
    assert based.meta["files"] == 1 and based.meta["lines_added"] == 1 and based.meta["base"] == "HEAD~1"
    assert measure(config, ensure_index(config)).meta["files"] == 0


def test_measure_outside_git_is_explicit(tmp_path: Path):
    _write(tmp_path / "a.py", "X = 1\n")
    config = load_config(tmp_path)
    report = measure(config, ensure_index(config))
    assert report.findings[0].kind == "git" and "unavailable" in report.findings[0].summary


# --- cli -------------------------------------------------------------------------------

def test_cli_reuse_duplicates_diff_json(git_repo: Path):
    def run(*args: str) -> dict:
        completed = subprocess.run([sys.executable, "-m", "lord", "--root", str(git_repo), *args, "--json"], cwd=ROOT, capture_output=True, text=True)
        assert completed.returncode == 0, completed.stderr
        return json.loads(completed.stdout)

    assert run("reuse", "validate email", "--name", "validate_email")["meta"]["decision"] == "reuse"
    assert run("duplicates")["meta"]["counts"]["thin-wrapper"] == 1
    assert run("diff", "--scope", "app")["meta"]["bloat_level"] == "low"
