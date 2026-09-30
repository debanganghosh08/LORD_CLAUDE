"""Workspace root resolution and path safety.

Every LORD operation is scoped to exactly one workspace root. Nothing in LORD
may read or write outside that root, and the Git repository root must be the
workspace root itself (never a parent directory). These helpers are the single
place where that boundary is defined.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

# A workspace-relative path with at least one directory and an extension, not
# glued to a longer token (so `a/b.py::func` yields `a/b.py`, URLs and version
# numbers do not match).
PATH_RE = re.compile(r"(?<![\w./-])((?:[\w.-]+/)+[\w.-]+\.[A-Za-z0-9]{1,8})")


def mentioned_paths(text: str) -> list[str]:
    """Workspace-relative paths a piece of text names, in order, deduplicated."""
    out: list[str] = []
    for match in PATH_RE.findall(text):
        rel = match.replace("\\\\", "/").split("::")[0]
        if rel.startswith("<") or rel in out:
            continue
        out.append(rel)
    return out

# Files/directories whose presence marks a LORD workspace root. Checked in
# order while walking upward from the starting directory.
ROOT_MARKERS: tuple[str, ...] = ("lord.toml", ".agents", ".git")

# Machine-local state LORD generates. Always ignored by Git.
STATE_DIR_NAME = ".lord"


class BoundaryError(RuntimeError):
    """Raised when an operation would leave the workspace boundary."""


def _home() -> Path | None:
    try:
        return Path.home().resolve()
    except (OSError, RuntimeError):
        return None


def find_workspace_root(start: Path | None = None) -> Path:
    """Return the nearest ancestor (or `start` itself) containing a root marker.

    Falls back to `start` when no marker is found so LORD still works in a
    plain directory; callers that need Git should use `git_toplevel`.

    The walk never climbs to the user's home directory or above it: a
    home-level `.agents` or `.git` is global tool configuration, not a
    workspace. (Observed 2026-09-30: a global `~/.agents/skills` folder made
    every marker-less directory under home resolve to home, and `inventory`
    walked the whole home directory.) Starting *at* home is still allowed.
    """
    origin = (start or Path.cwd()).resolve()
    home = _home()
    for candidate in (origin, *origin.parents):
        if home is not None and candidate != origin and (candidate == home or candidate in home.parents):
            break
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
    """Location of machine-local derived state (`<root>/.lord`).

    The directory ignores itself (`.lord/.gitignore` = `*`, as pytest does for
    its cache), so a target repository never has to edit its own .gitignore
    for LORD and runtime state can never be committed by accident."""
    directory = root / STATE_DIR_NAME
    if create:
        directory.mkdir(parents=True, exist_ok=True)
    if directory.is_dir():
        marker = directory / ".gitignore"
        if not marker.exists():
            try:
                marker.write_text("# LORD runtime state (machine-local); never commit.\n*\n", encoding="utf-8")
            except OSError:
                pass
    return directory


# --- product location ---------------------------------------------------------------
# The runtime (this package) is found in one of two layouts, never by an
# absolute path: an installed plugin bundle `<plugin>/runtime/lord/`, or a
# development checkout `<repo>/lord/` next to the plugin source `<repo>/plugin/`.

PLUGIN_NAME = "lord"
PLUGIN_MANIFEST = "plugin.json"


def runtime_home() -> Path:
    """The directory that contains the `lord` package being executed."""
    return Path(__file__).resolve().parent.parent


def plugin_root() -> Path | None:
    """The plugin this runtime belongs to: the installed bundle, or the plugin
    source of a development checkout. None when neither layout applies."""
    home = runtime_home()
    if home.name == "runtime" and (home.parent / PLUGIN_MANIFEST).is_file():
        return home.parent
    if (home / "plugin" / PLUGIN_MANIFEST).is_file():
        return home / "plugin"
    return None


def global_plugins_dir() -> Path | None:
    """Antigravity's documented user-level plugin directory (read-only here)."""
    home = _home()
    return home / ".gemini" / "config" / "plugins" if home is not None else None


def product_dirs(root: Path) -> list[Path]:
    """Directories that provide LORD rules and skills to this workspace: a
    workspace adapter (`<root>/.agents`) and the plugin this runtime belongs to."""
    dirs = [root / ".agents"]
    plugin = plugin_root()
    if plugin is not None:
        dirs.append(plugin)
    seen: list[Path] = []
    for d in dirs:
        if d.is_dir() and d.resolve() not in [s.resolve() for s in seen]:
            seen.append(d)
    return seen
