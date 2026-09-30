"""Phase 8B release-candidate tests: the marker detector, the clarification
boundary, the verification contract, the plugin (manifest, layout, launcher,
install / update / rollback / uninstall), and workspace isolation and
portability. Every workspace here is a fixture under a temporary directory;
nothing reads or writes the user's real plugin folders or Python user site."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from lord import hooks, paths, plugin, session
from lord.config import load_config
from lord.context import matching_skills
from lord.index import ensure_index
from lord.markers import added_markers, markers_in
from lord.memory import Store
from lord.review import model_claims, reconcile, verify

ROOT = Path(__file__).resolve().parents[1]
CONV = "rc-conversation"


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    return completed.stdout


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _repo(path: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        _write(path / rel, text)
    _git(path, "init", "-q", "-b", "main")
    for key, value in (("user.email", "t@example.com"), ("user.name", "t"), ("core.autocrlf", "false")):
        _git(path, "config", key, value)
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "base")
    return path


def _payload(tool: str, args: dict, root: Path) -> dict:
    return {"toolCall": {"name": tool, "args": args}, "conversationId": CONV, "workspacePaths": [str(root)]}


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("LORD_HOOK_ACTIVE", raising=False)
    monkeypatch.delenv("LORD_HOOKS_DISABLED", raising=False)
    monkeypatch.setattr(paths, "_home", lambda: tmp_path / "fake-home")   # no real ~/.gemini is ever read


# --- 1. unfinished-work markers --------------------------------------------------------------

MARKER_CASES = [
    # (path, source, markers expected) - the five required kinds and their neighbours
    ("app/service.py", "def f():\n    return 1  # TODO: handle the empty case\n", 1),        # real TODO in source
    ("app/service.py", "def f():\n    # FIXME(ops) wrong timezone\n    return 1\n", 1),
    ("docs/guide.md", "An added TODO marker makes verify report NOT VERIFIED.\n", 0),        # documentation prose that mentions the marker
    ("docs/guide.md", "TODO: document the export format\n", 1),                                # an actual doc marker
    ("docs/guide.md", "```python\n# TODO: example inside a code fence\n```\n", 0),
    ("tests/test_x.py", 'SAMPLE = "x = 1  # TODO: overflow"\n', 0),                          # a marker inside a test fixture string
    ("tests/test_x.py", "def test_x():\n    pass  # TODO: assert the result\n", 1),           # unfinished test is unfinished
    ("app/notes.py", "# todo-list handling lives in app/todo.py\n# TODOS are tracked elsewhere\n", 0),  # marker-like words in comments
    ("app/markers.py", "# the TODO/FIXME detector ignores prose about markers\nMARKERS = ('TODO', 'FIXME')\n", 0),  # completed code discussing TODO detection
    ("web/app.js", "const label = '// TODO not a comment';\nrender(); // HACK: remove after launch\n", 1),
    ("app/words.py", "# TODO-like wording and TODO/FIXME pairs are prose\n", 0),
    ("tests/fixtures/sample/mod.py", "# TODO: planted fixture content\n", 0),                 # fixture data, not work
    ("data/settings.json", '{"note": "TODO: tune"}\n', 0),
]


@pytest.mark.parametrize("path,source,expected", MARKER_CASES)
def test_marker_semantics(path: str, source: str, expected: int):
    assert len(markers_in(path, source)) == expected, markers_in(path, source)


def test_markers_only_count_added_lines_including_new_untracked_files(tmp_path: Path):
    repo = _repo(tmp_path / "m", {"app/a.py": "# TODO: old debt, not added by this change\nx = 1\n", "docs/readme.md": "hello\n"})
    _write(repo / "app" / "a.py", "# TODO: old debt, not added by this change\nx = 2\n")
    _write(repo / "docs" / "readme.md", "hello\nThe verify TODO detector ignores this sentence.\n")
    assert added_markers(repo) == []
    _write(repo / "app" / "new.py", "def later():\n    raise NotImplementedError  # TODO: implement\n")   # untracked, never in `git diff`
    found = added_markers(repo, untracked=["app/new.py"])
    assert found == ["app/new.py:2: raise NotImplementedError  # TODO: implement"]


def test_marker_fact_decides_the_verdict_and_prose_does_not(tmp_path: Path):
    repo = _repo(tmp_path / "v", {"pkg/__init__.py": "", "pkg/core.py": "def f():\n    return 1\n",
                                  "tests/test_core.py": "from pkg.core import f\n\n\ndef test_f():\n    assert f() == 1\n",
                                  "pyproject.toml": "[project]\nname='v'\nversion='0'\n[tool.pytest.ini_options]\npythonpath=['.']\n"})
    _write(repo / "README.md", "Verify reports NOT VERIFIED for an added TODO marker.\n")
    config = load_config(repo)
    report = verify(config, ensure_index(config), run=True, timeout=120)
    assert report.meta["verdict"] == "verified", report.to_markdown()
    _write(repo / "pkg" / "core.py", "def f():\n    return 1  # TODO: cache this\n")
    report = verify(config, ensure_index(config), run=True, timeout=120)
    assert report.meta["verdict"] == "not verified" and report.meta["outstanding"] == ["1 unresolved marker(s)"]


def test_lord_repository_does_not_flag_its_own_documentation():
    """LORD's own history is full of prose about TODO markers: none is one."""
    found = added_markers(ROOT, base="4cb5eaa")
    assert found == [], found


