"""`lord doctor`: verify the environment and workspace boundary.

This is the first thing an agent (or a human) should run in a new workspace.
It answers: is Python adequate, is Git present, is ripgrep available, where is
the workspace root, does the Git root match it, and is the Antigravity adapter
present. It reports facts, never secrets.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

from lord import __version__
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

    # where LORD's rules and skills come from, and which runtime is executing
    from lord.paths import plugin_root, product_dirs, runtime_home

    plugin = plugin_root()
    origin = "installed plugin" if plugin is not None and plugin.parent != runtime_home() else "development checkout"
    report.add(Finding(kind="runtime", summary=f"LORD {__version__} runtime from the {origin}", severity=OK, confidence=CONFIRMED,
                       evidence=[str(runtime_home())] + ([f"plugin: {plugin}"] if plugin else [])))
    sources = product_dirs(root)
    report.add(
        Finding(
            kind="product",
            summary=f"rules/skills provided by: {', '.join(str(d) for d in sources)}" if sources else "no LORD rules or skills found for this workspace",
            severity=OK if sources else INFO,
            evidence=[f"{d}: {', '.join(x for x in ADAPTER_DIRS if (d / x).is_dir())}" for d in sources],
            recommendation="" if sources else "install the plugin: `python -m lord plugin install --global`",
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

    from lord.plugin import _stdlib_violations

    violations = _stdlib_violations(runtime_home() / "lord")
    report.add(
        Finding(
            kind="provider-independence",
            summary="LORD runtime imports only the Python standard library: no model API, no API key" if not violations else f"{len(violations)} non-stdlib import(s) in the runtime",
            severity=OK if not violations else ERROR,
            confidence=CONFIRMED,
            evidence=violations[:10] or [f"checked every module under {runtime_home() / 'lord'}"],
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


def hook_configs(root: Path) -> list[tuple[str, Path]]:
    """Every hooks.json that can apply to this workspace, as (label, path):
    the workspace adapter, a workspace-installed plugin, the user-level hooks
    and a globally installed plugin (read, never written)."""
    from lord.paths import PLUGIN_NAME, global_plugins_dir

    candidates = [("workspace .agents", root / ".agents" / "hooks.json"),
                  ("workspace plugin", root / ".agents" / "plugins" / PLUGIN_NAME / "hooks.json")]
    plugins = global_plugins_dir()
    if plugins is not None:
        candidates += [("user hooks", plugins.parent / "hooks.json"), ("global plugin", plugins / PLUGIN_NAME / "hooks.json")]
    return [(label, path) for label, path in candidates if path.is_file()]


def _commands(data: object) -> list[str]:
    commands = []
    for hook in data.values() if isinstance(data, dict) else []:
        for event, value in (hook.items() if isinstance(hook, dict) else []):
            if event == "enabled" or not isinstance(value, list):
                continue
            for item in value:
                handlers = item.get("hooks", []) if event in TOOL_EVENTS and isinstance(item, dict) else [item]
                commands.extend(h.get("command", "") for h in handlers if isinstance(h, dict))
    return commands


def _launcher_of(command: str, config_dir: Path) -> Path | None:
    """The launcher a LORD hook command runs: `python -m lord_hook` resolves
    in the hook's working directory (the directory holding hooks.json);
    `python "<path>/lord_hook.py"` names it."""
    if "lord_hook" not in command:
        return None
    match = re.search(r'"([^"]*lord_hook\.py)"|(\S*lord_hook\.py)', command)
    if match:
        return Path(match.group(1) or match.group(2))
    return config_dir / "lord_hook.py"


def check_hooks(root: Path) -> list[Finding]:
    """Findings about every hooks.json that applies: schema, resolvable
    commands, launcher presence, and LORD enforcement configured twice."""
    import json

    configs = hook_configs(root)
    if not configs:
        return [Finding(kind="hooks", summary="no hooks.json applies to this workspace (enforcement not installed)", severity=INFO,
                        recommendation="install the plugin: `python -m lord plugin install --global` (see docs/INSTALL.md)")]
    findings: list[Finding] = []
    running_lord: list[str] = []
    for label, path in configs:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            findings.append(Finding(kind="hooks", summary=f"{label}: hooks.json is not valid JSON: {exc}", severity=ERROR, evidence=[str(path)],
                                    consequence="Antigravity will ignore or reject the file", recommendation="fix the JSON"))
            continue
        errors = validate_hooks_config(data)
        before = len(findings)
        if errors:
            findings.append(Finding(kind="hooks", summary=f"{label}: hooks.json has {len(errors)} schema problem(s)", severity=ERROR, evidence=errors[:10]))
        commands = _commands(data)
        missing = sorted({c.split()[0] for c in commands if c and shutil.which(c.split()[0]) is None})
        if missing:
            findings.append(Finding(kind="hooks", summary=f"{label}: hook command executable(s) not on PATH: {', '.join(missing)}", severity=ERROR,
                                    consequence="a PreToolUse hook that cannot start denies every matching tool call", recommendation="install it or disable the hook"))
        launchers = {_launcher_of(c, path.parent) for c in commands} - {None}
        if launchers:
            running_lord.append(label)
        for launcher in sorted(launchers, key=str):
            if not launcher.is_file():  # type: ignore[union-attr]
                findings.append(Finding(kind="hooks", summary=f"{label}: LORD launcher missing at {launcher}", severity=ERROR, evidence=[str(path)],
                                        consequence="without the launcher every gated write is denied", recommendation="reinstall: `python -m lord plugin install ...`"))
        if len(findings) == before and isinstance(data, dict):
            events = sorted({e for h in data.values() if isinstance(h, dict) for e in h if e != "enabled"})
            findings.append(Finding(kind="hooks", summary=f"{label}: hooks.json valid: {', '.join(events)}", severity=OK, evidence=[str(path)]))
    if len(running_lord) > 1:
        findings.append(Finding(kind="hooks", summary=f"LORD hooks are configured {len(running_lord)} times ({', '.join(running_lord)})", severity=WARN,
                                consequence="Antigravity merges hook configurations and runs each one: every gate would fire twice",
                                recommendation="keep one: the global plugin, or a workspace install, not both"))
    return findings
