"""Identifier search across the inventory.

Uses ripgrep when a real binary is on PATH, otherwise a pure-Python scan with
a byte-level prefilter. Both return the same `Hit` records so callers never
care which one ran. Matches are whole-identifier (word boundary) matches.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from lord.inventory import Inventory

MAX_SCAN_BYTES = 2_000_000


@dataclass(frozen=True)
class Hit:
    path: str
    line: int
    text: str


def ripgrep_available() -> bool:
    return shutil.which("rg") is not None


def _python_scan(root: Path, inventory: Inventory, name: str, paths: set[str] | None) -> list[Hit]:
    needle = name.encode("utf-8")
    pattern = re.compile(rb"(?<![\w$])" + re.escape(needle) + rb"(?![\w$])")
    hits: list[Hit] = []
    for record in inventory.files:
        if not record.is_text or record.size > MAX_SCAN_BYTES:
            continue
        if paths is not None and record.path not in paths:
            continue
        try:
            data = (root / record.path).read_bytes()
        except OSError:
            continue
        if needle not in data:
            continue
        for lineno, line in enumerate(data.splitlines(), start=1):
            if pattern.search(line):
                hits.append(Hit(record.path, lineno, line.decode("utf-8", "replace").strip()[:200]))
    return hits


def _ripgrep_scan(root: Path, inventory: Inventory, name: str, paths: set[str] | None) -> list[Hit] | None:
    args = ["rg", "--no-heading", "--line-number", "--with-filename", "--word-regexp", "--fixed-strings", "--no-messages"]
    for excluded in inventory.excluded_dirs:
        args += ["--glob", f"!{excluded}"]
    args += ["--", name, "."]
    try:
        completed = subprocess.run(args, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode not in (0, 1):
        return None
    hits: list[Hit] = []
    for raw in completed.stdout.splitlines():
        parts = raw.split(":", 2)
        if len(parts) < 3:
            continue
        path = parts[0].replace("\\", "/").removeprefix("./")
        if paths is not None and path not in paths:
            continue
        try:
            hits.append(Hit(path, int(parts[1]), parts[2].strip()[:200]))
        except ValueError:
            continue
    return hits


def find_identifier(root: Path, inventory: Inventory, name: str, paths: set[str] | None = None) -> list[Hit]:
    """All whole-word occurrences of `name` in inventoried text files."""
    if not name or not re.fullmatch(r"[\w$.]+", name):
        return []
    if ripgrep_available():
        hits = _ripgrep_scan(root, inventory, name, paths)
        if hits is not None:
            return hits
    return _python_scan(root, inventory, name, paths)
