"""Phase 4 tests: relationship graph, impact report and root-cause trace on
the sample fixture repository."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from lord.config import load_config
from lord.graph import build_graph, file_node, neighborhood, sym_node
from lord.impact import impact_report, resolve_target, trace_report
from lord.index import ensure_index
from lord.report import CONFIRMED, INFERRED, UNKNOWN

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "sample_repo"


@pytest.fixture(scope="module")
def repo(tmp_path_factory) -> Path:
    target = tmp_path_factory.mktemp("impact") / "sample_repo"
    shutil.copytree(FIXTURE, target)
    return target


@pytest.fixture(scope="module")
def index(repo: Path):
    return ensure_index(load_config(repo))


@pytest.fixture(scope="module")
def graph(index, repo: Path):
    return build_graph(index, repo)


def _edges(graph, node: str, direction: str, kind: str) -> set[tuple[str, str]]:
    edges = graph.outgoing(node, (kind,)) if direction == "out" else graph.incoming(node, (kind,))
    return {((e.dst if direction == "out" else e.src), e.confidence) for e in edges}


# --- graph --------------------------------------------------------------------------

def test_graph_import_and_define_edges(graph):
    users = file_node("pkg/users.py")
    assert _edges(graph, users, "out", "imports") == {(file_node("pkg/validators.py"), CONFIRMED), (file_node("pkg/utils/strings.py"), CONFIRMED)}
    assert (sym_node("pkg/users.py::UserService.create"), CONFIRMED) in _edges(graph, users, "out", "defines")
    assert _edges(graph, file_node("web/app.js"), "out", "imports") == {(file_node("web/lib/helper.js"), INFERRED)}


def test_graph_resolves_calls_through_import_bindings_and_same_file(graph):
    create = sym_node("pkg/users.py::UserService.create")
    assert _edges(graph, create, "out", "calls") == {
        (sym_node("pkg/validators.py::validate_email"), CONFIRMED),
        (sym_node("pkg/utils/strings.py::normalize_email"), CONFIRMED),
    }
    # self.create() inside AdminService.promote resolves by name within the file
    promote = sym_node("pkg/users.py::AdminService.promote")
    assert (create, CONFIRMED) in _edges(graph, promote, "out", "calls")
    # JS alias binding: h -> helper
    assert _edges(graph, sym_node("web/app.js::render"), "out", "calls") == {(sym_node("web/lib/helper.js::helper"), INFERRED)}


def test_graph_resolution_is_receiver_aware(graph):
    execute = sym_node("pkg/jobs.py::execute")
    # `r.run(cmd)` through a module alias is confirmed; `subprocess.run(cmd)` must not link to pkg/runner.py::run
    assert _edges(graph, execute, "out", "calls") == {(sym_node("pkg/runner.py::run"), CONFIRMED)}
    # `service.create(...)` with an unknown receiver may only match methods named create (inferred)
    handler = sym_node("pkg/users.py::handler")
    assert (sym_node("pkg/users.py::UserService.create"), INFERRED) in _edges(graph, handler, "out", "calls")
    # `os.getcwd()` resolves to nothing: no edge, and no false link
    create = sym_node("pkg/users.py::UserService.create")
    assert not any("getcwd" in e.dst for e in graph.outgoing(create))


def test_graph_extends_tests_and_config_edges(graph):
    assert _edges(graph, sym_node("pkg/users.py::AdminService"), "out", "extends") == {(sym_node("pkg/users.py::UserService"), CONFIRMED)}
    test_file = file_node("tests/test_validators.py")
    assert (file_node("pkg/validators.py"), CONFIRMED) in _edges(graph, test_file, "out", "tests")
    assert (sym_node("pkg/validators.py::validate_email"), CONFIRMED) in _edges(graph, test_file, "out", "tests")
    config = file_node("config/settings.yaml")
    assert _edges(graph, config, "out", "configures") == {(sym_node("pkg/users.py::handler"), INFERRED), (sym_node("pkg/validators.py::validate_email"), INFERRED)}


def test_graph_does_not_link_excluded_or_generated_definitions(graph):
    assert not any("generated/" in n or "node_modules/" in n for n in graph.nodes)
    hood = neighborhood(graph, sym_node("pkg/validators.py::validate_email"))
    assert {e["from"] for e in hood["incoming"] if e["kind"] == "calls"} == {
        sym_node("pkg/users.py::UserService.create"),
        sym_node("tests/test_validators.py::test_validate_email_accepts_simple_address"),
    }


# --- impact ---------------------------------------------------------------------------

def test_resolve_target_symbol_qualified_and_file(index):
    assert resolve_target(index, "UserService.create")[1][0].qualname == "UserService.create"
    assert resolve_target(index, "pkg\\users.py") == ("file", "pkg/users.py")
    assert resolve_target(index, "nothing_here") is None


def test_impact_of_shared_function(index, repo: Path, graph):
    report = impact_report(index, repo, "validate_email", graph=graph)
    kinds = {}
    for f in report.findings:
        kinds.setdefault(f.kind, []).append(f)
    assert kinds["definition"][0].summary.startswith("pkg/validators.py:8 function validate_email")
    assert report.meta["direct_callers"] == ["pkg/users.py::UserService.create", "tests/test_validators.py::test_validate_email_accepts_simple_address"]
    assert report.meta["indirect_callers"] == ["pkg/users.py::AdminService.promote", "pkg/users.py::handler"]
    chain = next(f for f in kinds["indirect-reference"] if "promote" in f.summary).evidence[0]
    assert chain == "pkg/users.py::AdminService.promote <- pkg/users.py::UserService.create <- pkg/validators.py::validate_email"
    assert report.meta["dependents"] == ["pkg/users.py", "tests/test_validators.py"]
    assert report.meta["tests"] == ["tests/test_validators.py"] and report.meta["config"] == ["config/settings.yaml"]
    assert report.meta["directories"] == ["pkg", "tests"]
    consequences = [f.summary for f in kinds["consequence"]]
    assert any("1 direct caller/reference site(s) in 2 file(s)" in s for s in consequences)
    assert any("test file(s) exercise it" in s for s in consequences)
    assert any("configuration file(s) name it" in s for s in consequences)
    assert any("unsupported languages" in s for s in consequences)
    assert any(f.kind == "reuse-candidate" and "normalize_email" in f.summary for f in report.findings)
    assert report.meta["overall_confidence"] == CONFIRMED


def test_impact_of_class_reports_subtypes_and_untested_warning(index, repo: Path, graph):
    report = impact_report(index, repo, "UserService", graph=graph)
    related = [f.summary for f in report.findings if f.kind == "related-type"]
    assert any("AdminService extends" in s and "inherits behaviour" in s for s in related)
    consequences = [f for f in report.findings if f.kind == "consequence"]
    assert any("subtype(s) inherit" in f.summary for f in consequences)
    assert any("no test file references it" in f.summary and f.severity == "warn" for f in consequences)


def test_impact_of_file_lists_dependents_with_depth(index, repo: Path, graph):
    report = impact_report(index, repo, "pkg/utils/strings.py", depth=3, graph=graph)
    dependents = {f.summary for f in report.findings if f.kind == "dependent"}
    assert any(s.startswith("pkg/users.py depends on it (depth 1)") for s in dependents)
    assert report.meta["dependents"] == ["pkg/users.py"]


def test_impact_unknown_target_is_explicit(index, repo: Path, graph):
    report = impact_report(index, repo, "ghost_symbol", graph=graph)
    assert report.findings[0].kind == "target" and report.findings[0].confidence == UNKNOWN


# --- trace ------------------------------------------------------------------------------

def test_trace_lists_candidate_causes_downstream_and_upstream(index, repo: Path, graph):
    report = trace_report(index, repo, "UserService.create", observed="bad email rejected although valid", graph=graph)
    assert report.findings[0].kind == "observed-symptom" and "bad email rejected" in report.findings[0].summary
    causes = report.meta["candidate_causes"]
    assert causes[:2] == ["pkg/utils/strings.py::normalize_email", "pkg/validators.py::validate_email"]
    assert "pkg/validators.py::EMAIL_RE" in causes and "pkg/validators.py::MAX_EMAIL_LENGTH" in causes  # depth 2 via references
    email_re = next(f for f in report.findings if f.kind == "candidate-cause" and "EMAIL_RE" in f.summary)
    assert email_re.evidence[0] == "pkg/users.py::UserService.create -> pkg/validators.py::validate_email -> pkg/validators.py::EMAIL_RE"
    assert report.meta["upstream"] == ["pkg/users.py::AdminService.promote", "pkg/users.py::handler"]
    missing = next(f for f in report.findings if f.kind == "missing-evidence")
    assert missing.confidence == UNKNOWN and any("unsupported" in e for e in missing.evidence)
    nxt = next(f for f in report.findings if f.kind == "next-investigation")
    assert "normalize_email" in nxt.evidence[0] and "CONFIRMED only after reading" in nxt.recommendation


def test_trace_requires_symbol(index, repo: Path, graph):
    assert trace_report(index, repo, "pkg/users.py", graph=graph).findings[0].confidence == UNKNOWN


# --- cli ----------------------------------------------------------------------------------

def test_cli_impact_trace_graph_json(repo: Path):
    def run(*args: str) -> dict:
        completed = subprocess.run([sys.executable, "-m", "lord", "--root", str(repo), *args, "--json"], cwd=ROOT, capture_output=True, text=True)
        assert completed.returncode == 0, completed.stderr
        return json.loads(completed.stdout)

    assert run("impact", "validate_email")["meta"]["tests"] == ["tests/test_validators.py"]
    causes = run("trace", "handler", "--depth", "2")["meta"]["candidate_causes"]
    assert causes[0] == "pkg/users.py::UserService.create", causes  # callables rank before the class constructor
    graph = run("graph", "pkg/validators.py")
    assert graph["meta"]["edges_total"] > 10 and graph["findings"][0]["data"]["incoming"]