# --- 2. clarification: material ambiguity -> confirmation boundary -> user decision ---------

@pytest.fixture
def accounts(tmp_path: Path) -> Path:
    """Generalised ambiguity fixture 1 (Python): "remove inactive users" -
    what is inactive, and is removal a hard or a soft delete?"""
    repo = _repo(tmp_path / "accounts", {
        ".gitignore": ".lord/\n",
        "accounts/__init__.py": "",
        "accounts/cleanup.py": "def purge_inactive(users):\n    kept = []\n    for user in users:\n        kept.append(user)\n    return kept\n",
        "accounts/models.py": "class User:\n    def __init__(self, name, last_login):\n        self.name = name\n        self.last_login = last_login\n",
    })
    ensure_index(load_config(repo))
    session.record(repo, "brief", "accounts/cleanup.py")
    session.record(repo, "brief", "accounts/models.py")
    return repo


EDIT = {"TargetFile": "accounts/cleanup.py", "TargetContent": "    kept = []\n    for user in users:\n        kept.append(user)\n    return kept\n",
        "ReplacementContent": "    cutoff = 90\n    kept = [u for u in users if u.last_login < cutoff]\n    return kept\n\n\n"}


def test_material_assumption_turns_the_next_edit_into_a_user_decision(accounts: Path):
    session.update_task(accounts, request="remove inactive users", intent="delete users that have not logged in recently")
    session.update_task(accounts, assumption="inactive = no login for 90 days; removal is a hard delete", material=True)
    assert session.decision_state(session.load_task(accounts)) == "awaiting-confirmation"
    asked = hooks.handle("pre-tool", _payload("replace_file_content", EDIT, accounts))
    assert asked["decision"] == "ask" and "hard delete" in asked["reason"] and "confirmation boundary" in asked["reason"]
    # the user rejected: the file is unchanged, so the next edit asks again
    again = hooks.handle("pre-tool", _payload("replace_file_content", EDIT, accounts))
    assert again["decision"] == "ask"
    # the user approved: the gated edit landed; its assumption is now confirmed by the user's decision
    _write(accounts / "accounts" / "cleanup.py", "def purge_inactive(users):\n    return [u for u in users if u.last_login < 90]\n")
    allowed = hooks.handle("pre-tool", _payload("replace_file_content", {**EDIT, "TargetContent": "x\ny\nz\nw\n"}, accounts))
    assert allowed == {"decision": "allow"}
    task = session.load_task(accounts)
    assert task["assumptions"][0]["confirmed"] and task["assumptions"][0]["source"] == "edit-gate approval"
    assert session.decision_state(task) == "clear"


