"""JavaScript / TypeScript heuristic extractor (INFERRED).

Line-oriented regular expressions find top-level and class-member
declarations, imports/exports and call sites. There is no parser here, so
every result is labelled `inferred`; string literals, comments and unusual
formatting can fool it. A tree-sitter based extractor can replace this module
later without changing the Extraction contract.
"""

from __future__ import annotations

import re
from pathlib import Path

from lord.report import INFERRED
from lord.symbols import Base, Extraction, Import, Ref, Symbol

IDENT = r"[A-Za-z_$][\w$]*"
RESOLVE_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts", ".vue", ".svelte")
CALL_KEYWORDS = {
    "if", "for", "while", "switch", "catch", "function", "return", "typeof", "await", "new", "else",
    "do", "try", "import", "export", "super", "constructor", "yield", "delete", "void", "in", "of",
}

RE_FUNCTION = re.compile(rf"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*({IDENT})\s*\(")
RE_CLASS = re.compile(rf"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+({IDENT})(?:\s+extends\s+([\w$.]+))?(?:\s+implements\s+([\w$.,\s]+?))?\s*\{{")
RE_VAR = re.compile(rf"^\s*(?:export\s+)?(?:const|let|var)\s+({IDENT})\s*(?::[^=]+)?=\s*(.*)$")
RE_INTERFACE = re.compile(rf"^\s*(?:export\s+)?interface\s+({IDENT})(?:\s+extends\s+([\w$.,\s]+?))?\s*\{{")
RE_TYPE = re.compile(rf"^\s*(?:export\s+)?type\s+({IDENT})\s*(?:<[^=]*>)?\s*=")
RE_ENUM = re.compile(rf"^\s*(?:export\s+)?(?:const\s+)?enum\s+({IDENT})")
RE_METHOD = re.compile(rf"^\s+(?:public\s+|private\s+|protected\s+|static\s+|async\s+|get\s+|set\s+|readonly\s+)*({IDENT})\s*\([^)]*\)\s*(?::\s*[^{{]+)?\{{")
RE_IMPORT_FROM = re.compile(r"""import\s+(?:type\s+)?(.+?)\s+from\s+['"]([^'"]+)['"]""")
RE_IMPORT_BARE = re.compile(r"""import\s+['"]([^'"]+)['"]""")
RE_REQUIRE = re.compile(rf"""(?:(?:const|let|var)\s+(\{{[^}}]*\}}|{IDENT})\s*=\s*)?require\(\s*['"]([^'"]+)['"]\s*\)""")
RE_DYNAMIC_IMPORT = re.compile(r"""import\(\s*['"]([^'"]+)['"]\s*\)""")
RE_EXPORT_LIST = re.compile(r"export\s*\{([^}]+)\}")
RE_EXPORTS_ASSIGN = re.compile(rf"(?:module\.)?exports\.({IDENT})\s*=")
RE_EXPORT_DEFAULT_NAME = re.compile(rf"^\s*export\s+default\s+({IDENT})\s*;?\s*$")
RE_CALL = re.compile(rf"(?:({IDENT}(?:\.{IDENT})*)\.)?\b({IDENT})\s*\(")
RE_ROUTE = re.compile(rf"""\b(?:app|router|server)\.(get|post|put|delete|patch|use|all)\(\s*['"]([^'"]+)['"]""")
RE_ARROW_OR_FN = re.compile(r"^(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*(?::\s*[^=]+)?=>|^(?:async\s+)?function\b")


def resolve_specifier(root: Path, rel: str, specifier: str) -> str | None:
    """Resolve a relative import specifier to a workspace file, else None."""
    if not specifier.startswith("."):
        return None
    base = (Path(rel).parent / specifier)
    candidates = [base, *(base.with_name(base.name + ext) for ext in RESOLVE_EXTS), *(base / f"index{ext}" for ext in RESOLVE_EXTS)]
    for candidate in candidates:
        try:
            full = (root / candidate).resolve()
        except OSError:
            continue
        if full.is_file():
            try:
                return full.relative_to(root.resolve()).as_posix()
            except ValueError:
                return None
    return None


def _parse_import_clause(clause: str) -> tuple[list[str], list[str]]:
    names: list[str] = []
    aliases: list[str] = []
    clause = clause.strip()
    braces = re.search(r"\{([^}]*)\}", clause)
    if braces:
        for part in braces.group(1).split(","):
            part = part.strip()
            if not part:
                continue
            if " as " in part:
                original, local = (p.strip() for p in part.split(" as ", 1))
            else:
                original = local = part
            names.append(original)
            aliases.append(local)
        clause = clause[: braces.start()] + clause[braces.end():]
    for part in clause.split(","):
        part = part.strip()
        if not part:
            continue
        if part.startswith("* as "):
            names.append("*")
            aliases.append(part[5:].strip())
        else:
            names.append("default")
            aliases.append(part)
    return names, aliases


def _strip_strings_and_comments(line: str) -> str:
    """Crude removal of string literal contents and line comments."""
    line = re.sub(r"(['\"`])(?:\\.|(?!\1).)*\1", "''", line)
    return line.split("//", 1)[0]


