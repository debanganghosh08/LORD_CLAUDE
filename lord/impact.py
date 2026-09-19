"""Impact analysis and root-cause tracing over the relationship graph.

`impact_report` answers "what happens if we change this?" by walking the
conceptual flow TARGET -> DEFINITION -> DIRECT REFERENCES -> CALLERS ->
CALLEES -> DEPENDENCIES -> DEPENDENTS -> RELATED TYPES -> TESTS ->
CONFIGURATION -> ARCHITECTURAL BOUNDARY -> POTENTIAL CONSEQUENCES.

`trace_report` answers "where could the actual cause be?" with upstream
(who reaches the symptom) and downstream (what the symptom depends on)
chains and a root-cause worksheet. LORD only ever labels a location as
OBSERVED SYMPTOM, CANDIDATE CAUSE or UNKNOWN; "confirmed root cause" is a
claim the model may make only after reading the source the chains point at.
"""

from __future__ import annotations

from collections import deque
from pathlib import Path

from lord.graph import Edge, Graph, build_graph, file_node, node_file, node_label, sym_node
from lord.index import Index
from lord.query import related
from lord.report import CONFIRMED, INFERRED, INFO, OK, UNKNOWN, WARN, Finding, Report
from lord.reuse import BUILTIN_NAMES
from lord.symbols import Symbol

UPSTREAM_KINDS = ("calls", "references", "extends", "implements")
DOWNSTREAM_KINDS = ("calls", "references", "extends", "implements")
CONF_ORDER = {CONFIRMED: 0, INFERRED: 1, UNKNOWN: 2}
KIND_RANK = {"function": 0, "method": 0, "route": 0, "class": 1, "interface": 1, "type": 1, "enum": 1, "constant": 2, "variable": 2}


def _weakest(*confidences: str) -> str:
    return max(confidences, key=lambda c: CONF_ORDER[c]) if confidences else UNKNOWN


def resolve_target(index: Index, target: str) -> tuple[str, list[Symbol]] | tuple[str, str] | None:
    """A file path in the index, or the symbols matching a (qualified) name."""
    normalized = target.replace("\\", "/").removeprefix("./")
    if normalized in index.entries:
        return "file", normalized
    symbols = index.symbols_named(target)
    if not symbols:
        symbols = [s for s in index.symbols() if s.name.lower() == target.lower()]
    return ("symbol", symbols) if symbols else None


def _edge_line(e: Edge, other: str) -> str:
    return f"{node_label(other)} [{e.kind}, {e.confidence}, line {e.line}]"


def _walk(graph: Graph, start: str, kinds: tuple[str, ...], depth: int, upstream: bool) -> dict[str, tuple[int, list[str], str]]:
    """BFS: node -> (depth, chain of labels from start, weakest confidence on the chain)."""
    found: dict[str, tuple[int, list[str], str]] = {}
    queue = deque([(start, 0, [node_label(start)], CONFIRMED)])
    while queue:
        node, d, chain, conf = queue.popleft()
        if d >= depth:
            continue
        edges = graph.incoming(node, kinds) if upstream else graph.outgoing(node, kinds)
        for e in edges:
            nxt = e.src if upstream else e.dst
            if nxt == start or nxt in found:
                continue
            new_conf = _weakest(conf, e.confidence)
            found[nxt] = (d + 1, chain + [node_label(nxt)], new_conf)
            queue.append((nxt, d + 1, chain + [node_label(nxt)], new_conf))
    return found


def _file_dependents(graph: Graph, path: str, depth: int) -> dict[str, tuple[int, list[str], str]]:
    return _walk(graph, file_node(path), ("imports",), depth, upstream=True)


def _top_dir(path: str) -> str:
    return path.split("/")[0] if "/" in path else "."