def test_confirmation_boundary_never_overrides_an_investigation_denial(accounts: Path):
    (accounts / ".lord" / "session" / "activity.jsonl").unlink()   # no investigation ran in this session
    session.update_task(accounts, assumption="exports keep the old column order", material=True)
    fresh = {"TargetFile": "accounts/export.py", "CodeContent": "def export(users):\n    return users\n" * 3}
    denied = hooks.handle("pre-tool", _payload("write_to_file", fresh, accounts))
    assert denied["decision"] == "deny" and "new code file" in denied["reason"], "approval of an ask must never let an uninvestigated edit through"


def test_cosmetic_assumptions_never_gate(accounts: Path):
    session.update_task(accounts, assumption="name the helper is_inactive", material=False)
    assert session.decision_state(session.load_task(accounts)) == "clear"
    assert hooks.handle("pre-tool", _payload("replace_file_content", EDIT, accounts)) == {"decision": "allow"}


@pytest.fixture
def pricing(tmp_path: Path) -> Path:
    """Generalised ambiguity fixture 2 (JavaScript): "round the prices" -
    half-up or banker's rounding, and to cents or to whole units?"""
    repo = _repo(tmp_path / "pricing", {
        ".gitignore": ".lord/\nnode_modules/\n",
        "package.json": json.dumps({"name": "pricing", "version": "1.0.0", "scripts": {"test": "node test/pricing.test.js"}}),
        "src/pricing.js": "function total(items) {\n  return items.reduce((sum, i) => sum + i.price, 0);\n}\nmodule.exports = { total };\n",
        "test/pricing.test.js": "const { total } = require('../src/pricing');\nif (total([{price: 1}]) !== 1) { process.exit(1); }\n",
    })
    ensure_index(load_config(repo))
    session.record(repo, "context", "src/pricing.js")
    return repo


def test_open_question_blocks_every_code_edit_until_the_user_answers(pricing: Path):
    session.update_task(pricing, request="round the prices", question="round half-up or banker's rounding, to cents or whole units?")
    assert session.decision_state(session.load_task(pricing)) == "blocked"
    one_line = {"TargetFile": "src/pricing.js", "TargetContent": "  return items.reduce((sum, i) => sum + i.price, 0);",
                "ReplacementContent": "  return Math.round(items.reduce((sum, i) => sum + i.price, 0));"}
    denied = hooks.handle("pre-tool", _payload("replace_file_content", one_line, pricing))
    assert denied["decision"] == "deny" and "open question" in denied["reason"], "a one-line edit can implement the undecided reading"
    assert hooks.handle("pre-tool", _payload("write_to_file", {"TargetFile": "NOTES.md", "CodeContent": "draft\n" * 5}, pricing)) == {"decision": "allow"}, "notes are not code"
    session.update_task(pricing, resolve="round half-up", answer="half-up, to cents")
    assert session.decision_state(session.load_task(pricing)) == "clear"
    assert hooks.handle("pre-tool", _payload("replace_file_content", one_line, pricing)) == {"decision": "allow"}


def test_task_show_reports_decision_state_and_confirmation_source(accounts: Path):
    session.update_task(accounts, assumption="inactive = 90 days", material=True)
    session.update_task(accounts, confirm="inactive")
    completed = subprocess.run([sys.executable, "-m", "lord", "--root", str(accounts), "task", "show", "--json"], cwd=ROOT, capture_output=True, text=True, timeout=120)
    data = json.loads(completed.stdout)
    assert data["meta"]["decision_state"] == "clear"
    assert any("confirmed (model-reported)" in f["summary"] for f in data["findings"] if f["kind"] == "assumption"), "a model's `confirm` is labelled as its claim"


# --- 3. verification contract: MODEL-REPORTED vs LORD-DETERMINED ---------------------------

