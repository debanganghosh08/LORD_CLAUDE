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
