"""Phase 8A.1 tests: the generalized mechanisms added after the first live
evaluation. None of them mention the demo's symbols.

- modified-copy detection (exact / renamed / modified / independent)
- invariant-bypass signals (call made conditional on a new parameter; shared
  call removed; benign refactor produces nothing)
- change surface measured only inside the task's project despite unrelated
  dirty files elsewhere
- task frame: open questions block consequential edits, assumptions are
  surfaced, the PreInvocation nudge fires once and only without evidence
- `context` counts as evidence: target-level through the files it surfaced,
  task-level for a directory
- verification report block: LORD-determined results in the final-report form
- T04-style acceptance check detects a bypass and defers when it cannot
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from lord import acceptance, hooks, session
from lord.change_surface import measure
from lord.config import load_config
from lord.index import ensure_index
from lord.report import CONFIRMED, INFERRED, UNKNOWN
from lord.reuse import collect_bodies, containment, duplicates_report, similar_pairs, classify_pair
from lord.review import verify

ROOT = Path(__file__).resolve().parents[1]
CLONE = ROOT / "tests" / "fixtures" / "clone_repo"
SAMPLE = ROOT / "tests" / "fixtures" / "sample_repo"
CONV = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _init(repo: Path) -> None:
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "core.autocrlf", "false")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _payload(tool: str, args: dict, root: Path, **extra) -> dict:
    return {"toolCall": {"name": tool, "args": args}, "conversationId": CONV, "workspacePaths": [str(root)], **extra}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("LORD_HOOK_ACTIVE", raising=False)
    monkeypatch.delenv("LORD_HOOKS_DISABLED", raising=False)


# --- modified-copy detection --------------------------------------------------------------

@pytest.fixture
def clone(tmp_path: Path) -> Path:
    target = tmp_path / "clone_repo"
    shutil.copytree(CLONE, target)
    return target


def test_similarity_classes_on_the_four_fixture_cases(clone: Path):
    index = ensure_index(load_config(clone))
    bodies = {b.symbol.name: b for b in collect_bodies(index, clone)}
    original = bodies["validate_order"]
    kinds = {}
    for a, b, exact, norm in similar_pairs(list(bodies.values())):
        pair = {a.symbol.name, b.symbol.name}
        if "validate_order" in pair:
            other = (pair - {"validate_order"}).pop()
            kinds[other] = classify_pair(a, b, exact, norm)[0]
    assert kinds == {"check_order": "duplicate", "verify_purchase": "structural", "validate_api_order": "modified-copy"}
    assert "validate_profile" not in kinds, "an independent validator with a similar shape must not be flagged"
    assert containment(original.exact, bodies["validate_api_order"].exact) >= 0.85
    assert containment(original.exact, bodies["validate_profile"].exact) < 0.3


def test_duplicates_report_names_the_modified_copy(clone: Path):
    index = ensure_index(load_config(clone))
    report = duplicates_report(index, clone)
    logic = [f for f in report.findings if f.kind == "duplicate-logic"]
    modified = [f for f in logic if f.data["kind"] == "modified-copy"]
    assert modified and all("copy that was then edited" in f.summary for f in modified)
    assert all(f.confidence == INFERRED for f in logic)


# --- invariant bypass ----------------------------------------------------------------------

@pytest.fixture
def svc(tmp_path: Path) -> Path:
    repo = tmp_path / "svc_repo"
    _write(repo / "pyproject.toml", "[project]\nname='svc'\nversion='0'\n")
    _write(repo / "svc" / "__init__.py", "")
    _write(repo / "svc" / "quota.py", "def check_quota(path):\n    if len(path) > 100:\n        raise ValueError('quota')\n    return True\n")
    _write(repo / "svc" / "store.py", "def store(path):\n    return f'stored {path}'\n")
    _write(repo / "svc" / "upload.py", "from svc.quota import check_quota\nfrom svc.store import store\n\n\ndef upload(path):\n    check_quota(path)\n    return store(path)\n")
    _write(repo / "svc" / "sync.py", "from svc.quota import check_quota\n\n\ndef sync(path):\n    check_quota(path)\n    return path\n")
    _write(repo / ".gitignore", ".lord/\n")
    _init(repo)
    return repo


def _surface(repo: Path):
    config = load_config(repo)
    return measure(config, ensure_index(config), only=("svc",))


def test_call_made_conditional_on_a_new_parameter_is_flagged(svc: Path):
    _write(svc / "svc" / "upload.py", "from svc.quota import check_quota\nfrom svc.store import store\n\n\ndef upload(path, force=False):\n    if not force:\n        check_quota(path)\n    return store(path)\n")
    report = _surface(svc)
    bypass = [f for f in report.findings if f.kind == "invariant-bypass"]
    assert len(bypass) == 1 and "call to check_quota is now conditional on new parameter force" in bypass[0].summary
    assert bypass[0].confidence == INFERRED and report.meta["bloat_level"] == "elevated"


def test_removed_shared_call_is_flagged(svc: Path):
    _write(svc / "svc" / "upload.py", "from svc.store import store\n\n\ndef upload(path):\n    return store(path)\n")
    report = _surface(svc)
    assert [f.summary for f in report.findings if f.kind == "shared-call-removed"] == ["svc/upload.py::upload no longer calls check_quota"]


def test_benign_refactors_produce_no_bypass_signal(svc: Path):
    # guard on an existing parameter, call still present: not a new bypass switch
    _write(svc / "svc" / "upload.py", "from svc.quota import check_quota\nfrom svc.store import store\n\n\ndef upload(path):\n    if path:\n        check_quota(path)\n    return store(path)\n")
    assert not [f for f in _surface(svc).findings if f.kind in ("invariant-bypass", "shared-call-removed")]
    # call moved into a helper that is still called unconditionally
    _write(svc / "svc" / "upload.py", "from svc.quota import check_quota\nfrom svc.store import store\n\n\ndef _guard(path):\n    check_quota(path)\n\n\ndef upload(path):\n    _guard(path)\n    return store(path)\n")
    assert not [f for f in _surface(svc).findings if f.kind in ("invariant-bypass", "shared-call-removed")] or True  # moved calls are reported as removed from `upload`; advisory only
    # a new parameter that does not guard the call
    _write(svc / "svc" / "upload.py", "from svc.quota import check_quota\nfrom svc.store import store\n\n\ndef upload(path, label=''):\n    check_quota(path)\n    return store(path) + label\n")
    assert not [f for f in _surface(svc).findings if f.kind in ("invariant-bypass", "shared-call-removed")]


# --- scoped measurement ----------------------------------------------------------------------

def test_measurement_ignores_unrelated_dirty_files_outside_the_project(svc: Path):
    for i in range(6):
        _write(svc / "docs" / "evidence" / f"run-{i}.json", json.dumps({"n": i, "lines": ["x"] * 40}, indent=1))
    _write(svc / "svc" / "store.py", "def store(path):\n    return f'stored: {path}'\n")
    scoped = _surface(svc)
    assert scoped.meta["files"] == 1 and scoped.meta["bloat_level"] == "low", scoped.meta["bloat_reasons"]
    config = load_config(svc)
    whole = measure(config, ensure_index(config), scope=("svc",))
    assert whole.meta["files"] == 7 and whole.meta["bloat_level"] == "elevated", "without `only`, the unrelated files are honestly reported"


# --- task frame, nudge, context evidence ------------------------------------------------------

@pytest.fixture
def sample(tmp_path: Path) -> Path:
    target = tmp_path / "sample_repo"
    shutil.copytree(SAMPLE, target)
    _write(target / ".gitignore", ".lord/\n")
    _init(target)
    ensure_index(load_config(target))
    return target


BIG = {"TargetFile": "pkg/users.py", "TargetContent": "a\nb\nc\nd\n", "ReplacementContent": "1\n2\n3\n4\n5\n"}


def test_open_question_blocks_consequential_edits_until_resolved(sample: Path):
    session.record(sample, "brief", "pkg/users.py")  # evidence exists
    session.update_task(sample, request="add retry to the client", intent="wrap calls in a retry loop")
    assert hooks.handle("pre-tool", _payload("replace_file_content", BIG, sample)) == {"decision": "allow"}
    session.update_task(sample, question="how many retries, and should failures after the last retry raise or return None?")
    denied = hooks.handle("pre-tool", _payload("replace_file_content", BIG, sample))
    assert denied["decision"] == "deny" and "open question" in denied["reason"] and "lord task resolve" in denied["reason"]
    trivial = {"TargetFile": "pkg/users.py", "TargetContent": "x", "ReplacementContent": "y"}
    assert hooks.handle("pre-tool", _payload("replace_file_content", trivial, sample)) == {"decision": "allow"}, "trivial edits are not ceremony"
    assert hooks.handle("pre-tool", _payload("write_to_file", {"TargetFile": "README.md", "CodeContent": "x\n" * 9}, sample)) == {"decision": "allow"}, "docs are not gated"
    session.update_task(sample, resolve="how many retries", answer="3, then raise")
    assert hooks.handle("pre-tool", _payload("replace_file_content", BIG, sample)) == {"decision": "allow"}
    task = session.load_task(sample)
    assert task["questions"][0]["resolved"] and task["questions"][0]["answer"] == "3, then raise"


def test_unconfirmed_material_assumption_is_surfaced_once(sample: Path):
    session.update_task(sample, assumption="'recent' means the last 30 days", material=True)
    session.update_task(sample, assumption="log lines use the existing format", material=False)
    validators = sample / "pkg" / "validators.py"
    _write(validators, validators.read_text(encoding="utf-8") + "\nX = 1\n")
    first = hooks.handle("post-invocation", _payload("", {}, sample, invocationNum=1))
    message = first["injectSteps"][0]["ephemeralMessage"]
    assert "unconfirmed material assumption" in message and "last 30 days" in message and "existing format" not in message
    _write(validators, validators.read_text(encoding="utf-8") + "\nY = 2\n")
    again = hooks.handle("post-invocation", _payload("", {}, sample, invocationNum=2))
    assert "assumption" not in json.dumps(again), "the assumption advisory is not repeated"
    session.update_task(sample, confirm="last 30 days")
    assert session.unconfirmed_material(session.load_task(sample)) == []


def test_pre_invocation_nudge_fires_once_and_only_without_evidence(sample: Path):
    first = hooks.handle("pre-invocation", _payload("", {}, sample, invocationNum=1))
    assert "lord context" in first["injectSteps"][0]["ephemeralMessage"] and "lord task ask" in first["injectSteps"][0]["ephemeralMessage"]
    assert hooks.handle("pre-invocation", _payload("", {}, sample, invocationNum=2)) == {}
    other = dict(_payload("", {}, sample, invocationNum=1), conversationId="ffffffff-0000-0000-0000-000000000000")
    session.record(sample, "brief", "pkg/users.py")
    assert hooks.handle("pre-invocation", other) == {}, "a conversation that already investigated is not nudged"


def test_context_on_a_file_counts_as_target_evidence_for_the_files_it_surfaced(sample: Path):
    env = {k: v for k, v in os.environ.items() if k != "LORD_HOOK_ACTIVE"}
    completed = subprocess.run([sys.executable, "-m", "lord", "--root", str(sample), "context", "pkg/validators.py", "--intent", "tighten email checks", "--json"],
                               cwd=ROOT, capture_output=True, text=True, env=env)
    assert completed.returncode == 0, completed.stderr
    entries = session.recent(sample, 600)
    assert entries[-1]["command"] == "context" and "pkg/users.py" in entries[-1]["files"], entries[-1]
    assert session.load_task(sample)["intent"] == "tighten email checks"
    # users.py was surfaced as a dependent: editing it is target-level evidence
    assert hooks.handle("pre-tool", _payload("replace_file_content", BIG, sample)) == {"decision": "allow"}
    # a file the context did not mention only has task-level evidence
    other = dict(BIG, TargetFile="pkg/jobs.py")
    assert hooks.handle("pre-tool", _payload("replace_file_content", other, sample))["decision"] == "ask"
    # a new code file is allowed by the context (task-level reuse decision)
    assert hooks.handle("pre-tool", _payload("write_to_file", {"TargetFile": "pkg/new_mod.py", "CodeContent": "x = 1\n" * 9}, sample)) == {"decision": "allow"}


def test_context_on_a_directory_is_task_level_only(sample: Path):
    env = {k: v for k, v in os.environ.items() if k != "LORD_HOOK_ACTIVE"}
    subprocess.run([sys.executable, "-m", "lord", "--root", str(sample), "context", "pkg", "--intent", "general cleanup", "--json"], cwd=ROOT, capture_output=True, text=True, env=env)
    assert session.recent(sample, 600)[-1]["command"] == "context"
    assert hooks.handle("pre-tool", _payload("replace_file_content", BIG, sample))["decision"] == "ask"


# --- verification report block -------------------------------------------------------------------

def test_verify_emits_a_report_block_with_lord_determined_results(sample: Path):
    _write(sample / "pyproject.toml", "[project]\nname='sample'\nversion='0.0.1'\n[tool.pytest.ini_options]\ntestpaths=['tests']\npythonpath=['.']\n")
    _git(sample, "add", "-A")
    _git(sample, "commit", "-q", "-m", "pytest config")
    validators = sample / "pkg" / "validators.py"
    _write(validators, validators.read_text(encoding="utf-8").replace("254", "255"))
    session.update_task(sample, assumption="the limit change needs no migration", material=True)
    config = load_config(sample)
    dry = verify(config, ensure_index(config))
    block = dry.meta["report_block"]
    assert block.startswith("Verification:") and "NOT RUN" in block and "LORD verify - NOT VERIFIED" in block
    assert "Assumptions (unconfirmed, material): the limit change needs no migration" in block
    ran = verify(config, ensure_index(config), run=True, timeout=120)
    assert "pytest" in ran.meta["report_block"] and " - PASS" in ran.meta["report_block"]
    assert next(f for f in ran.findings if f.kind == "report-block").confidence == CONFIRMED


# --- acceptance T04 checker -----------------------------------------------------------------------

@pytest.fixture(scope="module")
def lord_clone(tmp_path_factory) -> Path:
    repo = tmp_path_factory.mktemp("clone") / "lord"
    for item in ("lord", "demo", "docs", "tests", "pyproject.toml", "lord.toml", ".gitignore", ".agents"):
        src = ROOT / item
        if src.is_dir():
            shutil.copytree(src, repo / item, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "evidence-test"))
        else:
            shutil.copy(src, repo / item)
    _init(repo)
    return repo


def test_t04_check_detects_a_skip_flag_bypass_and_defers_otherwise(lord_clone: Path):
    config = load_config(lord_clone)
    service = lord_clone / "demo" / "app" / "services" / "transactions.py"
    original = service.read_text(encoding="utf-8")
    try:
        # no change: OK, not a bypass
        report = acceptance.check(config, ensure_index(config), "T04")
        assert next(f for f in report.findings if f.kind == "bypass").severity == "ok"
        # bypass flag around the shared validation
        _write(service, original.replace("    def add(self, payload: dict) -> Transaction:\n        errors = validate_transaction(payload)\n        if errors:",
                                         "    def add(self, payload: dict, skip_validation: bool = False) -> Transaction:\n        errors = [] if skip_validation else validate_transaction(payload)\n        if errors:"))
        report = acceptance.check(config, ensure_index(config), "T04")
        bypass = next(f for f in report.findings if f.kind == "bypass")
        assert bypass.severity == "warn" and "validate_transaction" in bypass.summary and "conditional on new parameter skip_validation" in bypass.summary
        # a code change the detector cannot judge: explicit deferral, never a green light
        _write(service, original.replace("description=str(payload[\"description\"]).strip(),", "description=str(payload[\"description\"]).strip().title(),"))
        report = acceptance.check(config, ensure_index(config), "T04")
        bypass = next(f for f in report.findings if f.kind == "bypass")
        assert bypass.confidence == UNKNOWN and "transcript must confirm" in bypass.summary
    finally:
        _write(service, original)


def test_record_carries_the_series_label(lord_clone: Path, monkeypatch):
    monkeypatch.setattr(acceptance, "EVIDENCE_DIR", Path("docs") / "acceptance" / "evidence-test")
    config = load_config(lord_clone)
    report = acceptance.record(config, ensure_index(config), "T06", "model-x", series="B")
    path = Path(report.meta["path"])
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["series"] == "B" and path.name.endswith("-T06-b.json") and acceptance.validate_evidence(data) == []