LORD_FAIL = {"ran": True, "fresh": True, "verdict": "not verified", "outstanding": ["pytest fail"], "step_results": {"pytest": "fail"}}
LORD_PASS = {"ran": True, "fresh": True, "verdict": "verified", "outstanding": [], "step_results": {"pytest": "pass"}}
CLAIM_PASS = "Done.\n\nVerification:\n  python -m pytest -q - PASS\n  LORD verify - VERIFIED\n"


def test_a_model_claim_cannot_override_failed_verification():
    result = reconcile(CLAIM_PASS, LORD_FAIL)
    assert result["status"] == "NOT VERIFIED" and result["basis"] == "LORD-determined"
    assert any("LORD determined NOT VERIFIED" in c for c in result["contradictions"])
    assert any("python -m pytest -q: reply says PASS, LORD determined FAIL" == c for c in result["contradictions"])
    prose = reconcile("All tests pass, fully tested.", LORD_FAIL)
    assert prose["status"] == "NOT VERIFIED" and prose["model"] == "prose claim only (heuristic)"


def test_lord_pass_is_factual_with_or_without_a_model_report():
    assert reconcile(CLAIM_PASS, LORD_PASS)["status"] == "VERIFIED" and reconcile(CLAIM_PASS, LORD_PASS)["contradictions"] == []
    silent = reconcile("Changed the formatter.", LORD_PASS)
    assert silent["status"] == "VERIFIED" and silent["model"] == "absent"


def test_missing_model_report_is_distinguishable_from_failed_verification():
    missing_report = reconcile("Changed the formatter.", LORD_PASS)
    failed = reconcile("Changed the formatter.", LORD_FAIL)
    nothing = reconcile("Changed the formatter.", {})
    claim_only = reconcile(CLAIM_PASS, {})
    stale = reconcile(CLAIM_PASS, {**LORD_PASS, "fresh": False})
    assert (missing_report["status"], missing_report["model"]) == ("VERIFIED", "absent")
    assert (failed["status"], failed["model"]) == ("NOT VERIFIED", "absent")
    assert (nothing["status"], nothing["lord"]) == ("NO VERIFICATION", "not run")
    assert (claim_only["status"], claim_only["basis"]) == ("UNVERIFIED CLAIM", "model-reported")
    assert (stale["status"], stale["lord"]) == ("UNVERIFIED CLAIM", "stale"), "a pass on an older tree is not a pass on this one"


def test_completed_verification_is_reported_consistently(tmp_path: Path, monkeypatch):
    repo = _repo(tmp_path / "c", {"pkg/__init__.py": "", "pkg/core.py": "def f():\n    return 1\n",
                                  "tests/test_core.py": "from pkg.core import f\n\n\ndef test_f():\n    assert f() == 1\n",
                                  "pyproject.toml": "[project]\nname='c'\nversion='0'\n[tool.pytest.ini_options]\npythonpath=['.']\n"})
    _write(repo / "pkg" / "core.py", "def f():\n    return 1\n\n\ndef g():\n    return f()\n")
    config = load_config(repo)
    first = verify(config, ensure_index(config), run=True, timeout=120)
    second = verify(config, ensure_index(config), run=True, timeout=120)
    assert first.meta["report_block"] == second.meta["report_block"], "same tree, same results, same block"
    claims = model_claims("Changed pkg/core.py.\n\n" + first.meta["report_block"])
    assert claims["present"] and claims["verdict"] == "VERIFIED" and set(claims["steps"].values()) == {"PASS"}
    recorded = session.load_verification(repo)
    assert recorded["fresh"] and recorded["verdict"] == "verified"
    assert reconcile(first.meta["report_block"], recorded) == reconcile(second.meta["report_block"], recorded)
    assert reconcile(first.meta["report_block"], recorded)["status"] == "VERIFIED"
    # the Stop gate reuses this executed result instead of running the suite again
    import lord.review

    monkeypatch.setattr(lord.review, "verify", lambda *a, **k: (_ for _ in ()).throw(AssertionError("re-ran the suite")))
    assert hooks.decide_stop({"conversationId": CONV, "workspacePaths": [str(repo)], "fullyIdle": True}, repo).get("decision") != "continue"
    # a failing change after the pass: the record is stale, LORD re-determines
    monkeypatch.undo()
    _write(repo / "pkg" / "core.py", "def f():\n    return 2\n")
    assert session.load_verification(repo)["fresh"] is False
    failed = verify(config, ensure_index(config), run=True, timeout=120)
    assert failed.meta["verdict"] == "not verified"
    assert reconcile(CLAIM_PASS, session.load_verification(repo))["status"] == "NOT VERIFIED"


