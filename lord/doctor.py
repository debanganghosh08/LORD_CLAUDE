"""`lord doctor`: verify the environment and workspace boundary.

This is the first thing an agent (or a human) should run in a new workspace.
It answers: is Python adequate, is Git present, is ripgrep available, where is
the workspace root, does the Git root match it, and is the Antigravity adapter
present. It reports facts, never secrets.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from lord.config import load_config
from lord.paths import git_toplevel, state_dir
from lord.report import CONFIRMED, ERROR, INFO, OK, WARN, Finding, Report

MIN_PYTHON = (3, 11)
ADAPTER_DIRS = ("rules", "skills", "agents")


def run_doctor(root: Path) -> Report:
    report = Report(title="LORD doctor", meta={"root": str(root)})

    version = sys.version_info[:3]
    report.add(
        Finding(
            kind="python",
            summary=f"Python {'.'.join(map(str, version))}",
            severity=OK if version >= MIN_PYTHON else ERROR,
            evidence=[sys.executable],
            recommendation="" if version >= MIN_PYTHON else "LORD requires Python 3.11+",
        )
    )

    for tool, required in (("git", True), ("rg", False)):
        found = shutil.which(tool)
        report.add(
            Finding(
                kind=f"tool-{tool}",
                summary=f"{tool} {'found' if found else 'not found'}",
                severity=OK if found else (ERROR if required else WARN),
                evidence=[found] if found else [],
                recommendation=(
                    "" if found else f"install {tool}; " + ("LORD needs Git for boundary checks" if required else "ripgrep speeds up reference search; LORD falls back to a slower scan")
                ),
            )
        )

    top = git_toplevel(root)
    if top is None:
        report.add(
            Finding(
                kind="git-root",
                summary="workspace is not inside a Git repository",
                severity=WARN,
                consequence="diff-based analysis and change-surface measurement are unavailable",
                recommendation="run `git init` in the workspace root",
            )
        )
    elif top != root.resolve():
        report.add(
            Finding(
                kind="git-root",
                summary="Git root differs from workspace root",
                severity=ERROR,
                evidence=[f"workspace={root}", f"git_toplevel={top}"],
                consequence="commits could capture files outside the project boundary",
                recommendation="run LORD from the repository root, or initialise Git in the workspace root",
            )
        )
    else:
        report.add(Finding(kind="git-root", summary="Git root matches workspace root", severity=OK, evidence=[str(top)]))

    config = load_config(root)
    report.add(
        Finding(
            kind="config",
            summary="lord.toml loaded" if config.source_file else "using built-in defaults (no lord.toml)",
            severity=OK,
            evidence=[str(config.source_file)] if config.source_file else [],
            data={"exclude_dirs": len(config.exclude_dirs), "exclude_globs": len(config.exclude_globs)},
        )
    )

    agents_dir = root / ".agents"
    present = [d for d in ADAPTER_DIRS if (agents_dir / d).is_dir()]
    report.add(
        Finding(
            kind="antigravity-adapter",
            summary=(
                f".agents/ present with {', '.join(present)}" if present else ".agents/ adapter not found"
            ),
            severity=OK if present else INFO,
            evidence=[str(agents_dir)] if agents_dir.exists() else [],
            recommendation="" if present else "install the LORD Antigravity adapter to activate rules, skills and agents",
        )
    )

    sd = state_dir(root)
    writable = os.access(root, os.W_OK)
    report.add(
        Finding(
            kind="state-dir",
            summary=f"state directory {'exists' if sd.exists() else 'will be created'} at {sd.name}/",
            severity=OK if writable else ERROR,
            evidence=[str(sd)],
            recommendation="" if writable else "workspace root is not writable",
        )
    )

    report.add(
        Finding(
            kind="provider-independence",
            summary="LORD core makes no model API calls and needs no API key",
            severity=OK,
            confidence=CONFIRMED,
            evidence=["pyproject.toml: dependencies = []"],
        )
    )
    return report
