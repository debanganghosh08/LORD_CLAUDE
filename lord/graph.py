"""Relationship graph derived from the index.

Nodes are files (`file:<path>`) and symbols (`sym:<path>::<qualname>`).
Edges carry a kind, a confidence and the line that produced them:

    defines     file -> symbol
    imports     file -> file                 (resolved workspace imports)
    calls       symbol|file -> symbol
    references  symbol|file -> symbol        (non-call uses)
    extends     class -> class
    implements  class -> interface
    tests       test file -> file | symbol
    configures  config file -> symbol|file   (name mentions, inferred)

Name resolution order for calls/references/bases: explicit import binding in
the same file (confirmed for Python), same-file definition (confirmed), then
any same-named definition in another code file (inferred; ambiguity is kept
as several edges). The graph is rebuilt from the index on demand; it is not
a second source of truth.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from lord.index import Index
from lord.report import INFERRED
from lord.symbols import Symbol

EDGE_KINDS = ("defines", "imports", "calls", "references", "extends", "implements", "tests", "configures")
CONFIG_TOKEN_RE = re.compile(r"[A-Za-z_][\w.]*")
CAMEL_RE = re.compile(r"[a-z][A-Z]")


@dataclass(frozen=True)
class Edge:
    src: str
    dst: str
    kind: str
    confidence: str
    line: int = 0
    note: str = ""


def file_node(path: str) -> str:
    return f"file:{path}"


def sym_node(symbol: Symbol | str) -> str:
    return f"sym:{symbol.id if isinstance(symbol, Symbol) else symbol}"


def node_label(node: str) -> str:
    return node.split(":", 1)[1]


def node_file(node: str) -> str:
    label = node_label(node)
    return label.split("::", 1)[0]


class Graph:
    def __init__(self) -> None:
        self.out: dict[str, list[Edge]] = defaultdict(list)
        self.inc: dict[str, list[Edge]] = defaultdict(list)
        self.nodes: set[str] = set()
        self._seen: set[tuple[str, str, str, int]] = set()

    def add(self, edge: Edge) -> None:
        key = (edge.src, edge.dst, edge.kind, edge.line)
        if key in self._seen or edge.src == edge.dst:
            return
        self._seen.add(key)
        self.out[edge.src].append(edge)
        self.inc[edge.dst].append(edge)
        self.nodes.update((edge.src, edge.dst))

    def outgoing(self, node: str, kinds: Iterable[str] | None = None) -> list[Edge]:
        edges = self.out.get(node, [])
        return [e for e in edges if kinds is None or e.kind in kinds]

    def incoming(self, node: str, kinds: Iterable[str] | None = None) -> list[Edge]:
        edges = self.inc.get(node, [])
        return [e for e in edges if kinds is None or e.kind in kinds]

    def edges(self) -> Iterable[Edge]:
        for edges in self.out.values():
            yield from edges

    def __len__(self) -> int:
        return len(self._seen)


def _is_code(index: Index, path: str) -> bool:
    rec = index.inventory.get(path)
    return bool(rec) and rec.kind in ("source", "script", "test")


def build_graph(index: Index, root: Path) -> Graph:
    graph = Graph()
    by_file: dict[str, dict[str, list[Symbol]]] = defaultdict(lambda: defaultdict(list))
    by_name: dict[str, list[Symbol]] = defaultdict(list)
    by_name_methods: dict[str, list[Symbol]] = defaultdict(list)
    for s in index.symbols():
        by_file[s.file][s.name].append(s)
        if not s.parent:
            by_name[s.name].append(s)
        elif s.kind == "method":
            by_name_methods[s.name].append(s)

    for ex in index.extractions():
        if ex.error:
            continue
        fnode = file_node(ex.file)
        rec = index.inventory.get(ex.file)
        is_test = bool(rec) and rec.kind == "test"
        for s in ex.symbols:
            graph.add(Edge(fnode, sym_node(s), "defines", s.confidence, s.line))

        bindings: dict[str, list[Symbol]] = {}     # local name -> symbols it is bound to by import
        module_aliases: dict[str, str] = {}         # local name -> workspace file it refers to as a module
        for imp in ex.imports:
            if not imp.resolved:
                continue
            graph.add(Edge(fnode, file_node(imp.resolved), "imports", imp.confidence, imp.line, ", ".join(imp.names) or "(module)"))
            if is_test:
                graph.add(Edge(fnode, file_node(imp.resolved), "tests", imp.confidence, imp.line))
            if not imp.names:  # `import a.b [as c]`: the alias names the module
                for alias in imp.aliases:
                    module_aliases[alias] = imp.resolved
            for original, alias in zip(imp.names, imp.aliases):
                targets = [t for t in by_file[imp.resolved].get(original, []) if not t.parent]
                if targets:
                    bindings[alias] = targets
                elif imp.resolved.endswith("__init__.py"):
                    # `from pkg import submodule`
                    for candidate in (f"{imp.resolved[:-len('__init__.py')]}{original}.py", f"{imp.resolved[:-len('__init__.py')]}{original}/__init__.py"):
                        if candidate in index.entries:
                            module_aliases[alias] = candidate
                            break

        def resolve(name: str, receiver: str = "", scope: str = "") -> list[tuple[Symbol, str]]:
            """Receiver-aware resolution. Unknown receivers only match methods, so
            `subprocess.run()` never links to a module-level `run` elsewhere."""
            short = name.split(".")[-1]
            if receiver:
                head = receiver.split(".")[0]
                if head in module_aliases and receiver == head:
                    return [(t, ex.confidence) for t in by_file[module_aliases[head]].get(short, []) if not t.parent]
                if head in ("self", "cls", "this", "super"):
                    owner = scope.rsplit(".", 1)[0] if "." in scope else scope
                    # walk the same-file inheritance chain: own class, then its bases
                    chain, seen = [owner], set()
                    while chain:
                        cls = chain.pop(0)
                        if cls in seen:
                            continue
                        seen.add(cls)
                        own = [t for t in by_file[ex.file].get(short, []) if t.parent == cls]
                        if own:
                            return [(t, ex.confidence) for t in own]
                        chain.extend(b.base.split(".")[-1] for b in ex.bases if b.qualname == cls)
                    return [(t, INFERRED) for t in by_file[ex.file].get(short, []) if t.kind == "method"]
                if head in bindings and receiver == head:
                    # attribute on an imported class/object: its methods
                    owners = {b.qualname for b in bindings[head]}
                    return [(t, INFERRED) for b in bindings[head] for t in by_file[b.file].get(short, []) if t.parent in owners]
                return [(t, INFERRED) for t in by_name_methods.get(short, []) if _is_code(index, t.file)]
            if short in bindings and bindings[short]:
                return [(t, ex.confidence) for t in bindings[short]]
            local = [t for t in by_file[ex.file].get(short, []) if not t.parent]
            if local:
                return [(t, ex.confidence) for t in local]
            return [(t, INFERRED) for t in by_name.get(short, []) if _is_code(index, t.file) and t.file != ex.file]

        scope_nodes = {s.qualname: sym_node(s) for s in ex.symbols}

        def source_node(scope: str) -> str:
            return scope_nodes.get(scope, fnode)

        call_lines: set[tuple[str, str, int]] = set()
        for call in ex.calls:
            src = source_node(call.scope)
            for target, conf in resolve(call.name, call.receiver, call.scope):
                graph.add(Edge(src, sym_node(target), "calls", conf, call.line))
                call_lines.add((src, sym_node(target), call.line))
                if is_test:
                    graph.add(Edge(fnode, sym_node(target), "tests", conf, call.line))
        for ref in ex.references:
            src = source_node(ref.scope)
            for target, conf in resolve(ref.name, ref.receiver, ref.scope):
                dst = sym_node(target)
                if (src, dst, ref.line) in call_lines or dst == src:
                    continue
                graph.add(Edge(src, dst, "references", conf, ref.line))
                if is_test:
                    graph.add(Edge(fnode, dst, "tests", conf, ref.line))
        for base in ex.bases:
            src = scope_nodes.get(base.qualname, fnode)
            head, _, short = base.base.rpartition(".")
            for target, conf in resolve(short, head if head in module_aliases else "", base.qualname):
                graph.add(Edge(src, sym_node(target), base.relation, conf, base.line))

    _add_config_edges(index, root, graph, by_name)
    return graph


def _add_config_edges(index: Index, root: Path, graph: Graph, by_name: dict[str, list[Symbol]]) -> None:
    """Config/manifest files that mention a symbol by name (inferred)."""
    distinctive = {n for n in by_name if len(n) >= 4 and ("_" in n or CAMEL_RE.search(n) or len(n) >= 10)}
    for rec in index.inventory.files:
        if rec.kind not in ("config", "manifest") or not rec.is_text or rec.size > 512_000:
            continue
        try:
            text = (root / rec.path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for token in CONFIG_TOKEN_RE.findall(line):
                parts = token.split(".")
                name = parts[-1]
                candidates = by_name.get(name, [])
                if not candidates:
                    continue
                if len(parts) >= 2:
                    # dotted path: earlier parts must appear in the defining file's path
                    for s in candidates:
                        if all(p in s.file.split("/") or p in Path(s.file).stem for p in parts[:-1]):
                            graph.add(Edge(file_node(rec.path), sym_node(s), "configures", INFERRED, lineno, token))
                elif name in distinctive:
                    for s in candidates:
                        graph.add(Edge(file_node(rec.path), sym_node(s), "configures", INFERRED, lineno, token))


def neighborhood(graph: Graph, node: str) -> dict[str, list[dict]]:
    """Inspectable dump of one node's edges, grouped by direction and kind."""
    result: dict[str, list[dict]] = {"outgoing": [], "incoming": []}
    for e in graph.outgoing(node):
        result["outgoing"].append({"kind": e.kind, "to": e.dst, "confidence": e.confidence, "line": e.line, "note": e.note})
    for e in graph.incoming(node):
        result["incoming"].append({"kind": e.kind, "from": e.src, "confidence": e.confidence, "line": e.line, "note": e.note})
    return result
