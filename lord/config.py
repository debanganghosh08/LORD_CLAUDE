"""LORD configuration.

Defaults are built in so LORD works on any repository with zero setup. A
project may override them with an optional `lord.toml` at the workspace root:

    [lord]
    exclude_dirs = ["node_modules", "dist", "generated"]   # replaces defaults
    extra_exclude_dirs = ["vendor/legacy"]                  # adds to defaults
    exclude_globs = ["**/*.min.js"]

Only the standard library `tomllib` reader is used; LORD never writes config.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_FILENAME = "lord.toml"

# Directories that are never scanned. These are vendor trees, build output,
# caches, virtual environments, and provider/IDE runtime state.
DEFAULT_EXCLUDE_DIRS: tuple[str, ...] = (
    ".git",
    ".hg",
    ".svn",
    ".lord",
    ".claude",
    ".gemini",
    ".antigravity",
    ".cursor",
    ".idea",
    ".vscode",
    "node_modules",
    "bower_components",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    "build",
    "dist",
    "out",
    "target",
    "bin",
    "obj",
    ".next",
    ".nuxt",
    ".turbo",
    ".cache",
    "coverage",
    "htmlcov",
    "site-packages",
    "vendor",
    "third_party",
)

DEFAULT_EXCLUDE_GLOBS: tuple[str, ...] = (
    "*.min.js",
    "*.min.css",
    "*.map",
    "*.lock",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "*.pyc",
    "*.log",
)


@dataclass(frozen=True)
class LordConfig:
    root: Path
    exclude_dirs: tuple[str, ...] = DEFAULT_EXCLUDE_DIRS
    exclude_globs: tuple[str, ...] = DEFAULT_EXCLUDE_GLOBS
    source_file: Path | None = None
    raw: dict = field(default_factory=dict, compare=False)


def load_config(root: Path) -> LordConfig:
    """Load `<root>/lord.toml` if present, otherwise return built-in defaults."""
    path = root / CONFIG_FILENAME
    if not path.is_file():
        return LordConfig(root=root)

    with path.open("rb") as handle:
        data = tomllib.load(handle)
    section = data.get("lord", {}) if isinstance(data, dict) else {}

    exclude_dirs = tuple(section.get("exclude_dirs", DEFAULT_EXCLUDE_DIRS))
    exclude_dirs += tuple(section.get("extra_exclude_dirs", ()))
    exclude_globs = tuple(section.get("exclude_globs", DEFAULT_EXCLUDE_GLOBS))
    exclude_globs += tuple(section.get("extra_exclude_globs", ()))

    return LordConfig(
        root=root,
        exclude_dirs=exclude_dirs,
        exclude_globs=exclude_globs,
        source_file=path,
        raw=section,
    )
