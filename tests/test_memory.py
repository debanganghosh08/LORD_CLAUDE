"""Phase 7 tests: memory schema and trust model, supersession and conflicts,
deterministic retrieval, durable vs runtime separation, session handoff,
context assembly and the CLI surface."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from lord.config import load_config
from lord.context import assemble, matching_skills
from lord.index import ensure_index
from lord.memory import HANDOFF_FILE, MEMORY_FILE, Store, clear_handoff, handoff_report, load_handoff, validate_item, write_handoff
from lord.report import CONFIRMED, INFERRED, UNKNOWN

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "tests" / "fixtures" / "sample_repo"
TODAY = "2026-09-20"


def _valid(**over) -> dict:
    base = {"id": "M-0001", "category": "fact", "statement": "validate_email is the only email validator", "status": "confirmed",
            "created": TODAY, "updated": TODAY, "evidence": ["pkg/validators.py:8"], "paths": ["pkg/validators.py"], "symbols": ["validate_email"], "tags": ["email"]}
    base.update(over)
    return base


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    target = tmp_path / "sample_repo"
    shutil.copytree(SAMPLE, target)
    return target


@pytest.fixture
def store(repo: Path) -> Store:
    s = Store(repo).load()
    s.add("fact", "validate_email is the single email validator", "confirmed", evidence=["pkg/validators.py:8"], paths=["pkg/validators.py"], symbols=["validate_email"], tags=["email"], key="email.validator", today="2026-09-01")
    s.add("trap", "normalize_email lower-cases before validation; callers must not re-strip", "evidenced", evidence=["pkg/utils/strings.py:4"], paths=["pkg/utils"], symbols=["normalize_email"], tags=["email"], today="2026-09-10")
    s.add("convention", "services live in pkg/ and import validators, never the reverse", "inferred", paths=["pkg"], tags=["layering"], today="2026-09-05")
    s.add("verification", "python -m pytest runs the suite in under 5 seconds", "confirmed", evidence=["tests/"], tags=["tests"], today="2026-09-15")
    s.add("unresolved", "web/app.js imports React but no package.json lists it", "unresolved", paths=["web/app.js"], tags=["deps"], today="2026-09-18")
    s.add("discovery", "the rust module mentions validate_email but is not analysed", "temporary", expires="2026-09-25", paths=["native/main.rs"], today="2026-09-19")
    s.save()
    return Store(repo).load()


# --- schema and trust ---------------------------------------------------------------

def test_valid_item_passes_and_each_rule_is_enforced():
    assert validate_item(_valid()) == []
    assert any("M-0001" in e for e in validate_item(_valid(id="7")))
    assert any("category" in e for e in validate_item(_valid(category="opinion")))
    assert any("status" in e for e in validate_item(_valid(status="maybe")))
    assert any("requires at least one evidence" in e for e in validate_item(_valid(evidence=[])))
    assert any("requires at least one evidence" in e for e in validate_item(_valid(status="evidenced", evidence=[])))
    assert validate_item(_valid(status="inferred", evidence=[])) == [], "inferred items may lack evidence but are labelled"
    assert any("expires" in e for e in validate_item(_valid(status="temporary")))
    assert any("superseded_by" in e for e in validate_item(_valid(status="superseded")))
    assert any("300" in e for e in validate_item(_valid(statement="x" * 301)))
    assert any("single line" in e for e in validate_item(_valid(statement="a\nb")))
    assert any("YYYY-MM-DD" in e for e in validate_item(_valid(created="yesterday")))
    assert any("evidence must be" in e for e in validate_item(_valid(evidence=[""])))


def test_invalid_lines_are_reported_not_loaded(repo: Path):
    path = repo / MEMORY_FILE
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(_valid()) + "\n{not json}\n" + json.dumps(_valid(id="M-0002", status="confirmed", evidence=[])) + "\n", encoding="utf-8")
    store = Store(repo).load()
    assert list(store.items) == ["M-0001"]
    assert len(store.load_errors) == 2 and "invalid JSON" in store.load_errors[0] and "M-0002" in store.load_errors[1]
    check = store.check()
    assert [f.kind for f in check.findings if f.kind == "invalid-item"] == ["invalid-item", "invalid-item"] and check.has_errors


def test_store_rejects_bad_writes(store: Store):
    with pytest.raises(ValueError, match="evidence"):
        store.add("fact", "unsupported claim", "confirmed")
    with pytest.raises(ValueError, match="category"):
        store.add("rumour", "x", "inferred")
    with pytest.raises(ValueError, match="unknown item"):
        store.add("fact", "x", "inferred", supersedes="M-9999")


def test_save_is_sorted_one_line_per_item_lf(store: Store):
    text = (store.root / MEMORY_FILE).read_bytes()
    assert b"\r" not in text
    ids = [json.loads(l)["id"] for l in text.decode().splitlines()]
    assert ids == sorted(ids) == ["M-0001", "M-0002", "M-0003", "M-0004", "M-0005", "M-0006"]
    assert all(len(l.splitlines()) == 1 for l in text.decode().splitlines())


# --- supersession, conflicts, staleness -------------------------------------------------

def test_supersede_keeps_history_and_hides_old_by_default(store: Store):
    new = store.add("fact", "validate_email and check_email both validate emails; validate_email is canonical", "evidenced", evidence=["app/legacy/checks.py:8"], supersedes="M-0001", today=TODAY)
    old = store.items["M-0001"]
    assert old.status == "superseded" and old.superseded_by == new.id and new.supersedes == "M-0001" and new.key == "email.validator"
    assert new.symbols == ["validate_email"] and new.paths == ["pkg/validators.py"] and new.tags == ["email"], "successor inherits the subject"
    store.save()
    reloaded = Store(store.root).load()
    shown = [f.data["id"] for f in reloaded.query(symbol="validate_email").findings if f.kind != "memory"]
    assert new.id in shown and "M-0001" not in shown
    everything = [f.data["id"] for f in reloaded.query(symbol="validate_email", include_all=True).findings if f.kind != "memory"]
    assert "M-0001" in everything
    with pytest.raises(ValueError, match="already superseded"):
        store.add("fact", "again", "inferred", supersedes="M-0001")
    with pytest.raises(ValueError, match="superseded"):
        store.update("M-0001", statement="edit history")


def test_conflicting_current_items_on_one_key_are_reported(store: Store):
    store.add("fact", "check_email is the canonical validator", "evidenced", evidence=["app/legacy/checks.py"], key="email.validator", today=TODAY)
    check = store.check()
    conflict = next(f for f in check.findings if f.kind == "conflict")
    assert "email.validator" in conflict.summary and conflict.severity == "warn" and check.meta["conflicts"] == ["email.validator"]
    assert not any(f.kind == "conflict" for f in Store(store.root).load().check().findings), "unsaved conflict must not leak; saved store had none"


def test_temporary_items_expire_and_cannot_pose_as_current(store: Store):
    assert "M-0006" in [f.data["id"] for f in store.query(path="native/main.rs", today="2026-09-24").findings if f.kind != "memory"]
    assert store.query(path="native/main.rs", today="2026-09-26").findings[0].kind == "memory"
    expired = next(f for f in store.check(today="2026-09-26").findings if f.kind == "expired")
    assert "M-0006" in expired.summary
    assert store.query(path="native/main.rs", include_all=True, today="2026-09-26").findings[0].data["id"] == "M-0006"


def test_status_maps_to_confidence_and_weak_facts_are_flagged(store: Store):
    by_id = {f.data["id"]: f for f in store.query(include_all=True, limit=50).findings if f.kind != "memory"}
    assert by_id["M-0001"].confidence == CONFIRMED and by_id["M-0002"].confidence == INFERRED and by_id["M-0003"].confidence == INFERRED and by_id["M-0005"].confidence == UNKNOWN
    assert any(f.kind == "weak-fact" and "M-0003" in f.summary for f in store.check().findings)
    assert any(f.kind == "open" and "M-0005" in " ".join(f.evidence) for f in store.check().findings)


def test_update_resolves_with_evidence(store: Store):
    item = store.update("M-0005", status="confirmed", evidence=["package.json:12 lists react"], today=TODAY)
    assert item.status == "confirmed" and item.updated == TODAY and item.evidence == ["package.json:12 lists react"]
    with pytest.raises(ValueError, match="evidence"):
        store.update("M-0003", status="confirmed")


# --- retrieval ------------------------------------------------------------------------------

def test_retrieval_ranking_symbol_then_path_then_text_is_deterministic(store: Store):
    ids = [f.data["id"] for f in store.query(symbol="validate_email", text="email validator").findings if f.kind != "memory"]
    assert ids[0] == "M-0001", ids
    ids = [f.data["id"] for f in store.query(path="pkg/utils/strings.py").findings if f.kind != "memory"]
    assert ids == ["M-0002", "M-0003"], "directory-level items apply to files beneath them; exact/deeper path first"
    ids = [f.data["id"] for f in store.query(text="tests suite").findings if f.kind != "memory"]
    assert ids == ["M-0004"]
    assert [f.data["id"] for f in store.query(category="trap").findings] == ["M-0002"]
    assert [f.data["id"] for f in store.query(tag="email").findings] == ["M-0002", "M-0001"], "ties broken by most recently updated"
    assert [f.data["id"] for f in store.query(status="unresolved").findings] == ["M-0005"]
    first = store.query(text="email", limit=5).to_json()
    assert first == Store(store.root).load().query(text="email", limit=5).to_json(), "same store, same order"


def test_query_without_criteria_lists_current_items_newest_first(store: Store):
    ids = [f.data["id"] for f in store.query(limit=50).findings]
    assert ids == ["M-0006", "M-0005", "M-0004", "M-0002", "M-0003", "M-0001"]


def test_memory_matched_terms_are_explained(store: Store):
    hit = store.query(text="lower-cases callers").findings[0]
    assert hit.data["id"] == "M-0002" and any(e.startswith("matched: terms") for e in hit.evidence)


# --- durable vs runtime ------------------------------------------------------------------

def test_memory_is_versioned_not_runtime_state(store: Store):
    assert (store.root / "docs" / "state" / "memory.jsonl").is_file()
    assert not (store.root / ".lord" / "session").exists() or not list((store.root / ".lord" / "session").glob("*.jsonl"))
    assert MEMORY_FILE.parts[0] == "docs" and HANDOFF_FILE.parts[0] == "docs"
    assert subprocess.run(["git", "check-ignore", "-q", "docs/state/memory.jsonl"], cwd=ROOT).returncode == 1, "memory must be tracked"
    assert subprocess.run(["git", "check-ignore", "-q", ".lord/session/activity.jsonl"], cwd=ROOT).returncode == 0, "session state must be ignored"


# --- handoff ---------------------------------------------------------------------------------

def test_handoff_roundtrip_merge_and_clear(repo: Path):
    assert load_handoff(repo) == {} and handoff_report(repo).findings[0].summary == "no unfinished work recorded"
    write_handoff(repo, {"doing": "add email normalisation", "done": ["read validators"], "remaining": ["write test"], "next": ["run pytest"]}, today=TODAY)
    write_handoff(repo, {"done": ["read validators", "edit strings.py"], "discovered": ["normalize_email strips"], "verification": {"verdict": "not verified", "outstanding": ["pytest not executed"]}}, today=TODAY)
    data = load_handoff(repo)
    assert data["done"] == ["read validators", "edit strings.py"] and data["remaining"] == ["write test"] and data["updated"] == TODAY
    report = handoff_report(repo)
    kinds = [f.kind for f in report.findings]
    assert kinds[:2] == ["doing", "done"] and "verification" in kinds
    assert next(f for f in report.findings if f.kind == "verification").severity == "warn"
    write_handoff(repo, {"doing": "something else"}, replace=True, today=TODAY)
    assert "done" not in load_handoff(repo)
    assert clear_handoff(repo) and not clear_handoff(repo) and load_handoff(repo) == {}


def test_handoff_file_is_compact_json_with_lf(repo: Path):
    write_handoff(repo, {"doing": "x", "remaining": ["y"]}, today=TODAY)
    raw = (repo / HANDOFF_FILE).read_bytes()
    assert b"\r" not in raw and json.loads(raw)["doing"] == "x" and len(raw) < 400


# --- context ----------------------------------------------------------------------------------

def test_context_assembles_capped_sections(store: Store):
    repo = store.root
    write_handoff(repo, {"doing": "tighten email validation", "remaining": ["add length test"]}, today=TODAY)
    config = load_config(repo)
    report = assemble(config, ensure_index(config), "validate_email", intent="reject addresses over 254 characters")
    kinds = [f.kind for f in report.findings]
    assert kinds[0] == "handoff" and "tighten email validation" in report.findings[0].summary
    assert report.findings[1].kind == "fact" and report.findings[1].data["id"] == "M-0001"
    assert "definition" in kinds and kinds[-1] == "next"
    sections = report.meta["sections"]
    assert sections["handoff"] == 1 and 1 <= sections["memory"] <= 6 and sections["brief"] <= 18
    assert sections["rules"] == 0 and "rules" not in kinds, "the fixture workspace ships no rules; sections reflect the analysed workspace"
    from lord.context import always_on_rules

    assert always_on_rules(ROOT) == ["lord-operating-contract"]
    assert report.meta["reuse_decision"] in ("reuse", "extend", "refactor-or-create", "create")
    assert len(report.findings) <= 30


def test_context_for_a_file_uses_path_memory(store: Store):
    config = load_config(store.root)
    report = assemble(config, ensure_index(config), "pkg/utils/strings.py", intent="")
    ids = [f.data.get("id") for f in report.findings if f.kind in ("trap", "convention")]
    assert ids[:2] == ["M-0002", "M-0003"]


def test_matching_skills_by_intent():
    matches = matching_skills(ROOT, "before creating a helper, check reuse and duplicates", 3)
    assert matches and matches[0][0] == "lord-reuse-audit"
    assert matching_skills(ROOT, "", 3) and all(o == 0 for _, _, o in matching_skills(ROOT, "", 3))


# --- cli ----------------------------------------------------------------------------------------

def test_cli_memory_and_handoff(repo: Path):
    def run(*args: str, ok: bool = True) -> dict:
        completed = subprocess.run([sys.executable, "-m", "lord", "--root", str(repo), *args, "--json"], cwd=ROOT, capture_output=True, text=True)
        assert (completed.returncode == 0) is ok, completed.stdout + completed.stderr
        return json.loads(completed.stdout)

    added = run("memory", "add", "--category", "decision", "--statement", "constants carry values for duplicate detection", "--evidence", "docs/decisions/0001-python-stdlib-core.md", "--paths", "lord/extractors", "--tag", "index")
    assert added["findings"][0]["data"]["id"] == "M-0001"
    rejected = run("memory", "add", "--category", "fact", "--statement", "no evidence here", "--status", "confirmed", ok=False)
    assert "rejected" in rejected["findings"][0]["summary"]
    assert run("memory", "query", "--path", "lord/extractors/python_ast.py")["findings"][0]["data"]["id"] == "M-0001"
    sup = run("memory", "supersede", "M-0001", "--statement", "constants carry values; JS symbols carry end lines", "--evidence", "lord/extractors/js_ts.py")
    assert sup["findings"][0]["data"]["supersedes"] == "M-0001"
    assert run("memory", "check")["meta"]["conflicts"] == []
    assert run("memory", "list")["meta"]["matched"] == 2
    ho = run("handoff", "write", "--doing", "phase 7", "--remaining", "report", "--from-verify")
    assert ho["meta"]["present"] and any(f["kind"] == "verification" for f in ho["findings"])
    assert run("handoff", "show")["findings"][0]["summary"] == "phase 7"
    ctx = run("context", "validate_email", "--intent", "extend validation")
    assert ctx["findings"][0]["kind"] == "handoff" and ctx["meta"]["sections"]["memory"] >= 0
    assert run("handoff", "clear")["findings"][0]["summary"] == "handoff cleared"
