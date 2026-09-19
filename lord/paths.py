"""Workspace root resolution and path safety.

Every LORD operation is scoped to exactly one workspace root. Nothing in LORD
may read or write outside that root, and the Git repository root must be the
workspace root itself (never a parent directory). These helpers are the single
place where that boundary is defined.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

# Files/directories whose presence marks a LORD workspace root. Checked in
# order while walking upward from the starting directory.
ROOT_MARKERS: tuple[str, ...] = ("lord.toml", ".agents", ".git")

# Machine-local state LORD generates. Always ignored by Git.
STATE_DIR_NAME = ".lord"


class BoundaryError(RuntimeError):
    """Raised when an operation would leave the workspace boundary."""


def find_workspace_root(start: Path | None = None) -> Path:
    """Return the nearest ancestor (or `start` itself) containing a root marker.

    Falls back to `start` when no marker is found so LORD still works in a
    plain directory; callers that need Git should use `git_toplevel`.
    """
    origin = (start or Path.cwd()).resolve()
    for candidate in (origin, *origin.parents):
        if any((candidate / marker).exists() for marker in ROOT_MARKERS):
            return candidate
    return origin


def git_toplevel(path: Path) -> Path | None:
    """Return the Git repository root that contains `path`, or None."""
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=path,
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None
    top = completed.stdout.strip()
    return Path(top).resolve() if top else None


def is_within(path: Path, root: Path) -> bool:
    """True when `path` resolves to `root` or a descendant of it."""
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def safe_join(root: Path, relative: str | Path) -> Path:
    """Join `relative` onto `root`, refusing anything that escapes the root."""
    candidate = (root / relative).resolve()
    if not is_within(candidate, root):
        raise BoundaryError(f"{relative!s} resolves outside workspace root {root}")
    return candidate


def to_rel_posix(path: Path, root: Path) -> str:
    """Workspace-relative POSIX path, the canonical form used in every report."""
    return path.resolve().relative_to(root.resolve()).as_posix()


def state_dir(root: Path, create: bool = False) -> Path:
    """Location of machine-local derived state (`<root>/.lord`)."""
    directory = root / STATE_DIR_NAME
    if create:
        directory.mkdir(parents=True, exist_ok=True)
    return directory
