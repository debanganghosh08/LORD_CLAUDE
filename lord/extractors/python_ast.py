"""Python extractor built on the standard-library `ast` module (CONFIRMED).

Discovers functions, methods, classes, module-level constants/variables,
route-decorated functions, imports (resolved to workspace files when the
module maps onto one), calls, name references and class bases.
"""

from __future__ import annotations

import ast
from pathlib import Path

from lord.report import CONFIRMED, INFERRED, UNKNOWN
from lord.symbols import Base, Extraction, Import, Ref, Symbol

ROUTE_DECORATORS = {"route", "get", "post", "put", "delete", "patch", "api_route", "websocket"}


def resolve_module(root: Path, rel: str, module: str, level: int) -> str | None:
    """Map a Python import onto a workspace file, or None if it is external."""
    file_dir = Path(rel).parent
    parts = module.split(".") if module else []

    if level > 0:
        base = file_dir
        for _ in range(level - 1):
            base = base.parent
        candidates = [base.joinpath(*parts)] if parts else [base]
    else:
        # Try the workspace root first, then every ancestor directory of the
        # importing file (covers src/ layouts and packages nested in subdirs).
        bases = [Path("")] + [p for p in reversed(file_dir.parents)] + [file_dir]
        seen: set[Path] = set()
        candidates = []
        for b in bases:
            if b in seen:
                continue
            seen.add(b)
            candidates.append(b.joinpath(*parts))

    for candidate in candidates:
        for target in (candidate.with_suffix(".py") if candidate.name else None, candidate / "__init__.py"):
            if target is None:
                continue
            if (root / target).is_file():
                return target.as_posix()
    return None