def test_cli_reconcile(tmp_path: Path):
    reply = tmp_path / "reply.md"
    reply.write_text(CLAIM_PASS, encoding="utf-8")
    completed = subprocess.run([sys.executable, "-m", "lord", "--root", str(tmp_path), "verify", "--reconcile", str(reply), "--json"], cwd=ROOT, capture_output=True, text=True, timeout=120)
    data = json.loads(completed.stdout)
    assert data["meta"]["status"] == "UNVERIFIED CLAIM" and data["meta"]["lord"] == "not run"


# --- 4. the plugin -------------------------------------------------------------------------------

PLUGIN_SRC, RUNTIME_SRC = plugin.source_dirs()


def test_manifest_uses_only_documented_fields():
    data = json.loads((PLUGIN_SRC / "plugin.json").read_text(encoding="utf-8"))
    assert set(data) <= plugin.MANIFEST_KEYS and data["name"] == "lord" and plugin.NAME_RE.match(data["name"])
    assert "version" not in data and "api" not in json.dumps(data).lower().replace("no model api", "").replace("no api key", "")


def test_hook_commands_are_relative_quote_free_and_bounded():
    data = json.loads((PLUGIN_SRC / "hooks.json").read_text(encoding="utf-8"))
    for event, entries in data["lord"].items():
        if event == "enabled":
            continue
        for entry in entries:
            for handler in entry.get("hooks", [entry]):
                command = handler["command"]
                assert command.startswith(plugin.SOURCE_HOOK_PREFIX) and '"' not in command and ":" not in command and "\\" not in command, command
                assert 0 < handler["timeout"] <= 600


def test_source_is_valid_and_carries_no_machine_paths_secrets_or_apis():
    assert plugin.validate_source(PLUGIN_SRC, RUNTIME_SRC, forbidden_paths=(str(ROOT), ROOT.as_posix(), str(Path.home()))) == []
    assert plugin._stdlib_violations(RUNTIME_SRC) == []
    assert json.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8").split("dependencies = ")[1].split("\n")[0]) == []


def test_validation_rejects_bad_sources(tmp_path: Path):
    src = tmp_path / "plugin"
    shutil.copytree(PLUGIN_SRC, src, ignore=shutil.ignore_patterns("__pycache__"))
    runtime = tmp_path / "lord"
    shutil.copytree(RUNTIME_SRC, runtime, ignore=shutil.ignore_patterns("__pycache__"))
    _write(src / "plugin.json", json.dumps({"name": "lord", "description": "x", "version": "1", "apiKey": "abc"}))
    _write(src / "credentials.json", "{}")
    _write(runtime / "net.py", "import requests\n")
    _write(src / "skills" / "lord-memory" / "notes.md", f"see {tmp_path / 'dev'}\n")
    errors = plugin.validate_source(src, runtime, forbidden_paths=(str(tmp_path / "dev"),))
    joined = "\n".join(errors)
    assert "undocumented field(s) ['apiKey', 'version']" in joined and "credentials.json: secret-like" in joined
    assert "imports requests" in joined and "contains the machine path" in joined


