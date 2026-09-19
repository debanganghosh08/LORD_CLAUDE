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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lord", description="LORD deterministic engineering tooling")
    parser.add_argument("--version", action="version", version=f"lord {__version__}")
    _add_common(parser, top_level=True)
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="verify environment, workspace boundary and adapter presence")
    _add_common(doctor)
    return parser


def _add_common(parser: argparse.ArgumentParser, top_level: bool = False) -> None:
    """`--root` and `--json` are accepted before or after the subcommand.

    Subcommand copies use SUPPRESS so they only override the top-level value
    when explicitly given (argparse would otherwise reset it to the default).
    """
    default = None if top_level else argparse.SUPPRESS
    parser.add_argument("--root", type=Path, default=default, help="workspace root (default: auto-detect)")
    parser.add_argument("--json", action="store_true", default=False if top_level else argparse.SUPPRESS,
                        help="emit JSON instead of Markdown")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = find_workspace_root(args.root)
    # Windows consoles default to a legacy code page; reports are UTF-8.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if args.command == "doctor":
        from lord.doctor import run_doctor

        return _emit(run_doctor(root), args.json)

    parser.error(f"unknown command {args.command!r}")  # pragma: no cover
    return 2