def impact_report(index: Index, root: Path, target: str, depth: int = 2, graph: Graph | None = None) -> Report:
    report = Report(title=f"impact: {target}", meta={"root": index.root, "depth": depth})
    resolved = resolve_target(index, target)
    if resolved is None:
        report.add(Finding(kind="target", summary=f"{target!r} is not an indexed file or symbol", severity=WARN, confidence=UNKNOWN,
                           recommendation="check the name with `lord def` or `lord related`; the target may live in an unsupported language"))
        return report
    graph = graph or build_graph(index, root)

    if resolved[0] == "file":
        path = resolved[1]
        nodes = [file_node(path)]
        files = {path}
        report.add(Finding(kind="definition", summary=f"file {path} defines {len(index.symbols_in(path))} symbol(s)", severity=OK, confidence=CONFIRMED,
                           evidence=[f"{s.kind} {s.qualname}" for s in index.symbols_in(path)[:15]]))
        symbols: list[Symbol] = []
    else:
        symbols = resolved[1]
        nodes = [sym_node(s) for s in symbols]
        files = {s.file for s in symbols}
        for s in symbols:
            report.add(Finding(kind="definition", summary=f"{s.file}:{s.line} {s.kind} {s.qualname}{(' ' + s.signature) if s.signature else ''}", severity=OK,
                               confidence=s.confidence, evidence=[s.doc] if s.doc else []))
        if len(symbols) > 1:
            report.add(Finding(kind="ambiguity", summary=f"{len(symbols)} definitions share this name; impact below covers all of them", severity=INFO, confidence=CONFIRMED,
                               recommendation="qualify the name (Class.method) or pass the file path"))
        path = ""

    # direct callers / references
    direct: dict[str, list[Edge]] = {}
    for node in nodes:
        for e in graph.incoming(node, UPSTREAM_KINDS):
            direct.setdefault(e.src, []).append(e)
    caller_files = {node_file(n) for n in direct}
    for src, edges in sorted(direct.items()):
        kinds = sorted({e.kind for e in edges})
        conf = _weakest(*(e.confidence for e in edges))
        rec = index.inventory.get(node_file(src))
        tag = " [test]" if rec and rec.kind == "test" else ""
        report.add(Finding(kind="direct-reference", summary=f"{node_label(src)} {'/'.join(kinds)} it{tag}", severity=OK, confidence=conf,
                           evidence=[f"{node_file(src)}:{e.line} {e.kind}" for e in edges[:8]]))

    # indirect callers (depth >= 2)
    indirect: dict[str, tuple[int, list[str], str]] = {}
    for node in nodes:
        for n, (d, chain, conf) in _walk(graph, node, UPSTREAM_KINDS, depth, upstream=True).items():
            if d >= 2 and n not in direct and n not in indirect:
                indirect[n] = (d, chain, conf)
    for n, (d, chain, conf) in sorted(indirect.items(), key=lambda kv: (kv[1][0], kv[0])):
        report.add(Finding(kind="indirect-reference", summary=f"{node_label(n)} reaches it at depth {d}", severity=INFO, confidence=conf,
                           evidence=[" <- ".join(reversed(chain))]))

    # callees / dependencies (what the target relies on)
    callees: dict[str, list[Edge]] = {}
    for node in nodes:
        for e in graph.outgoing(node, DOWNSTREAM_KINDS):
            callees.setdefault(e.dst, []).append(e)
    for dst, edges in sorted(callees.items()):
        kinds = sorted({e.kind for e in edges})
        report.add(Finding(kind="callee", summary=f"it {'/'.join(kinds)} {node_label(dst)}", severity=OK, confidence=_weakest(*(e.confidence for e in edges)),
                           evidence=[f"line {e.line}" for e in edges[:5]]))

    # file-level dependencies and dependents
    for f in sorted(files):
        for e in graph.outgoing(file_node(f), ("imports",)):
            report.add(Finding(kind="dependency", summary=f"{f} imports {node_label(e.dst)} ({e.note})", severity=OK, confidence=e.confidence))
    dependents: dict[str, tuple[int, list[str], str]] = {}
    for f in sorted(files):
        for n, info in _file_dependents(graph, f, depth).items():
            if n not in dependents or info[0] < dependents[n][0]:
                dependents[n] = info
    for n, (d, chain, conf) in sorted(dependents.items(), key=lambda kv: (kv[1][0], kv[0])):
        rec = index.inventory.get(node_label(n))
        tag = " [test]" if rec and rec.kind == "test" else ""
        report.add(Finding(kind="dependent", summary=f"{node_label(n)} depends on it (depth {d}){tag}", severity=OK if d == 1 else INFO, confidence=conf,
                           evidence=[" <- ".join(reversed(chain))] if d > 1 else []))

    # related types
    for node in nodes:
        for e in graph.outgoing(node, ("extends", "implements")):
            report.add(Finding(kind="related-type", summary=f"{node_label(node)} {e.kind} {node_label(e.dst)}", severity=OK, confidence=e.confidence))
        for e in graph.incoming(node, ("extends", "implements")):
            report.add(Finding(kind="related-type", summary=f"{node_label(e.src)} {e.kind} {node_label(node)} (subtype inherits behaviour)", severity=OK, confidence=e.confidence))

    # tests
    test_edges: dict[str, list[Edge]] = {}
    for node in nodes + [file_node(f) for f in files]:
        for e in graph.incoming(node, ("tests",)):
            test_edges.setdefault(node_file(e.src), []).append(e)
    for tf, edges in sorted(test_edges.items()):
        report.add(Finding(kind="test", summary=f"{tf} exercises it", severity=OK, confidence=_weakest(*(e.confidence for e in edges)),
                           evidence=[f"{tf}:{e.line}" for e in edges[:5]]))

    # configuration
    config_edges: dict[str, list[Edge]] = {}
    for node in nodes + [file_node(f) for f in files]:
        for e in graph.incoming(node, ("configures",)):
            config_edges.setdefault(node_file(e.src), []).append(e)
    for cf, edges in sorted(config_edges.items()):
        report.add(Finding(kind="config", summary=f"{cf} mentions it ({', '.join(sorted({e.note for e in edges}))})", severity=INFO, confidence=INFERRED,
                           evidence=[f"{cf}:{e.line}" for e in edges[:5]], consequence="a rename or signature change may need a configuration update"))

    # architectural boundary
    affected_files = set(files) | caller_files | {node_label(n) for n in dependents} | {node_file(n) for n in indirect}
    dirs = sorted({_top_dir(f) for f in affected_files})
    roots = sorted({r for r in index.inventory.project_roots if any(f.startswith(r + "/") or r == "." for f in affected_files)})
    report.add(Finding(kind="boundary", summary=f"affects {len(affected_files)} file(s) across {len(dirs)} top-level director{'y' if len(dirs) == 1 else 'ies'}: {', '.join(dirs)}",
                       severity=OK if len(dirs) <= 1 else INFO, confidence=INFERRED, evidence=[f"project roots: {', '.join(roots) or '.'}"]))

    # consequences
    consequences: list[Finding] = []
    n_direct = len([n for n in direct if not (index.inventory.get(node_file(n)) and index.inventory.get(node_file(n)).kind == "test")])
    if n_direct:
        conf = _weakest(*(e.confidence for edges in direct.values() for e in edges))
        consequences.append(Finding(kind="consequence", summary=f"a signature or behaviour change reaches {n_direct} direct caller/reference site(s) in {len(caller_files)} file(s)",
                                    severity=WARN, confidence=conf, evidence=sorted(node_label(n) for n in direct)[:10]))
    if indirect:
        consequences.append(Finding(kind="consequence", summary=f"{len(indirect)} indirect caller(s) up to depth {depth} inherit the change through the chain", severity=INFO,
                                    confidence=_weakest(*(v[2] for v in indirect.values()))))
    subtypes = [e for node in nodes for e in graph.incoming(node, ("extends", "implements"))]
    if subtypes:
        consequences.append(Finding(kind="consequence", summary=f"{len(subtypes)} subtype(s) inherit its behaviour: overridden methods and super() calls are affected", severity=WARN,
                                    confidence=_weakest(*(e.confidence for e in subtypes))))
    if test_edges:
        consequences.append(Finding(kind="consequence", summary=f"{len(test_edges)} test file(s) exercise it; run them first", severity=OK, confidence=INFERRED, evidence=sorted(test_edges)))
    else:
        consequences.append(Finding(kind="consequence", summary="no test file references it: a regression here would not be caught by existing tests", severity=WARN, confidence=INFERRED,
                                    recommendation="add or extend a test before changing behaviour"))
    if config_edges:
        consequences.append(Finding(kind="consequence", summary=f"{len(config_edges)} configuration file(s) name it; renames must update them", severity=INFO, confidence=INFERRED, evidence=sorted(config_edges)))
    if len(dirs) > 1:
        consequences.append(Finding(kind="consequence", summary=f"the change crosses {len(dirs)} top-level directories ({', '.join(dirs)})", severity=INFO, confidence=INFERRED))
    unsupported = index.unsupported_languages()
    if unsupported:
        consequences.append(Finding(kind="consequence", summary="callers in unsupported languages are invisible to this analysis: " + ", ".join(f"{k} ({v})" for k, v in sorted(unsupported.items())),
                                    severity=INFO, confidence=UNKNOWN, recommendation="search those files by name before concluding nothing else is affected"))
    report.extend(consequences)

    # reuse candidates near the target (per the impact-report contract)
    if symbols:
        rel = related(index, symbols[0].name, limit=4)
        for f in rel.findings:
            if f.kind == "candidate" and f.data.get("symbol", {}).get("qualname") not in {s.qualname for s in symbols}:
                report.add(Finding(kind="reuse-candidate", summary=f.summary, severity=INFO, confidence=INFERRED, evidence=f.evidence[:1]))

    all_conf = [f.confidence for f in report.findings if f.kind in ("direct-reference", "dependent", "callee", "test")]
    report.meta.update({
        "direct_callers": sorted(node_label(n) for n in direct), "indirect_callers": sorted(node_label(n) for n in indirect),
        "dependents": sorted(node_label(n) for n in dependents), "tests": sorted(test_edges), "config": sorted(config_edges),
        "directories": dirs, "overall_confidence": _weakest(*all_conf) if all_conf else INFERRED,
    })
    return report