def extract_js_ts(root: Path, rel: str, source: str, language: str) -> Extraction:
    out = Extraction(file=rel, language=language, confidence=INFERRED)
    stack: list[tuple[str, int, bool]] = []  # (qualname, owning depth, is_class)
    open_symbols: dict[str, Symbol] = {}     # symbols whose closing brace has not been seen yet
    depth = 0
    in_block_comment = False
    export_names: set[str] = set()

    for lineno, raw in enumerate(source.splitlines(), start=1):
        line = raw
        if in_block_comment:
            if "*/" in line:
                line = line.split("*/", 1)[1]
                in_block_comment = False
            else:
                continue
        if "/*" in line and "*/" not in line.split("/*", 1)[1]:
            line = line.split("/*", 1)[0]
            in_block_comment = True
        code = _strip_strings_and_comments(line)
        stripped = code.strip()
        if not stripped:
            depth += code.count("{") - code.count("}")
            continue

        exported = stripped.startswith("export")
        parent = stack[-1][0] if stack else ""
        in_class = bool(stack) and stack[-1][2]
        declared: Symbol | None = None

        # imports (work on the raw line because specifiers are string literals)
        for m in RE_IMPORT_FROM.finditer(raw):
            names, aliases = _parse_import_clause(m.group(1))
            resolved = resolve_specifier(root, rel, m.group(2))
            out.imports.append(Import(m.group(2), names, aliases, lineno, resolved, INFERRED, m.group(2).startswith(".")))
        for m in RE_IMPORT_BARE.finditer(raw):
            resolved = resolve_specifier(root, rel, m.group(1))
            out.imports.append(Import(m.group(1), [], [], lineno, resolved, INFERRED, m.group(1).startswith(".")))
        for m in RE_REQUIRE.finditer(raw):
            names, aliases = _parse_import_clause(m.group(1)) if m.group(1) else ([], [])
            resolved = resolve_specifier(root, rel, m.group(2))
            out.imports.append(Import(m.group(2), names, aliases, lineno, resolved, INFERRED, m.group(2).startswith(".")))
        for m in RE_DYNAMIC_IMPORT.finditer(raw):
            resolved = resolve_specifier(root, rel, m.group(1))
            out.imports.append(Import(m.group(1), [], [], lineno, resolved, INFERRED, m.group(1).startswith(".")))

        # exports
        for m in RE_EXPORT_LIST.finditer(code):
            for part in m.group(1).split(","):
                part = part.strip()
                if part:
                    export_names.add(part.split(" as ")[-1].strip())
        for m in RE_EXPORTS_ASSIGN.finditer(code):
            export_names.add(m.group(1))
        if m := RE_EXPORT_DEFAULT_NAME.match(code):
            export_names.add(m.group(1))

        # declarations
        if m := RE_FUNCTION.match(code):
            declared = Symbol(m.group(1), "function", rel, lineno, m.group(1), language, INFERRED, parent=parent, exported=exported)
        elif m := RE_CLASS.match(code):
            qual = f"{parent}.{m.group(1)}" if parent else m.group(1)
            declared = Symbol(m.group(1), "class", rel, lineno, qual, language, INFERRED, parent=parent,
                              signature=f"extends {m.group(2)}" if m.group(2) else "", exported=exported)
            if m.group(2):
                out.bases.append(Base(qual, m.group(2), lineno))
            if m.group(3):
                for iface in m.group(3).split(","):
                    out.bases.append(Base(qual, iface.strip(), lineno, relation="implements"))
        elif m := RE_INTERFACE.match(code):
            declared = Symbol(m.group(1), "interface", rel, lineno, m.group(1), language, INFERRED, exported=exported)
            if m.group(2):
                for iface in m.group(2).split(","):
                    out.bases.append(Base(m.group(1), iface.strip(), lineno))
        elif m := RE_TYPE.match(code):
            declared = Symbol(m.group(1), "type", rel, lineno, m.group(1), language, INFERRED, exported=exported)
        elif m := RE_ENUM.match(code):
            declared = Symbol(m.group(1), "enum", rel, lineno, m.group(1), language, INFERRED, exported=exported)
        elif not in_class and (m := RE_VAR.match(code)):
            name, rhs = m.group(1), m.group(2).strip()
            kind = "function" if RE_ARROW_OR_FN.match(rhs) else ("constant" if name.isupper() else "variable")
            declared = Symbol(name, kind, rel, lineno, name, language, INFERRED, exported=exported)
        elif in_class and (m := RE_METHOD.match(code)) and m.group(1) not in CALL_KEYWORDS:
            declared = Symbol(m.group(1), "method", rel, lineno, f"{parent}.{m.group(1)}", language, INFERRED, parent=parent)

        # routes: app.get('/path', handler)
        for m in RE_ROUTE.finditer(raw):
            out.symbols.append(Symbol(f"{m.group(1).upper()} {m.group(2)}", "route", rel, lineno, f"{m.group(1).upper()} {m.group(2)}", language, INFERRED, signature=m.group(0)))

        if declared:
            out.symbols.append(declared)
            if exported:
                export_names.add(declared.name)

        # calls (skip the declaration's own name)
        scope = declared.qualname if declared and declared.kind in ("function", "method") else (stack[-1][0] if stack else "")
        for m in RE_CALL.finditer(code):
            receiver, name = m.group(1) or "", m.group(2)
            if name in CALL_KEYWORDS or (declared and name == declared.name):
                continue
            out.calls.append(Ref(name, lineno, scope, receiver=receiver))

        opens, closes = code.count("{"), code.count("}")
        if declared and opens > closes and declared.kind in ("class", "function", "method", "interface", "enum"):
            stack.append((declared.qualname, depth + 1, declared.kind == "class"))
            open_symbols[declared.qualname] = declared
        depth += opens - closes
        while stack and stack[-1][1] > depth:
            closed = stack.pop()[0]
            if closed in open_symbols:
                open_symbols.pop(closed).end_line = lineno

    out.exports = sorted(export_names)
    return out
