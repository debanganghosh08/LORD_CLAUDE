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

    report.extend(check_hooks(root))

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


HOOK_EVENTS = ("PreToolUse", "PostToolUse", "PreInvocation", "PostInvocation", "Stop")
TOOL_EVENTS = ("PreToolUse", "PostToolUse")
MAX_HOOK_TIMEOUT = 600


def validate_hooks_config(data: object) -> list[str]:
    """Structural validation of a hooks.json document against the documented schema."""
    errors: list[str] = []
    if not isinstance(data, dict) or not data:
        return ["hooks.json must be a non-empty object mapping hook names to configurations"]
    for name, hook in data.items():
        if not isinstance(hook, dict):
            errors.append(f"{name}: must be an object")
            continue
        if "enabled" in hook and not isinstance(hook["enabled"], bool):
            errors.append(f"{name}.enabled must be a boolean")
        for event, value in hook.items():
            if event == "enabled":
                continue
            if event not in HOOK_EVENTS:
                errors.append(f"{name}: unknown event {event!r}")
                continue
            if not isinstance(value, list):
                errors.append(f"{name}.{event} must be a list")
                continue
            handlers = []
            for item in value:
                if event in TOOL_EVENTS:
                    if not isinstance(item, dict) or "hooks" not in item:
                        errors.append(f"{name}.{event}: entries need a matcher and a hooks list")
                        continue
                    if not isinstance(item.get("matcher", ""), str):
                        errors.append(f"{name}.{event}: matcher must be a string")
                    handlers.extend(item.get("hooks") or [])
                else:
                    handlers.append(item)
            for handler in handlers:
                if not isinstance(handler, dict) or not isinstance(handler.get("command"), str) or not handler.get("command"):
                    errors.append(f"{name}.{event}: handler needs a non-empty command string")
                    continue
                if handler.get("type", "command") != "command":
                    errors.append(f"{name}.{event}: only type 'command' is supported")
                timeout = handler.get("timeout", 30)
                if not isinstance(timeout, int) or timeout <= 0 or timeout > MAX_HOOK_TIMEOUT:
                    errors.append(f"{name}.{event}: timeout must be an integer in 1..{MAX_HOOK_TIMEOUT} seconds")
    return errors


def check_hooks(root: Path) -> list[Finding]:
    """Findings about `.agents/hooks.json`: schema, resolvable commands, launcher copies."""
    import json

    path = root / ".agents" / "hooks.json"
    if not path.is_file():
        return [Finding(kind="hooks", summary="no .agents/hooks.json (enforcement not installed)", severity=INFO)]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        return [Finding(kind="hooks", summary=f"hooks.json is not valid JSON: {exc}", severity=ERROR, evidence=[str(path)],
                        consequence="Antigravity will ignore or reject the file", recommendation="fix the JSON")]
    errors = validate_hooks_config(data)
    findings = []
    if errors:
        findings.append(Finding(kind="hooks", summary=f"hooks.json has {len(errors)} schema problem(s)", severity=ERROR, evidence=errors[:10]))
    commands = []
    for hook in data.values() if isinstance(data, dict) else []:
        for event, value in (hook.items() if isinstance(hook, dict) else []):
            if event == "enabled" or not isinstance(value, list):
                continue
            for item in value:
                handlers = item.get("hooks", []) if event in TOOL_EVENTS and isinstance(item, dict) else [item]
                commands.extend(h.get("command", "") for h in handlers if isinstance(h, dict))
    missing = sorted({c.split()[0] for c in commands if c and shutil.which(c.split()[0]) is None})
    if missing:
        findings.append(Finding(kind="hooks", summary=f"hook command executable(s) not on PATH: {', '.join(missing)}", severity=ERROR,
                                consequence="a PreToolUse hook that cannot start denies every matching tool call", recommendation="install it or disable the hook"))
    launcher = root / ".agents" / "lord_hook.py"
    if any("lord_hook" in c for c in commands) and not launcher.is_file():
        findings.append(Finding(kind="hooks", summary=".agents/lord_hook.py launcher missing", severity=ERROR, evidence=[str(launcher)],
                                consequence="Antigravity runs workspace hooks from .agents/; without the launcher every gated write is denied"))
    if not findings:
        findings.append(Finding(kind="hooks", summary=f"hooks.json valid: {', '.join(sorted({e for h in data.values() for e in h if e != 'enabled'}))}", severity=OK, evidence=[str(path)]))
    return findings
