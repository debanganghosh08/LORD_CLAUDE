"""Runtime session state under `.lord/session/` (machine-local, ignored).

Two small records, both append-only JSON lines or tiny JSON files:

- `activity.jsonl`: every LORD investigation command run in this workspace
  (command, target, time). The pre-edit hook reads it as evidence that a
  target was investigated before it is modified. Nothing else is stored:
  no prompts, no model output, no source.
- per-conversation counters and caches used by the Stop and PostInvocation
  hooks (continuation count, last verification signature, last bloat level).

This is transient state. Durable engineering knowledge lives in
`docs/state/` (Phase 7), never here.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from lord.paths import state_dir

SESSION_DIR_NAME = "session"
ACTIVITY_FILE = "activity.jsonl"
HOOK_LOG_FILE = "hooks.log"
MAX_ACTIVITY_LINES = 1000
KEEP_ACTIVITY_LINES = 500

# Commands whose execution counts as investigation evidence.
INVESTIGATION_COMMANDS = frozenset({
    "brief", "reuse", "impact", "trace", "refs", "def", "related", "symbols", "deps", "dependents",
    "tests-for", "graph", "duplicates", "diff", "verify",
})
TASK_LEVEL_COMMANDS = frozenset({"brief", "reuse", "impact", "trace", "related", "duplicates"})


def session_dir(root: Path, create: bool = True) -> Path:
    directory = state_dir(root) / SESSION_DIR_NAME
    if create:
        directory.mkdir(parents=True, exist_ok=True)
    return directory


def _append(path: Path, entry: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, default=str) + "\n")


def record(root: Path, command: str, target: str = "", extra: dict[str, Any] | None = None) -> None:
    """Append one activity entry. Never raises: session state is best-effort."""
    try:
        path = session_dir(root) / ACTIVITY_FILE
        _append(path, {"t": time.time(), "command": command, "target": target.replace("\\", "/"), **(extra or {})})
        _trim(path)
    except OSError:
        pass


def _trim(path: Path) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    if len(lines) > MAX_ACTIVITY_LINES:
        path.write_text("\n".join(lines[-KEEP_ACTIVITY_LINES:]) + "\n", encoding="utf-8")


def recent(root: Path, window_seconds: float, now: float | None = None) -> list[dict[str, Any]]:
    """Activity entries newer than `window_seconds`, oldest first."""
    path = session_dir(root, create=False) / ACTIVITY_FILE
    if not path.is_file():
        return []
    cutoff = (now if now is not None else time.time()) - window_seconds
    entries = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if entry.get("t", 0) >= cutoff:
                entries.append(entry)
    except OSError:
        return []
    return entries


def evidence_for(root: Path, rel_path: str, symbol_names: set[str], window_seconds: float, now: float | None = None) -> tuple[str, dict[str, Any] | None]:
    """Strongest evidence that `rel_path` was investigated recently.

    Returns ("target", entry) when a command named the file or one of its
    symbols, ("task", entry) when a task-level command ran for anything,
    ("none", None) otherwise.
    """
    rel = rel_path.replace("\\", "/")
    stem = Path(rel).stem
    task_entry = None
    for entry in reversed(recent(root, window_seconds, now)):
        command = entry.get("command", "")
        if command not in INVESTIGATION_COMMANDS:
            continue
        target = str(entry.get("target", ""))
        named = {target, target.split("::")[-1], target.split(".")[-1]}
        if target and (target == rel or rel.endswith("/" + target) or target.endswith(rel) or named & symbol_names or target == stem):
            return "target", entry
        if command in TASK_LEVEL_COMMANDS and task_entry is None:
            task_entry = entry
    return ("task", task_entry) if task_entry else ("none", None)


# --- small per-key JSON state (counters, caches) ------------------------------------

def _state_path(root: Path, key: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in key)[:80]
    return session_dir(root) / f"{safe}.json"


def load_state(root: Path, key: str) -> dict[str, Any]:
    path = _state_path(root, key)
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, ValueError):
        return {}


def save_state(root: Path, key: str, data: dict[str, Any]) -> None:
    try:
        _state_path(root, key).write_text(json.dumps(data, default=str), encoding="utf-8")
    except OSError:
        pass


def hook_log(root: Path, entry: dict[str, Any]) -> None:
    """Diagnostics for every hook invocation (decision, reason, timing)."""
    try:
        _append(session_dir(root) / HOOK_LOG_FILE, {"t": time.time(), "pid": os.getpid(), **entry})
    except OSError:
        pass
