"""Antigravity hook decisions: thin enforcement over LORD core evidence.

Contract (antigravity.google/docs/hooks, confirmed against live payloads):
stdin is camelCase JSON; stdout must be JSON. PreToolUse returns
`{"decision": "allow|deny|ask|force_ask|deny_unless_prior_grant", "reason"}`,
PostInvocation may return `{"injectSteps": [{"ephemeralMessage": ...}]}`,
Stop returns `{"decision": "continue", "reason"}` to block completion or
anything else to allow it.

Safety model (observed live: a PreToolUse hook that exits non-zero or prints
malformed JSON DENIES the tool call):
- every code path ends in valid JSON and exit code 0;
- any internal error -> the event's permissive default, logged;
- deny only on strong deterministic evidence; ask when weaker; log otherwise;
- hooks never write, delete or rewrite user files; they read state and
  append diagnostics under `.lord/session/`;
- `LORD_HOOKS_DISABLED=1` or `LORD_HOOK_ACTIVE=1` (recursion guard) -> default.

Enforcement tiers:
  PreToolUse on write_to_file / replace_file_content / multi_replace_file_content
    non-code file, trivial edit, outside workspace ........ allow (audit)
    code file, investigated target in this session ........ allow (audit)
    code file, only task-level investigation .............. ask  (user decides)
    code file, no investigation at all ..................... deny (run brief/reuse first)
    new code file, no reuse/brief this session ............. deny
  Stop (fullyIdle, code changed, verification failed) ...... continue (bounded)
  PostInvocation (bloat signal rose to HIGH) ................ ephemeral warning
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from lord import session
from lord.config import load_config
from lord.inventory import PROBE_BYTES, classify, language_of
from lord.paths import find_workspace_root, is_within

EVENTS = ("pre-tool", "post-tool", "pre-invocation", "post-invocation", "stop")
WRITE_TOOLS = ("write_to_file", "replace_file_content", "multi_replace_file_content")
WRITE_TOOL_MATCHER = "|".join(WRITE_TOOLS)
DEFAULTS: dict[str, dict[str, Any]] = {
    "pre-tool": {"decision": "allow"},
    "post-tool": {},
    "pre-invocation": {},
    "post-invocation": {},
    "stop": {},
}
EVIDENCE_WINDOW_SECONDS = 45 * 60
TRIVIAL_EDIT_LINES = 3
MAX_STOP_CONTINUATIONS = 2
STOP_VERIFY_BUDGET_SECONDS = 540


def matcher_matches(matcher: str, tool: str) -> bool:
    """Antigravity matcher semantics: empty or * matches all; otherwise a regex
    that may use | for alternatives (full match)."""
    if matcher in ("", "*"):
        return True
    try:
        return re.fullmatch(matcher, tool) is not None
    except re.error:
        return False


# --- helpers --------------------------------------------------------------------------

def _root_from(payload: dict[str, Any], fallback: Path | None) -> Path | None:
    paths = payload.get("workspacePaths") or []
    for candidate in paths:
        try:
            p = Path(str(candidate)).resolve()
        except OSError:
            continue
        if p.is_dir():
            return find_workspace_root(p)
    return fallback


def _line_count(text: Any) -> int:
    if not isinstance(text, str) or not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def _target(root: Path, args: dict[str, Any]) -> tuple[Path | None, str]:
    raw = str(args.get("TargetFile") or args.get("AbsolutePath") or "")
    if not raw:
        return None, ""
    path = Path(raw)
    full = (path if path.is_absolute() else root / path)
    try:
        full = full.resolve()
    except OSError:
        return None, raw
    if not is_within(full, root):
        return None, raw
    return full, full.relative_to(root.resolve()).as_posix()


def _edit_shape(tool: str, args: dict[str, Any], exists: bool) -> tuple[str, int]:
    """(shape, changed_lines): shape is new-file | rewrite | edit | unknown."""
    if tool == "write_to_file":
        lines = _line_count(args.get("CodeContent"))
        return ("rewrite" if exists else "new-file"), lines
    if tool == "replace_file_content":
        return "edit", max(_line_count(args.get("TargetContent")), _line_count(args.get("ReplacementContent")))
    if tool == "multi_replace_file_content":
        chunks = args.get("ReplacementChunks")
        if isinstance(chunks, list):
            total = sum(max(_line_count(c.get("TargetContent")), _line_count(c.get("ReplacementContent"))) for c in chunks if isinstance(c, dict))
            return "edit", total
        return "unknown", 0
    return "unknown", 0


def _is_code(full: Path | None, rel: str) -> bool:
    language = language_of(Path(rel))
    probe = b""
    if full is not None and full.is_file():
        try:
            with full.open("rb") as handle:
                probe = handle.read(PROBE_BYTES)
        except OSError:
            probe = b""
    kind, _ = classify(rel, language, probe, b"\x00" not in probe)
    return kind in ("source", "script")


# --- PreToolUse ------------------------------------------------------------------------

def decide_pre_tool(payload: dict[str, Any], root: Path, now: float | None = None) -> dict[str, Any]:
    tool_call = payload.get("toolCall") or {}
    tool = str(tool_call.get("name") or "")
    args = tool_call.get("args") or {}
    if tool not in WRITE_TOOLS:
        return {"decision": "allow", "_audit": f"{tool or '?'}: not a write tool"}
    full, rel = _target(root, args)
    if full is None:
        return {"decision": "allow", "_audit": f"{tool}: target {rel!r} outside workspace or missing"}
    exists = full.is_file()
    if not _is_code(full, rel):
        return {"decision": "allow", "_audit": f"{tool} {rel}: not a code file"}
    shape, lines = _edit_shape(tool, args, exists)
    if shape == "edit" and 0 < lines <= TRIVIAL_EDIT_LINES:
        return {"decision": "allow", "_audit": f"{tool} {rel}: trivial edit ({lines} line(s))"}

    symbol_names: set[str] = set()
    if exists:
        try:
            from lord.index import load_index

            index = load_index(root)
            if index is not None:
                symbol_names = {s.name for s in index.symbols_in(rel)} | {s.qualname for s in index.symbols_in(rel)}
        except Exception:  # noqa: BLE001 - evidence lookup is best-effort
            symbol_names = set()
    level, entry = session.evidence_for(root, rel, symbol_names, EVIDENCE_WINDOW_SECONDS, now)
    label = f"{shape} of {rel} ({lines} line(s))" if lines else f"{shape} of {rel}"

    if shape == "new-file":
        if entry is not None and entry.get("command") in ("reuse", "brief"):
            return {"decision": "allow", "_audit": f"{label}: reuse/brief evidence `{entry['command']} {entry.get('target', '')}`"}
        return {
            "decision": "deny",
            "reason": (f"LORD pre-edit gate: {rel} is a new code file and no `lord reuse` or `lord brief` ran in this session. "
                       f"Run `python -m lord reuse \"<behaviour>\" --name <Name>` (reuse -> extend -> refactor -> create), then retry."),
        }
    if level == "target":
        return {"decision": "allow", "_audit": f"{label}: investigated (`{entry['command']} {entry.get('target', '')}`)"}
    if level == "task":
        return {
            "decision": "ask",
            "reason": (f"LORD pre-edit gate: {rel} was not itself investigated this session (only `{entry['command']} {entry.get('target', '')}`). "
                       f"Approve if intended, or run `python -m lord brief {rel}` first."),
        }
    return {
        "decision": "deny",
        "reason": (f"LORD pre-edit gate: no LORD investigation ran in this session before a {shape} of {rel}. "
                   f"Run `python -m lord brief {rel} --intent \"<goal>\"` (or `lord refs`/`lord impact` on the symbol), then retry."),
    }


# --- Stop ------------------------------------------------------------------------------

def _tree_signature(root: Path) -> str:
    try:
        status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace")
        text = status.stdout if status.returncode == 0 else ""
    except OSError:
        text = ""
    parts = [text]
    for line in text.splitlines():
        path = root / line[3:].strip().strip('"')
        try:
            parts.append(f"{line[3:]}:{path.stat().st_mtime_ns}")
        except OSError:
            continue
    return hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()


def _changed_code_files(root: Path) -> list[str]:
    try:
        from lord.change_surface import git_changes

        return [c.path for c in git_changes(root) if c.kind in ("source", "script") and c.status != "D"]
    except Exception:  # noqa: BLE001
        return []


def decide_stop(payload: dict[str, Any], root: Path, budget_seconds: float = STOP_VERIFY_BUDGET_SECONDS, run_steps: bool = True) -> dict[str, Any]:
    if payload.get("fullyIdle") is False:
        return {"_audit": "not fully idle"}
    conversation = str(payload.get("conversationId") or "default")
    changed = _changed_code_files(root)
    if not changed:
        return {"_audit": "no changed code files"}
    key = f"stop-{conversation}"
    state = session.load_state(root, key)
    continuations = int(state.get("continuations", 0))
    if continuations >= MAX_STOP_CONTINUATIONS:
        return {"_audit": f"continuation cap reached ({continuations}); allowing"}

    signature = _tree_signature(root)
    cached = state.get("verify") if state.get("signature") == signature else None
    if cached is None:
        from lord.index import ensure_index
        from lord.review import verify

        config = load_config(root)
        started = time.time()
        report = verify(config, ensure_index(config), run=run_steps, timeout=int(max(30, budget_seconds - 30)))
        meta = report.to_dict()["meta"]
        failing = [f for f in report.findings if f.kind == "verification-step" and f.severity == "error"]
        cached = {
            "verdict": meta.get("verdict"), "outstanding": meta.get("outstanding", []), "step_results": meta.get("step_results", {}),
            "failing": [{"summary": f.summary, "tail": f.evidence[-3:]} for f in failing],
            "bloat_level": meta.get("bloat_level"), "elapsed": round(time.time() - started, 1),
        }
        if time.time() - started > budget_seconds:
            session.save_state(root, key, {"signature": signature, "verify": cached, "continuations": continuations})
            return {"_audit": f"verification exceeded the hook budget ({cached['elapsed']}s); not blocking"}
    if cached.get("failing"):
        continuations += 1
        session.save_state(root, key, {"signature": signature, "verify": cached, "continuations": continuations})
        lines = "; ".join(f"{f['summary']}: {' | '.join(f['tail'])}"[:300] for f in cached["failing"][:3])
        return {
            "decision": "continue",
            "reason": (f"LORD completion gate: deterministic verification failed ({lines}). Fix it, re-run `python -m lord verify --run`, "
                       f"and only then report completion. Continuation {continuations}/{MAX_STOP_CONTINUATIONS}."),
        }
    session.save_state(root, key, {"signature": signature, "verify": cached, "continuations": continuations})
    warnings = [o for o in cached.get("outstanding", []) if "not executed" not in o]
    return {"_audit": f"verdict {cached.get('verdict')}; advisory: {warnings}" if warnings else f"verdict {cached.get('verdict')}"}


# --- PostInvocation ---------------------------------------------------------------------

def decide_post_invocation(payload: dict[str, Any], root: Path) -> dict[str, Any]:
    changed = _changed_code_files(root)
    if not changed:
        return {"_audit": "no changed code files"}
    conversation = str(payload.get("conversationId") or "default")
    key = f"surface-{conversation}"
    state = session.load_state(root, key)
    signature = _tree_signature(root)
    if state.get("signature") == signature:
        return {"_audit": "tree unchanged since last check"}
    from lord.change_surface import measure
    from lord.index import ensure_index

    config = load_config(root)
    report = measure(config, ensure_index(config))
    level = report.meta.get("bloat_level", "low")
    reasons = report.meta.get("bloat_reasons", [])
    previous = state.get("level", "low")
    session.save_state(root, key, {"signature": signature, "level": level, "reasons": reasons})
    if level == "high" or (level == "elevated" and previous == "low"):
        summary = report.findings[0].summary
        message = (f"LORD change-surface {level.upper()}: {summary}. Reasons: " + "; ".join(reasons[:5]) +
                   ". Did this become larger than the task requires? Check `python -m lord diff --scope <task>` before continuing.")
        return {"injectSteps": [{"ephemeralMessage": message}], "_audit": f"level {level} (was {previous}); warned"}
    return {"_audit": f"level {level} (was {previous}); no warning"}


# --- dispatch ---------------------------------------------------------------------------

def handle(event: str, payload: dict[str, Any], root: Path | None = None, now: float | None = None, budget_seconds: float = STOP_VERIFY_BUDGET_SECONDS, run_steps: bool = True) -> dict[str, Any]:
    """Return the JSON to emit for `event`. Never raises; never leaves `_audit`
    in the output. The permissive default is returned on any internal error."""
    default = dict(DEFAULTS.get(event, {}))
    started = time.time()
    resolved = _root_from(payload, root)
    if os.environ.get("LORD_HOOKS_DISABLED") == "1" or event not in EVENTS:
        return default
    if resolved is None:
        return default
    try:
        if event == "pre-tool":
            result = decide_pre_tool(payload, resolved, now)
        elif event == "stop":
            result = decide_stop(payload, resolved, budget_seconds=budget_seconds, run_steps=run_steps)
        elif event == "post-invocation":
            result = decide_post_invocation(payload, resolved)
        else:
            result = dict(default)
        outcome = "ok"
    except Exception as exc:  # noqa: BLE001 - a LORD bug must never block the user's work
        result = dict(default)
        result["_audit"] = f"internal error, defaulted: {type(exc).__name__}: {exc}"
        outcome = "error"
    audit = result.pop("_audit", "")
    tool = (payload.get("toolCall") or {}).get("name", "")
    session.hook_log(resolved, {
        "event": event, "tool": tool, "decision": result.get("decision", "") or ("inject" if result.get("injectSteps") else "allow"),
        "reason": result.get("reason", ""), "audit": audit, "outcome": outcome, "ms": int((time.time() - started) * 1000), "cwd": os.getcwd(),
    })
    return result


def main(argv: list[str] | None = None, stdin: str | None = None, root: Path | None = None) -> int:
    """Entry point used by the launcher: read stdin, print JSON, always exit 0."""
    argv = list(sys.argv[1:] if argv is None else argv)
    event = argv[0] if argv else ""
    budget = STOP_VERIFY_BUDGET_SECONDS
    if "--timeout" in argv:
        try:
            budget = float(argv[argv.index("--timeout") + 1])
        except (IndexError, ValueError):
            pass
    default = DEFAULTS.get(event, {"decision": "allow"} if event == "pre-tool" else {})
    if os.environ.get("LORD_HOOK_ACTIVE") == "1":
        sys.stdout.write(json.dumps(default))
        return 0
    os.environ["LORD_HOOK_ACTIVE"] = "1"
    try:
        raw = stdin if stdin is not None else sys.stdin.read()
        payload = json.loads(raw) if raw and raw.strip() else {}
        if not isinstance(payload, dict):
            payload = {}
        result = handle(event, payload, root=root, budget_seconds=budget)
    except Exception:  # noqa: BLE001
        result = default
    sys.stdout.write(json.dumps(result))
    sys.stdout.flush()
    return 0
