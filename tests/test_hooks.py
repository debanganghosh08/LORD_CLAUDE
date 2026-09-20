"""Phase 6 tests: hook configuration, matcher semantics, the three hook
decisions (pre-edit gate, completion gate, change-surface advisory), the
launcher contract (stdin -> JSON stdout, exit 0, both working directories,
Windows paths), internal-error and recursion safety, timeout handling, and
the absence of destructive side effects.

Payload shapes are the ones captured live from Antigravity CLI 1.2.7
(camelCase top-level keys; toolCall.args keys TargetFile, TargetContent,
ReplacementContent, CodeContent, Overwrite, AbsolutePath, CommandLine)."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from lord import hooks, session
from lord.config import load_config
from lord.doctor import check_hooks, validate_hooks_config
from lord.index import ensure_index

ROOT = Path(__file__).resolve().parents[1]
DUP = ROOT / "tests" / "fixtures" / "dup_repo"
HOOKS_JSON = ROOT / ".agents" / "hooks.json"
CONVERSATION = "11111111-2222-3333-4444-555555555555"


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    return completed.stdout


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha1()
    skip = {".lord", ".git", "__pycache__", ".pytest_cache"}  # tool caches, not user files
    for path in sorted(p for p in root.rglob("*") if p.is_file() and not (skip & set(p.parts))):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _payload(tool: str, args: dict, root: Path, **extra) -> dict:
    return {
        "toolCall": {"name": tool, "args": args},
        "stepIdx": 3,
        "conversationId": CONVERSATION,
        "workspacePaths": [str(root)],
        "transcriptPath": str(root / ".lord" / "transcript.jsonl"),
        "artifactDirectoryPath": str(root / ".lord"),
        "modelName": "test-model",
        **extra,
    }


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    target = tmp_path / "dup_repo"
    shutil.copytree(DUP, target)
    _git(target, "init", "-q", "-b", "main")
    _git(target, "config", "user.email", "t@example.com")
    _git(target, "config", "user.name", "t")
    _git(target, "config", "core.autocrlf", "false")
    _write(target / ".gitignore", ".lord/\n.pytest_cache/\n__pycache__/\n")
    _write(target / "pyproject.toml", "[project]\nname='dup'\nversion='0.0.1'\n[tool.pytest.ini_options]\ntestpaths=['tests']\npythonpath=['.']\n")
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "base")
    ensure_index(load_config(target))
    return target


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("LORD_HOOK_ACTIVE", raising=False)
    monkeypatch.delenv("LORD_HOOKS_DISABLED", raising=False)


# --- configuration --------------------------------------------------------------------

def test_shipped_hooks_json_is_valid_and_bounded():
    data = json.loads(_read(HOOKS_JSON))
    assert validate_hooks_config(data) == []
    lord = data["lord"]
    assert set(lord) == {"enabled", "PreToolUse", "PreInvocation", "PostInvocation", "Stop"}, "no PostToolUse (it cannot return a message)"
    pre = lord["PreToolUse"][0]
    assert pre["matcher"] == hooks.WRITE_TOOL_MATCHER
    for event in ("PreToolUse", "PreInvocation", "PostInvocation", "Stop"):
        handlers = [h for item in lord[event] for h in (item.get("hooks", [item]) if event == "PreToolUse" else [item])]
        for h in handlers:
            assert h["type"] == "command" and h["command"].startswith("python -m lord_hook ") and 0 < h["timeout"] <= 600
            assert '"' not in h["command"], "Antigravity keeps literal quotes on Windows; commands must not need them"
    assert lord["Stop"][0]["timeout"] >= 300, "Stop runs the project's tests"


def test_invalid_hooks_configs_are_rejected():
    assert validate_hooks_config({}) and validate_hooks_config([])
    bad = {"x": {"PreToolUse": [{"matcher": "*"}]}}
    assert any("matcher and a hooks list" in e for e in validate_hooks_config(bad))
    bad = {"x": {"Stop": [{"type": "command", "command": "python x", "timeout": 5000}]}}
    assert any("timeout" in e for e in validate_hooks_config(bad))
    bad = {"x": {"OnSave": [{"command": "python x"}]}}
    assert any("unknown event" in e for e in validate_hooks_config(bad))
    bad = {"x": {"Stop": [{"type": "script", "command": "x"}]}}
    assert any("only type 'command'" in e for e in validate_hooks_config(bad))
    bad = {"x": {"Stop": [{"command": ""}]}}
    assert any("non-empty command" in e for e in validate_hooks_config(bad))


def test_single_launcher_in_agents_and_doctor_sees_it():
    assert (ROOT / ".agents" / "lord_hook.py").is_file() and not (ROOT / "lord_hook.py").exists(), "Antigravity runs hooks from .agents/; one launcher only"
    findings = check_hooks(ROOT)
    assert [f.severity for f in findings] == ["ok"], [f.summary for f in findings]


def test_doctor_flags_broken_hooks_json(tmp_path: Path):
    _write(tmp_path / ".agents" / "hooks.json", "{not json")
    assert check_hooks(tmp_path)[0].severity == "error"
    _write(tmp_path / ".agents" / "hooks.json", json.dumps({"x": {"Stop": [{"command": "definitely-not-a-program-xyz run"}]}}))
    findings = check_hooks(tmp_path)
    assert any("not on PATH" in f.summary and f.severity == "error" for f in findings)


@pytest.mark.parametrize("tool,expected", [
    ("write_to_file", True), ("replace_file_content", True), ("multi_replace_file_content", True),
    ("view_file", False), ("run_command", False), ("grep_search", False), ("write_to_file_v2", False),
])
def test_matcher_semantics(tool: str, expected: bool):
    assert hooks.matcher_matches(hooks.WRITE_TOOL_MATCHER, tool) is expected
    assert hooks.matcher_matches("*", tool) and hooks.matcher_matches("", tool)
    assert hooks.matcher_matches("browser_.*", "browser_open") and not hooks.matcher_matches("browser_.*", "view_file")


# --- pre-edit gate ---------------------------------------------------------------------

def test_non_write_tools_and_non_code_files_are_allowed(repo: Path):
    assert hooks.handle("pre-tool", _payload("view_file", {"AbsolutePath": "app/api.py"}, repo)) == {"decision": "allow"}
    assert hooks.handle("pre-tool", _payload("run_command", {"CommandLine": "python -c 1"}, repo)) == {"decision": "allow"}
    assert hooks.handle("pre-tool", _payload("write_to_file", {"TargetFile": "docs/notes.md", "CodeContent": "x\n" * 50}, repo)) == {"decision": "allow"}
    assert hooks.handle("pre-tool", _payload("write_to_file", {"TargetFile": "tests/test_new.py", "CodeContent": "def test_x():\n    pass\n"}, repo)) == {"decision": "allow"}
    assert hooks.handle("pre-tool", _payload("replace_file_content", {"TargetFile": "pyproject.toml", "TargetContent": "a", "ReplacementContent": "b"}, repo)) == {"decision": "allow"}


def test_trivial_edit_is_allowed_without_evidence(repo: Path):
    args = {"TargetFile": "app/validators.py", "TargetContent": "< 100", "ReplacementContent": "< 120", "StartLine": "21", "EndLine": "21", "AllowMultiple": "False"}
    assert hooks.handle("pre-tool", _payload("replace_file_content", args, repo)) == {"decision": "allow"}
    log = [json.loads(l) for l in _read(repo / ".lord" / "session" / "hooks.log").splitlines()]
    assert "trivial edit" in log[-1]["audit"]


def test_meaningful_edit_without_any_investigation_is_denied(repo: Path):
    args = {"TargetFile": "app/validators.py", "TargetContent": "def validate_email(value: str) -> bool:\n    if not value:\n        return False\n    value = value.strip()\n",
            "ReplacementContent": "def validate_email(value: str) -> bool:\n    if not value:\n        return False\n    value = value.strip().lower()\n    log(value)\n"}
    result = hooks.handle("pre-tool", _payload("replace_file_content", args, repo))
    assert result["decision"] == "deny" and "python -m lord context app/validators.py" in result["reason"]


def test_target_level_evidence_allows_and_task_level_asks(repo: Path):
    big = {"TargetFile": "app\\validators.py", "TargetContent": "a\nb\nc\nd\n", "ReplacementContent": "1\n2\n3\n4\n5\n"}
    session.record(repo, "reuse", "normalize an email", {"names": ["EmailNormalizer"]})
    asked = hooks.handle("pre-tool", _payload("replace_file_content", big, repo))
    assert asked["decision"] == "ask" and "reuse" in asked["reason"]
    session.record(repo, "refs", "validate_email")  # a symbol defined in the target file
    assert hooks.handle("pre-tool", _payload("replace_file_content", big, repo)) == {"decision": "allow"}
    session.record(repo, "brief", "app/legacy/checks.py")
    absolute = dict(big, TargetFile=str(repo / "app" / "legacy" / "checks.py"))
    assert hooks.handle("pre-tool", _payload("replace_file_content", absolute, repo)) == {"decision": "allow"}


def test_new_code_file_requires_reuse_or_brief(repo: Path):
    new = {"TargetFile": "app/email_utils.py", "CodeContent": "def verify_email(v):\n    return True\n", "Overwrite": "True"}
    result = hooks.handle("pre-tool", _payload("write_to_file", new, repo))
    assert result["decision"] == "deny" and "lord reuse" in result["reason"]
    session.record(repo, "refs", "validate_email")
    assert hooks.handle("pre-tool", _payload("write_to_file", new, repo))["decision"] == "deny", "refs alone is not a reuse decision"
    session.record(repo, "reuse", "verify an email", {"names": ["verify_email"]})
    assert hooks.handle("pre-tool", _payload("write_to_file", new, repo)) == {"decision": "allow"}


def test_evidence_expires_outside_the_window(repo: Path):
    session.record(repo, "brief", "app/validators.py")
    big = {"TargetFile": "app/validators.py", "TargetContent": "a\nb\nc\nd\n", "ReplacementContent": "1\n2\n3\n4\n5\n"}
    later = time.time() + hooks.EVIDENCE_WINDOW_SECONDS + 60
    assert hooks.handle("pre-tool", _payload("replace_file_content", big, repo), now=later)["decision"] == "deny"


def test_paths_outside_workspace_are_not_gated(repo: Path, tmp_path: Path):
    outside = {"TargetFile": str(tmp_path / "elsewhere.py"), "CodeContent": "x = 1\n" * 10}
    assert hooks.handle("pre-tool", _payload("write_to_file", outside, repo)) == {"decision": "allow"}


# --- completion gate -------------------------------------------------------------------

def test_stop_allows_when_nothing_changed_or_not_idle(repo: Path):
    assert hooks.handle("stop", _payload("", {}, repo, fullyIdle=True, terminationReason="COMPLETED")) == {}
    validators = repo / "app" / "validators.py"
    _write(validators, _read(validators).replace("return bool(EMAIL_RE.match(value))", "return False"))
    assert hooks.handle("stop", _payload("", {}, repo, fullyIdle=False)) == {}


def test_stop_blocks_on_failing_verification_then_caps(repo: Path):
    validators = repo / "app" / "validators.py"
    _write(validators, _read(validators).replace("return bool(EMAIL_RE.match(value))", "return False"))
    payload = _payload("", {}, repo, fullyIdle=True, terminationReason="COMPLETED", executionNum=1)
    first = hooks.handle("stop", payload)
    assert first["decision"] == "continue" and "verification failed" in first["reason"] and "1/2" in first["reason"]
    second = hooks.handle("stop", payload)
    assert second["decision"] == "continue" and "2/2" in second["reason"]
    assert hooks.handle("stop", payload) == {}, "after the cap the turn must be allowed to end"
    state = session.load_state(repo, f"stop-{CONVERSATION}")
    assert state["continuations"] == 2 and state["verify"]["step_results"] == {"pytest": "fail"}


def test_stop_allows_when_verification_passes_and_caches_by_tree(repo: Path):
    validators = repo / "app" / "validators.py"
    _write(validators, _read(validators).replace("< 100", "< 120"))
    payload = _payload("", {}, repo, fullyIdle=True)
    started = time.time()
    assert hooks.handle("stop", payload) == {}
    first = time.time() - started
    state = session.load_state(repo, f"stop-{CONVERSATION}")
    assert state["verify"]["step_results"] == {"pytest": "pass"} and state["continuations"] == 0
    started = time.time()
    assert hooks.handle("stop", payload) == {}
    assert time.time() - started < first / 2 or time.time() - started < 0.5, "unchanged tree must reuse the cached verification"


def test_stop_does_not_block_on_advisory_signals(repo: Path):
    # untested change + TODO marker: outstanding, but no deterministic failure -> allow
    models = repo / "app" / "legacy" / "models.py"
    _write(models, _read(models) + "\n\ndef helper():\n    return 1  # TODO later\n")
    assert hooks.handle("stop", _payload("", {}, repo, fullyIdle=True)) == {}
    log = [json.loads(l) for l in _read(repo / ".lord" / "session" / "hooks.log").splitlines()]
    assert "not verified" in log[-1]["audit"] and "marker" in log[-1]["audit"]


def test_stop_respects_budget_without_blocking(repo: Path, monkeypatch):
    validators = repo / "app" / "validators.py"
    _write(validators, _read(validators).replace("return bool(EMAIL_RE.match(value))", "return False"))
    import lord.review as review

    real = review.verify

    def slow_verify(*args, **kwargs):
        time.sleep(0.3)
        return real(*args, **kwargs)

    monkeypatch.setattr(review, "verify", slow_verify)
    result = hooks.handle("stop", _payload("", {}, repo, fullyIdle=True), budget_seconds=0.1)
    assert result == {}
    log = [json.loads(l) for l in _read(repo / ".lord" / "session" / "hooks.log").splitlines()]
    assert "exceeded the hook budget" in log[-1]["audit"]


# --- change-surface advisory -----------------------------------------------------------

def test_post_invocation_warns_on_high_bloat_only_when_tree_changed(repo: Path):
    assert hooks.handle("post-invocation", _payload("", {}, repo, invocationNum=1)) == {}
    original = _read(repo / "app" / "validators.py")
    body = original.split("def validate_email")[1].split("def validate_name")[0]
    _write(repo / "app" / "email_utils.py", "from app.validators import EMAIL_RE, MAX_EMAIL_LENGTH\n\n\ndef verify_email" + body)
    result = hooks.handle("post-invocation", _payload("", {}, repo, invocationNum=2))
    message = result["injectSteps"][0]["ephemeralMessage"]
    assert message.startswith("LORD change-surface HIGH") and "verify_email resembles existing validate_email" in message
    assert hooks.handle("post-invocation", _payload("", {}, repo, invocationNum=3)) == {}, "same tree: no repeated warning"


def test_post_invocation_warns_once_on_elevated_transition(repo: Path):
    checks = repo / "app" / "legacy" / "checks.py"
    _write(checks, "\n".join(line.replace("    ", "  ") if line.startswith("    ") else line for line in _read(checks).splitlines()) + "\n")
    first = hooks.handle("post-invocation", _payload("", {}, repo, invocationNum=1))
    assert "ELEVATED" in first["injectSteps"][0]["ephemeralMessage"] and "formatting-only churn" in first["injectSteps"][0]["ephemeralMessage"]
    _write(checks, _read(checks) + "\n")
    assert hooks.handle("post-invocation", _payload("", {}, repo, invocationNum=2)) == {}, "still elevated: no nagging"


# --- safety: errors, recursion, side effects, launcher contract -------------------------

def test_internal_error_defaults_to_allow_and_is_logged(repo: Path, monkeypatch):
    monkeypatch.setattr(hooks, "decide_pre_tool", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    payload = _payload("write_to_file", {"TargetFile": "app/x.py", "CodeContent": "x = 1\n" * 9}, repo)
    assert hooks.handle("pre-tool", payload) == {"decision": "allow"}
    monkeypatch.setattr(hooks, "decide_stop", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert hooks.handle("stop", _payload("", {}, repo, fullyIdle=True)) == {}
    log = [json.loads(l) for l in _read(repo / ".lord" / "session" / "hooks.log").splitlines()]
    assert log[-1]["outcome"] == "error" and "boom" in log[-1]["audit"]


def test_disabled_and_recursion_guards(repo: Path, monkeypatch):
    denied = _payload("write_to_file", {"TargetFile": "app/new.py", "CodeContent": "x = 1\n" * 9}, repo)
    assert hooks.handle("pre-tool", denied)["decision"] == "deny"
    monkeypatch.setenv("LORD_HOOKS_DISABLED", "1")
    assert hooks.handle("pre-tool", denied) == {"decision": "allow"}
    monkeypatch.delenv("LORD_HOOKS_DISABLED")
    monkeypatch.setenv("LORD_HOOK_ACTIVE", "1")
    import io

    buffer = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buffer)
    assert hooks.main(["pre-tool"], stdin=json.dumps(denied)) == 0
    assert json.loads(buffer.getvalue()) == {"decision": "allow"}


def test_malformed_stdin_and_unknown_event_are_safe(repo: Path, monkeypatch):
    import io

    for argv, raw, expected in (
        (["pre-tool"], "{not json", {"decision": "allow"}),
        (["pre-tool"], "", {"decision": "allow"}),
        (["pre-tool"], "[1,2]", {"decision": "allow"}),
        (["stop"], "{not json", {}),
        (["bogus-event"], "{}", {}),
        ([], "{}", {}),
    ):
        buffer = io.StringIO()
        monkeypatch.setattr(sys, "stdout", buffer)
        assert hooks.main(argv, stdin=raw, root=repo) == 0
        assert json.loads(buffer.getvalue()) == expected


def test_hooks_never_modify_the_workspace(repo: Path):
    validators = repo / "app" / "validators.py"
    _write(validators, _read(validators).replace("return bool(EMAIL_RE.match(value))", "return False"))
    before = _tree_hash(repo)
    for event, payload in (
        ("pre-tool", _payload("write_to_file", {"TargetFile": "app/new.py", "CodeContent": "x\n" * 9}, repo)),
        ("pre-tool", _payload("replace_file_content", {"TargetFile": "app/validators.py", "TargetContent": "a\nb\nc\nd\n", "ReplacementContent": "1\n2\n3\n4\n5\n"}, repo)),
        ("post-invocation", _payload("", {}, repo, invocationNum=1)),
        ("stop", _payload("", {}, repo, fullyIdle=True)),
    ):
        hooks.handle(event, payload)
    assert _tree_hash(repo) == before
    assert (repo / ".lord" / "session" / "hooks.log").is_file()


@pytest.mark.parametrize("cwd_rel", [".agents"])
def test_launcher_contract_from_the_agents_directory(repo: Path, cwd_rel: str):
    """Exactly what Antigravity does (confirmed live): run the command string
    with the payload on stdin, from the workspace's .agents folder."""
    shutil.copytree(ROOT / ".agents", repo / ".agents", dirs_exist_ok=True)
    shutil.copytree(ROOT / "lord", repo / "lord", ignore=shutil.ignore_patterns("__pycache__"))
    payload = _payload("write_to_file", {"TargetFile": "app\\brand_new.py", "CodeContent": "x = 1\n" * 9, "Overwrite": "True"}, repo)
    env = {k: v for k, v in os.environ.items() if k not in ("LORD_HOOK_ACTIVE", "LORD_HOOKS_DISABLED")}
    completed = subprocess.run(["python", "-m", "lord_hook", "pre-tool"], cwd=repo / cwd_rel, input=json.dumps(payload), capture_output=True, text=True, env=env, timeout=60)
    assert completed.returncode == 0, completed.stderr
    out = json.loads(completed.stdout)
    assert out["decision"] == "deny" and "brand_new.py" in out["reason"]
    completed = subprocess.run(["python", "-m", "lord_hook", "stop", "--timeout", "120"], cwd=repo / cwd_rel, input=json.dumps(_payload("", {}, repo, fullyIdle=True)), capture_output=True, text=True, env=env, timeout=120)
    assert completed.returncode == 0 and json.loads(completed.stdout) == {}
    completed = subprocess.run(["python", "-m", "lord_hook", "post-invocation"], cwd=repo / cwd_rel, input="garbage", capture_output=True, text=True, env=env, timeout=60)
    assert completed.returncode == 0 and json.loads(completed.stdout) == {}
    log = [json.loads(l) for l in _read(repo / ".lord" / "session" / "hooks.log").splitlines()]
    assert Path(log[0]["cwd"]).resolve() == (repo / cwd_rel).resolve()


def test_cli_investigation_commands_record_evidence(repo: Path):
    env = {k: v for k, v in os.environ.items() if k not in ("LORD_HOOK_ACTIVE",)}
    for args in (["brief", "validate_email", "--intent", "tighten validation"], ["reuse", "check an email", "--name", "EmailChecker"], ["inventory"]):
        completed = subprocess.run([sys.executable, "-m", "lord", "--root", str(repo), *args, "--json"], cwd=ROOT, capture_output=True, text=True, env=env)
        assert completed.returncode == 0, completed.stderr
    entries = session.recent(repo, 600)
    assert [(e["command"], e["target"]) for e in entries] == [("brief", "validate_email"), ("reuse", "check an email")]
    assert entries[1]["names"] == ["EmailChecker"]
    assert session.evidence_for(repo, "app/validators.py", {"validate_email"}, 600)[0] == "target"