def trace_report(index: Index, root: Path, target: str, depth: int = 3, observed: str = "", graph: Graph | None = None) -> Report:
    report = Report(title=f"trace: {target}", meta={"root": index.root, "depth": depth, "observed": observed})
    resolved = resolve_target(index, target)
    if resolved is None or resolved[0] == "file":
        report.add(Finding(kind="target", summary=f"{target!r} must be an indexed symbol name (use `lord impact` for files)", severity=WARN, confidence=UNKNOWN))
        return report
    graph = graph or build_graph(index, root)
    symbols = resolved[1]
    nodes = [sym_node(s) for s in symbols]

    report.add(Finding(kind="observed-symptom", summary=observed or f"behaviour observed at {', '.join(f'{s.file}:{s.line} {s.qualname}' for s in symbols)}", severity=INFO,
                       confidence=CONFIRMED, evidence=[f"{s.file}:{s.line} {s.qualname}" for s in symbols]))

    downstream: dict[str, tuple[int, list[str], str]] = {}
    upstream: dict[str, tuple[int, list[str], str]] = {}
    for node in nodes:
        for n, info in _walk(graph, node, DOWNSTREAM_KINDS, depth, upstream=False).items():
            if n not in downstream or info[0] < downstream[n][0]:
                downstream[n] = info
        for n, info in _walk(graph, node, UPSTREAM_KINDS, depth, upstream=True).items():
            if n not in upstream or info[0] < upstream[n][0]:
                upstream[n] = info

    target_files = {s.file for s in symbols}
    for n, (d, chain, conf) in sorted(downstream.items(), key=lambda kv: (kv[1][0], kv[0])):
        cross = node_file(n) not in target_files
        report.add(Finding(kind="candidate-cause", summary=f"{node_label(n)} (depth {d}{', other file' if cross else ''})", severity=INFO, confidence=conf,
                           evidence=[" -> ".join(chain)], consequence="a wrong value or side effect here would surface at the symptom"))
    for n, (d, chain, conf) in sorted(upstream.items(), key=lambda kv: (kv[1][0], kv[0])):
        report.add(Finding(kind="upstream", summary=f"{node_label(n)} reaches the symptom (depth {d})", severity=INFO, confidence=conf,
                           evidence=[" <- ".join(reversed(chain))], consequence="if inputs are wrong, the cause may be here rather than at the symptom"))

    unresolved: set[str] = set()
    for s in symbols:
        ex = index.extraction_for(s.file)
        if ex is None:
            continue
        resolved_names = {node_label(e.dst).rsplit("::", 1)[-1].rsplit(".", 1)[-1] for e in graph.outgoing(sym_node(s), ("calls",))}
        for c in ex.calls:
            if c.scope == s.qualname and c.name not in resolved_names and c.name not in BUILTIN_NAMES and c.receiver != "<expr>":
                unresolved.add(f"{c.receiver}.{c.name}" if c.receiver else c.name)
    unresolved = sorted(unresolved)
    missing: list[str] = []
    if unresolved:
        missing.append(f"calls not resolved to workspace symbols (external, dynamic or unsupported): {', '.join(unresolved[:12])}")
    unsupported = index.unsupported_languages()
    if unsupported:
        missing.append("files in unsupported languages are not traversed: " + ", ".join(f"{k} ({v})" for k, v in sorted(unsupported.items())))
    inferred_hops = sum(1 for v in list(downstream.values()) + list(upstream.values()) if v[2] != CONFIRMED)
    if inferred_hops:
        missing.append(f"{inferred_hops} chain(s) contain an inferred hop (name-based resolution); confirm by reading the source")
    report.add(Finding(kind="missing-evidence", summary="what this trace cannot establish", severity=INFO, confidence=UNKNOWN, evidence=missing or ["nothing structural is missing; behaviour must still be read from the source"]))

    # nearest first; callables before types before constants; other files before the symptom's own file
    kind_of = {sym_node(s): s.kind for s in index.symbols()}
    ranked = sorted(downstream.items(), key=lambda kv: (kv[1][0], KIND_RANK.get(kind_of.get(kv[0], ""), 3), 0 if node_file(kv[0]) not in target_files else 1, kv[0]))
    next_steps = [f"open {node_label(n)} ({node_file(n)}) and check the value it produces for the failing input" for n, _ in ranked[:3]]
    if upstream:
        first = sorted(upstream.items(), key=lambda kv: kv[1][0])[0][0]
        next_steps.append(f"check what {node_label(first)} passes in; if the input is already wrong, move the symptom there")
    report.add(Finding(kind="next-investigation", summary="recommended next investigation", severity=INFO, confidence=INFERRED,
                       evidence=next_steps or ["no callees or callers found in the index; read the symbol's own body"],
                       recommendation="label the cause CONFIRMED only after reading the source and reproducing the behaviour; otherwise keep it as a candidate"))
    report.meta.update({"candidate_causes": [node_label(n) for n, _ in ranked], "upstream": sorted(node_label(n) for n in upstream)})
    return report
