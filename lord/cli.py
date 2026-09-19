"""LORD command-line interface.

`python -m lord <command> [options]` is the stable boundary between the
deterministic core and whatever agent or IDE is driving it. Every command
returns a `Report`; `--json` selects machine-readable output, the default is
compact Markdown suitable for pasting into a model's context.

Exit codes: 0 = ok/info, 1 = report contains an error finding, 2 = usage error.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from lord import __version__
from lord.paths import find_workspace_root
from lord.report import Report


def _emit(report: Report, as_json: bool) -> int:
    sys.stdout.write(report.to_json() + "\n" if as_json else report.to_markdown())
    return 1 if report.has_errors else 0


def _add_common(parser: argparse.ArgumentParser, top_level: bool = False) -> None:
    """`--root` and `--json` are accepted before or after the subcommand.

    Subcommand copies use SUPPRESS so they only override the top-level value
    when explicitly given (argparse would otherwise reset it to the default).
    """
    default = None if top_level else argparse.SUPPRESS
    parser.add_argument("--root", type=Path, default=default, help="workspace root (default: auto-detect)")
    parser.add_argument("--json", action="store_true", default=False if top_level else argparse.SUPPRESS,
                        help="emit JSON instead of Markdown")


# (name, help, positional argument name or None, extra options)
COMMANDS: tuple[tuple[str, str, str | None], ...] = (
    ("doctor", "verify environment, workspace boundary and adapter presence", None),
    ("inventory", "classify every file (source/test/config/...) with exclusions applied", None),
    ("index", "build or refresh the repository index in .lord/", None),
    ("symbols", "list the symbols a file defines", "path"),
    ("def", "where is a symbol defined", "name"),
    ("refs", "where is a symbol used (confirmed vs text matches)", "name"),
    ("related", "existing implementations related to a behaviour or name", "query"),
    ("deps", "what a file depends on (resolved imports)", "path"),
    ("dependents", "what depends on a file (importers)", "path"),
    ("tests-for", "test files that touch a symbol or file", "target"),
    ("reuse", "before creating something: what already exists? (reuse -> extend -> refactor -> create)", "description"),
    ("duplicates", "candidate duplicate symbols, constants, function bodies and thin wrappers", None),
    ("diff", "change surface of the working tree, staged set or a base ref, with a bloat signal", None),
    ("impact", "what happens if this symbol or file changes: callers, dependents, types, tests, config, boundary, consequences", "target"),
    ("trace", "root-cause worksheet: candidate causes downstream and callers upstream of an observed symptom", "target"),
    ("graph", "inspect one node's edges in the relationship graph", "target"),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lord", description="LORD deterministic engineering tooling")
    parser.add_argument("--version", action="version", version=f"lord {__version__}")
    _add_common(parser, top_level=True)
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text, positional in COMMANDS:
        p = sub.add_parser(name, help=help_text)
        _add_common(p)
        if positional:
            p.add_argument(positional, help=f"{positional} to analyse")
        if name == "index":
            p.add_argument("--rebuild", action="store_true", help="discard the cached index and re-extract everything")
        if name == "related":
            p.add_argument("--limit", type=int, default=10)
        if name == "refs":
            p.add_argument("--no-tests", action="store_true", help="exclude test files")
        if name == "reuse":
            p.add_argument("--name", action="append", default=[], help="proposed symbol name (repeatable)")
        if name == "duplicates":
            p.add_argument("--include-tests", action="store_true", help="also compare test files")
        if name == "diff":
            p.add_argument("--base", default=None, help="compare against this ref (default: working tree vs HEAD)")
            p.add_argument("--staged", action="store_true", help="compare the staged set only")
            p.add_argument("--scope", action="append", default=[], help="path or term the task is about (repeatable)")
        if name in ("impact", "trace"):
            p.add_argument("--depth", type=int, default=2 if name == "impact" else 3, help="traversal depth")
        if name == "trace":
            p.add_argument("--observed", default="", help="the symptom as observed (input, expected vs actual)")
    return parser


def run(args: argparse.Namespace, root: Path) -> Report:
    if args.command == "doctor":
        from lord.doctor import run_doctor

        return run_doctor(root)

    from lord.config import load_config
    from lord.index import build_index, ensure_index, load_index

    config = load_config(root)
    if args.command == "inventory":
        from lord.inventory import build_inventory, summarize
        from lord.report import OK, Finding

        inventory = build_inventory(config)
        summary = summarize(inventory)
        report = Report(title="LORD inventory", meta={"root": str(root), **summary})
        report.add(Finding(kind="inventory", summary=f"{summary['files']} files, {summary['source_lines']} source lines, {summary['excluded_dirs']} excluded dirs",
                           severity=OK, data={"files": [f.__dict__ for f in inventory.files], "excluded_dirs": inventory.excluded_dirs}))
        return report
    if args.command == "index":
        previous = None if args.rebuild else load_index(root)
        _, report = build_index(config, previous=previous)
        return report

    from lord import query

    index = ensure_index(config)
    if args.command == "symbols":
        return query.symbols_in(index, _norm(args.path))
    if args.command == "def":
        return query.definition(index, args.name)
    if args.command == "refs":
        return query.references(index, root, args.name, include_tests=not args.no_tests)
    if args.command == "related":
        return query.related(index, args.query, limit=args.limit)
    if args.command == "deps":
        return query.deps(index, _norm(args.path))
    if args.command == "dependents":
        return query.dependents(index, _norm(args.path))
    if args.command == "tests-for":
        return query.tests_for(index, root, _norm(args.target))
    if args.command == "reuse":
        from lord.reuse import reuse_report

        return reuse_report(index, root, args.description, names=args.name)
    if args.command == "duplicates":
        from lord.reuse import duplicates_report

        return duplicates_report(index, root, include_tests=args.include_tests)
    if args.command == "diff":
        from lord.change_surface import measure

        return measure(config, index, base=args.base, staged=args.staged, scope=tuple(args.scope))
    if args.command == "impact":
        from lord.impact import impact_report

        return impact_report(index, root, args.target, depth=args.depth)
    if args.command == "trace":
        from lord.impact import trace_report

        return trace_report(index, root, args.target, depth=args.depth, observed=args.observed)
    if args.command == "graph":
        from lord.graph import build_graph, file_node, neighborhood, sym_node
        from lord.impact import resolve_target
        from lord.report import OK, UNKNOWN, WARN, Finding

        resolved = resolve_target(index, args.target)
        report = Report(title=f"graph: {args.target}", meta={"root": str(root)})
        if resolved is None:
            report.add(Finding(kind="node", summary=f"{args.target!r} is not an indexed file or symbol", severity=WARN, confidence=UNKNOWN))
            return report
        graph = build_graph(index, root)
        nodes = [file_node(resolved[1])] if resolved[0] == "file" else [sym_node(s) for s in resolved[1]]
        for node in nodes:
            hood = neighborhood(graph, node)
            report.add(Finding(kind="node", summary=f"{node}: {len(hood['outgoing'])} outgoing, {len(hood['incoming'])} incoming", severity=OK,
                               evidence=[f"-> {e['kind']} {e['to']} [{e['confidence']}, line {e['line']}]" for e in hood["outgoing"][:40]]
                               + [f"<- {e['kind']} {e['from']} [{e['confidence']}, line {e['line']}]" for e in hood["incoming"][:40]], data=hood))
        report.meta["edges_total"] = len(graph)
        return report
    raise SystemExit(2)  # pragma: no cover


def _norm(path: str) -> str:
    return path.replace("\\", "/").removeprefix("./")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = find_workspace_root(args.root)
    # Windows consoles default to a legacy code page; reports are UTF-8.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    return _emit(run(args, root), args.json)