def test_install_layout_is_the_product_only(tmp_path: Path):
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    report = plugin.install(plugins, cli=False)
    assert not report.has_errors, report.to_markdown()
    target = plugins / "lord"
    files = {p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file()}
    for required in ("plugin.json", "hooks.json", "lord_hook.py", "lord_cli.py", "install.json", "LICENSE", "rules/lord-operating-contract.md",
                     "skills/lord-pre-edit-audit/SKILL.md", "agents/lord-investigator.md", "runtime/lord/cli.py", "runtime/lord/extractors/python_ast.py"):
        assert required in files, required
    for leaked in ("docs", "tests", "demo", "evidence", "oracle", "memory.jsonl", "handoff.json", ".lord", "__pycache__", "lord.toml", ".pyc", "acceptance.py"):
        assert not any(leaked in f for f in files), leaked
    answers = ("month_bounds", "normalize_text", "format_amount", "validate_transaction", "DEFAULT_PAGE_SIZE", "last month total")
    shipped = "".join((target / f).read_text(encoding="utf-8", errors="ignore") for f in files)
    assert not [a for a in answers if a in shipped], "no scenario prompt or expected answer ships in the plugin"
    assert (target / "hooks.json").read_bytes() == (PLUGIN_SRC / "hooks.json").read_bytes(), "hooks.json ships unchanged"
    record = json.loads((target / "install.json").read_text(encoding="utf-8"))
    assert record["version"] == plugin.__version__ and set(record["files"]) == files - {"install.json"}
    assert str(ROOT) not in "".join((target / f).read_text(encoding="utf-8", errors="ignore") for f in files if f != "install.json")


def test_install_is_idempotent_and_dry_run_writes_nothing(tmp_path: Path):
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    dry = plugin.install(plugins, cli=False, dry_run=True)
    assert not dry.has_errors and not (plugins / "lord").exists()
    plugin.install(plugins, cli=False)
    stamps = {p: p.stat().st_mtime_ns for p in (plugins / "lord").rglob("*") if p.is_file()}
    again = plugin.install(plugins, cli=False)
    assert "already installed and identical" in again.findings[-1].summary
    assert stamps == {p: p.stat().st_mtime_ns for p in (plugins / "lord").rglob("*") if p.is_file()}


