"""Durable engineering memory: `docs/state/memory.jsonl` and `docs/state/handoff.json`.

Repository engineering state, not personal memory and not a transcript.
One JSON object per line, sorted by id when saved, so Git diffs stay one
line per fact. Every item carries a category, a status and evidence, and
retrieval hides what is superseded, deprecated or expired unless asked.

Categories: decision, fact, discovery, trap, convention, unresolved, verification.
Statuses:   confirmed (evidence required), evidenced (evidence required),
            inferred, temporary (expiry date required), unresolved,
            superseded, deprecated.

Conflicts: items may carry a `key` naming the subject they describe (for
example "auth.middleware"). Two current items with the same key are an
unresolved conflict until one supersedes the other. Superseded items stay
in the file with `superseded_by`, so history is never silently deleted.

The handoff is a single compact JSON document answering: what were we
doing, what is done, what remains, what was discovered, what was decided,
what happens next, what verification is outstanding.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from lord.query import tokenize
from lord.report import CONFIRMED, ERROR, INFERRED, INFO, OK, UNKNOWN, WARN, Finding, Report

STATE_DIR = Path("docs") / "state"
MEMORY_FILE = STATE_DIR / "memory.jsonl"
HANDOFF_FILE = STATE_DIR / "handoff.json"

CATEGORIES = ("decision", "fact", "discovery", "trap", "convention", "unresolved", "verification")
STATUSES = ("confirmed", "evidenced", "inferred", "temporary", "unresolved", "superseded", "deprecated")
CURRENT_STATUSES = ("confirmed", "evidenced", "inferred", "temporary", "unresolved")
EVIDENCE_REQUIRED = ("confirmed", "evidenced")
TERMINAL_STATUSES = ("superseded", "deprecated")
MAX_STATEMENT_CHARS = 300
ID_RE = re.compile(r"^M-\d{4,}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CONFIDENCE_OF_STATUS = {"confirmed": CONFIRMED, "evidenced": INFERRED, "inferred": INFERRED, "temporary": INFERRED, "unresolved": UNKNOWN, "superseded": UNKNOWN, "deprecated": UNKNOWN}
HANDOFF_FIELDS = ("doing", "done", "remaining", "discovered", "decided", "next", "verification")


@dataclass
class Item:
    id: str
    category: str
    statement: str
    status: str
    created: str
    updated: str
    evidence: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    key: str = ""
    supersedes: str = ""
    superseded_by: str = ""
    expires: str = ""
    context: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v not in ("", [], None)}

    def is_current(self, today: str | None = None) -> bool:
        if self.status not in CURRENT_STATUSES:
            return False
        if self.status == "temporary" and self.expires and self.expires < (today or date.today().isoformat()):
            return False
        return True


def validate_item(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["item must be an object"]
    for required in ("id", "category", "statement", "status", "created", "updated"):
        if not data.get(required):
            errors.append(f"missing {required}")
    if data.get("id") and not ID_RE.match(str(data["id"])):
        errors.append(f"id {data['id']!r} must look like M-0001")
    if data.get("category") not in CATEGORIES:
        errors.append(f"category must be one of {', '.join(CATEGORIES)}")
    if data.get("status") not in STATUSES:
        errors.append(f"status must be one of {', '.join(STATUSES)}")
    statement = str(data.get("statement", ""))
    if len(statement) > MAX_STATEMENT_CHARS:
        errors.append(f"statement longer than {MAX_STATEMENT_CHARS} characters; put detail in evidence or a decision record")
    if "\n" in statement:
        errors.append("statement must be a single line")
    evidence = data.get("evidence", [])
    if not isinstance(evidence, list) or not all(isinstance(e, str) and e for e in evidence):
        errors.append("evidence must be a list of non-empty strings")
    elif data.get("status") in EVIDENCE_REQUIRED and not evidence:
        errors.append(f"status {data.get('status')} requires at least one evidence entry")
    for list_field in ("paths", "symbols", "tags"):
        value = data.get(list_field, [])
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            errors.append(f"{list_field} must be a list of strings")
    for date_field in ("created", "updated", "expires"):
        value = data.get(date_field, "")
        if value and not DATE_RE.match(str(value)):
            errors.append(f"{date_field} must be YYYY-MM-DD")
    if data.get("status") == "temporary" and not data.get("expires"):
        errors.append("temporary items need an expires date")
    if data.get("status") == "superseded" and not data.get("superseded_by"):
        errors.append("superseded items need superseded_by")
    return errors


class Store:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.path = self.root / MEMORY_FILE
        self.items: dict[str, Item] = {}
        self.load_errors: list[str] = []

    # -- persistence --------------------------------------------------------------
    def load(self) -> "Store":
        self.items, self.load_errors = {}, []
        if not self.path.is_file():
            return self
        for number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except ValueError as exc:
                self.load_errors.append(f"line {number}: invalid JSON ({exc})")
                continue
            errors = validate_item(data)
            if errors:
                self.load_errors.append(f"line {number} ({data.get('id', '?')}): " + "; ".join(errors))
                continue
            known = {f for f in Item.__dataclass_fields__}
            self.items[data["id"]] = Item(**{k: v for k, v in data.items() if k in known})
        return self

    def save(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps(self.items[k].to_dict(), ensure_ascii=False) for k in sorted(self.items)]
        self.path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8", newline="\n")
        return self.path

    def next_id(self) -> str:
        numbers = [int(k.split("-")[1]) for k in self.items if ID_RE.match(k)]
        return f"M-{(max(numbers) + 1 if numbers else 1):04d}"

    # -- writes ---------------------------------------------------------------------
    def add(self, category: str, statement: str, status: str, evidence: list[str] | None = None, paths: list[str] | None = None,
            symbols: list[str] | None = None, tags: list[str] | None = None, key: str = "", expires: str = "", context: str = "",
            supersedes: str = "", today: str | None = None) -> Item:
        today = today or date.today().isoformat()
        item = Item(id=self.next_id(), category=category, statement=statement.strip(), status=status, created=today, updated=today,
                    evidence=list(evidence or []), paths=[p.replace("\\", "/") for p in (paths or [])], symbols=list(symbols or []),
                    tags=sorted({t.lower() for t in (tags or [])}), key=key, expires=expires, context=context, supersedes=supersedes)
        errors = validate_item(item.to_dict())
        if errors:
            raise ValueError("; ".join(errors))
        if supersedes:
            old = self.items.get(supersedes)
            if old is None:
                raise ValueError(f"cannot supersede unknown item {supersedes}")
            if old.status in TERMINAL_STATUSES:
                raise ValueError(f"{supersedes} is already {old.status}")
            old.status, old.superseded_by, old.updated = "superseded", item.id, today
            # the successor is about the same subject unless told otherwise
            item.key = item.key or old.key
            item.paths = item.paths or list(old.paths)
            item.symbols = item.symbols or list(old.symbols)
            item.tags = item.tags or list(old.tags)
        self.items[item.id] = item
        return item

    def update(self, item_id: str, status: str | None = None, evidence: list[str] | None = None, statement: str | None = None, today: str | None = None) -> Item:
        item = self.items.get(item_id)
        if item is None:
            raise ValueError(f"unknown item {item_id}")
        if item.status in TERMINAL_STATUSES:
            raise ValueError(f"{item_id} is {item.status}; supersede or add a new item instead")
        if status in TERMINAL_STATUSES and status == "superseded":
            raise ValueError("use supersede to mark an item superseded")
        if evidence:
            item.evidence.extend(e for e in evidence if e not in item.evidence)
        if statement:
            item.statement = statement.strip()
        if status:
            item.status = status
        item.updated = today or date.today().isoformat()
        errors = validate_item(item.to_dict())
        if errors:
            raise ValueError("; ".join(errors))
        return item

    # -- reads ----------------------------------------------------------------------
    def current(self, today: str | None = None) -> list[Item]:
        return [i for i in self.items.values() if i.is_current(today)]

    def conflicts(self, today: str | None = None) -> list[tuple[str, list[Item]]]:
        by_key: dict[str, list[Item]] = {}
        for item in self.current(today):
            if item.key:
                by_key.setdefault(item.key, []).append(item)
        return [(key, sorted(group, key=lambda i: i.id)) for key, group in sorted(by_key.items()) if len(group) > 1]

    def check(self, today: str | None = None) -> Report:
        report = Report(title="memory check", meta={"file": str(self.path), "items": len(self.items)})
        for error in self.load_errors:
            report.add(Finding(kind="invalid-item", summary=error, severity=ERROR, confidence=CONFIRMED, consequence="the item is ignored until fixed"))
        for item in self.items.values():
            if item.supersedes and item.supersedes not in self.items:
                report.add(Finding(kind="dangling-link", summary=f"{item.id} supersedes unknown {item.supersedes}", severity=WARN, confidence=CONFIRMED))
            if item.superseded_by and item.superseded_by not in self.items:
                report.add(Finding(kind="dangling-link", summary=f"{item.id} superseded_by unknown {item.superseded_by}", severity=WARN, confidence=CONFIRMED))
            if item.status == "temporary" and not item.is_current(today):
                report.add(Finding(kind="expired", summary=f"{item.id} temporary item expired on {item.expires}: {item.statement[:80]}", severity=INFO, confidence=CONFIRMED,
                                   recommendation="confirm it with evidence, supersede it, or deprecate it"))
            if item.status == "inferred" and item.category in ("fact", "convention"):
                report.add(Finding(kind="weak-fact", summary=f"{item.id} is an inferred {item.category}: {item.statement[:80]}", severity=INFO, confidence=INFERRED,
                                   recommendation="add evidence and confirm, or keep treating it as a hypothesis"))
        for key, group in self.conflicts(today):
            report.add(Finding(kind="conflict", summary=f"key {key!r} has {len(group)} current items: " + ", ".join(i.id for i in group), severity=WARN, confidence=CONFIRMED,
                               evidence=[f"{i.id}: {i.statement[:100]}" for i in group], consequence="two current statements about one subject",
                               recommendation="`lord memory supersede <old> --statement ...` to keep one"))
        unresolved = [i for i in self.current(today) if i.status == "unresolved" or i.category == "unresolved"]
        if unresolved:
            report.add(Finding(kind="open", summary=f"{len(unresolved)} unresolved item(s)", severity=INFO, confidence=CONFIRMED, evidence=[f"{i.id}: {i.statement[:100]}" for i in unresolved[:10]]))
        if not report.findings:
            report.add(Finding(kind="memory", summary=f"{len(self.items)} item(s), all valid, no conflicts", severity=OK, confidence=CONFIRMED))
        report.meta["conflicts"] = [k for k, _ in self.conflicts(today)]
        return report

    def query(self, text: str = "", path: str = "", symbol: str = "", category: str = "", tag: str = "", status: str = "",
              include_all: bool = False, limit: int = 10, today: str | None = None) -> Report:
        """Deterministic retrieval: exact symbol > path > tag > category/text overlap > recency."""
        terms = tokenize(text) if text else set()
        rel = path.replace("\\", "/").strip("/") if path else ""
        scored: list[tuple[float, Item, list[str]]] = []
        for item in self.items.values():
            if not include_all and not item.is_current(today):
                continue
            if status and item.status != status:
                continue
            if category and item.category != category:
                continue
            if tag and tag.lower() not in item.tags:
                continue
            score, why = 0.0, []
            if symbol and (symbol in item.symbols or any(s.endswith("." + symbol) or s.endswith("::" + symbol) for s in item.symbols)):
                score += 10
                why.append(f"symbol {symbol}")
            if rel:
                for p in item.paths:
                    p_norm = p.strip("/")
                    if rel == p_norm or rel.startswith(p_norm + "/") or p_norm.startswith(rel + "/"):
                        score += 6 if rel == p_norm else 4
                        why.append(f"path {p}")
                        break
            if terms:
                overlap = terms & (tokenize(item.statement) | set(item.tags) | tokenize(" ".join(item.symbols)))
                if overlap:
                    score += len(overlap)
                    why.append("terms " + ", ".join(sorted(overlap)[:5]))
            if tag:
                score += 4
                why.append(f"tag {tag}")
            if category:
                score += 2
            if (symbol or rel or terms) and score == 0:
                continue
            scored.append((score, item, why))
        scored.sort(key=lambda t: (-t[0], t[1].updated, t[1].id), reverse=False)
        scored.sort(key=lambda t: (-t[0], _date_key(t[1].updated), t[1].id))
        report = Report(title="memory", meta={"file": str(self.path), "matched": len(scored), "shown": min(limit, len(scored))})
        for score, item, why in scored[:limit]:
            severity = WARN if item.category in ("trap", "unresolved") or item.status == "unresolved" else OK
            report.add(Finding(kind=f"{item.category}", summary=f"{item.id} [{item.status}] {item.statement}", severity=severity,
                               confidence=CONFIDENCE_OF_STATUS[item.status],
                               evidence=item.evidence[:4] + ([f"matched: {'; '.join(why)}"] if why else []),
                               data={"id": item.id, "score": score, "paths": item.paths, "symbols": item.symbols, "tags": item.tags, "key": item.key,
                                     "updated": item.updated, "supersedes": item.supersedes}))
        if not scored:
            report.add(Finding(kind="memory", summary="no memory items match", severity=INFO, confidence=CONFIRMED,
                               consequence="either nothing durable is known about this area, or it was recorded under other terms"))
        return report


def _date_key(value: str) -> str:
    # newest first: invert lexical order of ISO dates
    return "".join(chr(0x7A - (ord(c) - 0x30)) if c.isdigit() else c for c in value)


# --- handoff ----------------------------------------------------------------------------

def _git_state(root: Path) -> dict[str, str]:
    out = {}
    for name, args in (("branch", ["branch", "--show-current"]), ("commit", ["rev-parse", "--short", "HEAD"])):
        try:
            completed = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace")
            out[name] = completed.stdout.strip() if completed.returncode == 0 else ""
        except OSError:
            out[name] = ""
    return out


def load_handoff(root: Path) -> dict[str, Any]:
    path = root / HANDOFF_FILE
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def write_handoff(root: Path, fields: dict[str, Any], replace: bool = False, today: str | None = None) -> dict[str, Any]:
    """Merge (or replace) handoff fields. Lists append unique entries; strings replace."""
    current = {} if replace else load_handoff(root)
    for name in HANDOFF_FIELDS:
        value = fields.get(name)
        if value is None or value == "" or value == []:
            continue
        if name in ("doing", "verification") or not isinstance(value, list):
            current[name] = value
        else:
            existing = [v for v in current.get(name, []) if isinstance(v, str)]
            current[name] = existing + [v for v in value if v not in existing]
    current["updated"] = today or date.today().isoformat()
    current.update(_git_state(root))
    path = root / HANDOFF_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return current


def clear_handoff(root: Path) -> bool:
    path = root / HANDOFF_FILE
    if path.is_file():
        path.unlink()
        return True
    return False


def handoff_report(root: Path) -> Report:
    data = load_handoff(root)
    report = Report(title="handoff", meta={"file": str(root / HANDOFF_FILE), "present": bool(data)})
    if not data:
        report.add(Finding(kind="handoff", summary="no unfinished work recorded", severity=OK, confidence=CONFIRMED))
        return report
    report.meta.update({k: data.get(k, "") for k in ("updated", "branch", "commit")})
    report.add(Finding(kind="doing", summary=str(data.get("doing", "")) or "(not stated)", severity=INFO, confidence=CONFIRMED,
                       evidence=[f"updated {data.get('updated', '?')} on {data.get('branch', '?')}@{data.get('commit', '?')}"]))
    for name in ("done", "remaining", "discovered", "decided", "next"):
        values = data.get(name) or []
        if values:
            report.add(Finding(kind=name, summary=f"{len(values)} item(s)", severity=WARN if name == "remaining" else INFO, confidence=CONFIRMED, evidence=[str(v) for v in values][:12]))
    verification = data.get("verification")
    if verification:
        summary = verification if isinstance(verification, str) else f"verdict {verification.get('verdict', '?')}"
        evidence = [] if isinstance(verification, str) else [str(o) for o in verification.get("outstanding", [])][:8]
        report.add(Finding(kind="verification", summary=summary, severity=WARN if "not" in summary else OK, confidence=CONFIRMED, evidence=evidence))
    return report