class _Visitor(ast.NodeVisitor):
    def __init__(self, root: Path, rel: str, source: str = "") -> None:
        self.root = root
        self.rel = rel
        self.source = source
        self.out = Extraction(file=rel, language="python", confidence=CONFIRMED)
        self.scope: list[str] = []

    # -- helpers ---------------------------------------------------------------
    def _qual(self, name: str) -> str:
        return ".".join([*self.scope, name])

    def _scope_name(self) -> str:
        return ".".join(self.scope)

    @staticmethod
    def _doc(node: ast.AST) -> str:
        doc = ast.get_docstring(node) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)) else None
        return doc.strip().splitlines()[0] if doc else ""

    @staticmethod
    def _dotted(node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            head = _Visitor._dotted(node.value)
            return f"{head}.{node.attr}" if head else node.attr
        if isinstance(node, ast.Call):
            return _Visitor._dotted(node.func)
        if isinstance(node, ast.Subscript):
            return _Visitor._dotted(node.value)
        return ""

    # -- definitions -----------------------------------------------------------
    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        kind = "method" if self.scope and self._is_class_scope else "function"
        signature = f"({', '.join(a.arg for a in node.args.args)})"
        for dec in node.decorator_list:
            dotted = self._dotted(dec)
            if dotted.split(".")[-1] in ROUTE_DECORATORS and isinstance(dec, ast.Call):
                kind = "route"
                path = next((a.value for a in dec.args if isinstance(a, ast.Constant) and isinstance(a.value, str)), "")
                signature = f"@{dotted} {path}".strip()
        self.out.symbols.append(
            Symbol(
                name=node.name, kind=kind, file=self.rel, line=node.lineno, qualname=self._qual(node.name),
                language="python", end_line=getattr(node, "end_lineno", None), parent=self._scope_name(),
                signature=signature, exported=not node.name.startswith("_"), doc=self._doc(node),
            )
        )
        self.scope.append(node.name)
        was_class = self._is_class_scope
        self._is_class_scope = False
        self.generic_visit(node)
        self._is_class_scope = was_class
        self.scope.pop()

    _is_class_scope = False

    visit_FunctionDef = _function
    visit_AsyncFunctionDef = _function

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        qual = self._qual(node.name)
        self.out.symbols.append(
            Symbol(
                name=node.name, kind="class", file=self.rel, line=node.lineno, qualname=qual, language="python",
                end_line=getattr(node, "end_lineno", None), parent=self._scope_name(),
                signature=f"({', '.join(self._dotted(b) for b in node.bases)})" if node.bases else "",
                exported=not node.name.startswith("_"), doc=self._doc(node),
            )
        )
        for base in node.bases:
            dotted = self._dotted(base)
            if dotted:
                self.out.bases.append(Base(qualname=qual, base=dotted, line=node.lineno))
        self.scope.append(node.name)
        was_class = self._is_class_scope
        self._is_class_scope = True
        self.generic_visit(node)
        self._is_class_scope = was_class
        self.scope.pop()

    def _assignment_targets(self, node: ast.AST, targets: list[ast.expr]) -> None:
        if self.scope:  # only module-level bindings are symbols
            return
        value_src = ""
        value = getattr(node, "value", None)
        if value is not None and self.source:
            segment = ast.get_source_segment(self.source, value) or ""
            value_src = " ".join(segment.split())[:80]
        for target in targets:
            names = [target] if isinstance(target, ast.Name) else [e for e in getattr(target, "elts", []) if isinstance(e, ast.Name)]
            for name_node in names:
                name = name_node.id
                if name == "__all__":
                    continue
                self.out.symbols.append(
                    Symbol(
                        name=name, kind="constant" if name.isupper() else "variable", file=self.rel,
                        line=node.lineno, qualname=name, language="python", exported=not name.startswith("_"),
                        signature=value_src,
                    )
                )

    def visit_Assign(self, node: ast.Assign) -> None:
        self._assignment_targets(node, node.targets)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._assignment_targets(node, [node.target])
        self.generic_visit(node)

    # -- imports ---------------------------------------------------------------
    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            resolved = resolve_module(self.root, self.rel, alias.name, 0)
            self.out.imports.append(
                Import(module=alias.name, names=[], aliases=[alias.asname or alias.name.split(".")[0]], line=node.lineno,
                       resolved=resolved, confidence=CONFIRMED if resolved else INFERRED)
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        resolved = resolve_module(self.root, self.rel, module, node.level)
        names = [a.name for a in node.names]
        aliases = [a.asname or a.name for a in node.names]
        self.out.imports.append(
            Import(module=("." * node.level) + module, names=names, aliases=aliases, line=node.lineno,
                   resolved=resolved, confidence=CONFIRMED if resolved else INFERRED, is_relative=node.level > 0)
        )

    # -- uses ------------------------------------------------------------------
    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name):
            self.out.calls.append(Ref(name=node.func.id, line=node.lineno, scope=self._scope_name()))
        elif isinstance(node.func, ast.Attribute):
            receiver = self._dotted(node.func.value) or "<expr>"
            self.out.calls.append(Ref(name=node.func.attr, line=node.lineno, scope=self._scope_name(), receiver=receiver))
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            self.out.references.append(Ref(name=node.id, line=node.lineno, scope=self._scope_name()))

    def visit_Attribute(self, node: ast.Attribute) -> None:
        receiver = self._dotted(node.value) or "<expr>"
        self.out.references.append(Ref(name=node.attr, line=node.lineno, scope=self._scope_name(), receiver=receiver))
        self.generic_visit(node)


def extract_python(root: Path, rel: str, source: str) -> Extraction:
    try:
        tree = ast.parse(source, filename=rel)
    except (SyntaxError, ValueError) as exc:
        lineno = getattr(exc, "lineno", None)
        return Extraction(file=rel, language="python", confidence=UNKNOWN,
                          error=f"{type(exc).__name__} at line {lineno}: {getattr(exc, 'msg', exc)}")
    visitor = _Visitor(root, rel, source)
    visitor.visit(tree)
    exported = {s.name for s in visitor.out.symbols if s.exported and not s.parent}
    visitor.out.exports = sorted(exported)
    return visitor.out