def test_update_rollback_and_uninstall(tmp_path: Path):
    src, runtime = tmp_path / "src" / "plugin", tmp_path / "src" / "lord"
    shutil.copytree(PLUGIN_SRC, src, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(RUNTIME_SRC, runtime, ignore=shutil.ignore_patterns("__pycache__"))
    plugins, site_dir = tmp_path / "plugins", tmp_path / "site"
    plugins.mkdir()
    plugin.install(plugins, site_dir=site_dir, source=(src, runtime))
    rule = plugins / "lord" / "rules" / "lord-operating-contract.md"
    v1 = rule.read_bytes()
    _write(src / "rules" / "lord-operating-contract.md", v1.decode("utf-8") + "\nAn added line.\n")
    updated = plugin.install(plugins, site_dir=site_dir, source=(src, runtime))
    assert updated.meta["changed"] == ["rules/lord-operating-contract.md"] and rule.read_bytes() != v1
    assert (plugins / "lord" / plugin.ROLLBACK_ARCHIVE).is_file()
    assert not plugin.rollback(plugins).has_errors and rule.read_bytes() == v1
    assert plugin.status(plugins, site_dir=site_dir).meta["drift"] == []
    assert not plugin.rollback(plugins).has_errors and rule.read_bytes() != v1, "rollback swaps, so it can be undone"
    removed = plugin.uninstall(plugins, site_dir=site_dir)
    assert not (plugins / "lord").exists() and not (site_dir / plugin.CLI_PTH).exists() and "removed" in removed.findings[0].summary
    assert "nothing removed" in plugin.uninstall(plugins, site_dir=site_dir).findings[0].summary


def test_install_refuses_a_directory_it_did_not_create(tmp_path: Path):
    plugins = tmp_path / "plugins"
    _write(plugins / "lord" / "mine.txt", "someone else's plugin")
    report = plugin.install(plugins, cli=False)
    assert report.has_errors and "was not installed by LORD" in report.findings[-1].summary
    assert (plugins / "lord" / "mine.txt").read_text(encoding="utf-8") == "someone else's plugin"
    assert "nothing removed" in plugin.uninstall(plugins).findings[0].summary and (plugins / "lord" / "mine.txt").exists()


def test_global_target_requires_antigravity_and_is_never_created_blindly(tmp_path: Path):
    target = plugin.resolve_plugins_dir(use_global=True)
    assert target == tmp_path / "fake-home" / ".gemini" / "config" / "plugins"
    refused = plugin.install(target, cli=False)
    assert refused.has_errors and not (tmp_path / "fake-home").exists()
    with pytest.raises(ValueError):
        plugin.resolve_plugins_dir(dest=tmp_path, use_global=True)


def test_cli_registration_and_fallback_resolve_the_installed_runtime(tmp_path: Path):
    plugins, site_dir, neutral = tmp_path / "plugins", tmp_path / "site", tmp_path / "neutral"
    plugins.mkdir()
    neutral.mkdir()
    report = plugin.install(plugins, site_dir=site_dir)
    runtime = plugins / "lord" / "runtime"
    assert (site_dir / plugin.CLI_PTH).read_text(encoding="utf-8").strip() == str(runtime), report.to_markdown()
    probe = "import site, sys; site.addsitedir(sys.argv[1]); import lord, os; print(os.path.dirname(os.path.dirname(os.path.abspath(lord.__file__))))"
    completed = subprocess.run([sys.executable, "-c", probe, str(site_dir)], cwd=neutral, capture_output=True, text=True, timeout=60)
    assert Path(completed.stdout.strip()) == runtime, completed.stderr
    workspace = _repo(tmp_path / "ws", {"src/a.py": "def a():\n    return 1\n"})
    completed = subprocess.run([sys.executable, str(plugins / "lord" / "lord_cli.py"), "--root", str(workspace), "doctor", "--json"],
                               cwd=neutral, capture_output=True, text=True, timeout=120, env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"})
    data = json.loads(completed.stdout)
    kinds = {f["kind"]: f for f in data["findings"]}
    assert kinds["runtime"]["summary"].endswith("installed plugin") and kinds["provider-independence"]["severity"] == "ok"
    assert "plugins" in kinds["product"]["summary"], "the installed plugin provides the rules and skills"


# --- 5. workspace state and portability ---------------------------------------------------------

def test_runtime_state_ignores_itself_and_memory_stays_per_workspace(tmp_path: Path):
    one = _repo(tmp_path / "one", {"a.py": "x = 1\n"})
    two = _repo(tmp_path / "two", {"b.py": "y = 2\n"})
    ensure_index(load_config(one))
    assert (one / ".lord" / ".gitignore").read_text(encoding="utf-8").strip().endswith("*")
    assert _git(one, "status", "--porcelain") == "", "LORD state never shows up as a change in the target repository"
    store = Store(one).load()
    store.add("fact", "one's fact", "evidenced", evidence=["a.py:1"])
    store.save()
    assert Store(two).load().items == {} and len(Store(one).load().items) == 1


def test_non_python_workspace_is_gated_verified_and_briefed(pricing: Path):
    new_js = {"TargetFile": "src/discount.js", "CodeContent": "function discount(p) {\n  return p * 0.9;\n}\nmodule.exports = { discount };\n"}
    session.clear_task(pricing)
    (pricing / ".lord" / "session" / "activity.jsonl").unlink()
    denied = hooks.handle("pre-tool", _payload("write_to_file", new_js, pricing))
    assert denied["decision"] == "deny" and "discount.js" in denied["reason"], "the gate is language-agnostic"
    config = load_config(pricing)
    names = verify(config, ensure_index(config)).meta["steps"]
    assert names == ["npm test"], "steps come from the project's manifests, not from a Python assumption"
    assert matching_skills(pricing, "reuse an existing helper before creating one", 3), "skills come from the plugin, not from the workspace"
