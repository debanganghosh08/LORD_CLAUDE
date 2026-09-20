"""Context assembly: high-signal context for one target and intent.

This is the interface future phases build on, not an autonomous context
engine. It composes what already exists, each section capped so the result
stays small: unfinished work (handoff), relevant durable memory, the
pre-edit brief (impact, references, reuse decision), the skills whose
descriptions match the intent, and the always-on rules. Progressive
disclosure: every section names the command that gives the detail.
"""

from __future__ import annotations

import re
from pathlib import Path

from lord.config import LordConfig
from lord.index import Index
from lord.memory import Store, load_handoff
from lord.query import tokenize
from lord.report import CONFIRMED, INFERRED, INFO, OK, WARN, Finding, Report
from lord.review import brief

SECTION_LIMITS = {"handoff": 1, "memory": 6, "brief": 18, "skills": 3, "rules": 3}
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.S)


def _frontmatter(path: Path) -> dict[str, str]:
    try:
        match = FRONTMATTER_RE.match(path.read_text(encoding="utf-8"))
    except OSError:
        return {}
    fields: dict[str, str] = {}
    for line in (match.group(1).splitlines() if match else []):
        if ":" in line and not line.startswith((" ", "-")):
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip()
    return fields


def matching_skills(root: Path, intent: str, limit: int) -> list[tuple[str, str, int]]:
    """(name, description, overlap) for skills whose description shares terms with the intent."""
    terms = tokenize(intent) if intent else set()
    found = []
    for skill_md in sorted((root / ".agents" / "skills").glob("*/SKILL.md")):
        fm = _frontmatter(skill_md)
        name = fm.get("name") or skill_md.parent.name
        description = fm.get("description", "")
        overlap = len(terms & tokenize(description)) if terms else 0
        found.append((name, description, overlap))
    found.sort(key=lambda t: (-t[2], t[0]))
    return [f for f in found[:limit] if f[2] > 0 or not intent]


def always_on_rules(root: Path) -> list[str]:
    names = []
    for rule in sorted((root / ".agents" / "rules").glob("*.md")):
        if _frontmatter(rule).get("trigger") == "always_on":
            names.append(rule.stem)
    return names


def assemble(config: LordConfig, index: Index, target: str, intent: str = "", names: list[str] | None = None) -> Report:
    root = config.root.resolve()
    report = Report(title=f"context: {target}", meta={"root": str(root), "intent": intent, "sections": {}})

    handoff = load_handoff(root)
    if handoff:
        remaining = handoff.get("remaining") or []
        report.add(Finding(kind="handoff", summary=f"unfinished work: {handoff.get('doing', '(unstated)')}", severity=WARN if remaining else INFO, confidence=CONFIRMED,
                           evidence=[f"remaining: {r}" for r in remaining[:4]] + [f"next: {n}" for n in (handoff.get('next') or [])[:2]],
                           recommendation="`python -m lord handoff show` for the full record"))
    report.meta["sections"]["handoff"] = 1 if handoff else 0

    store = Store(root).load()
    symbol = "" if "/" in target or "\\" in target or "." in Path(target).name and target.endswith((".py", ".js", ".ts", ".tsx", ".jsx")) else target.split(".")[-1]
    path = target if not symbol else ""
    memory = store.query(text=intent, path=path, symbol=symbol, limit=SECTION_LIMITS["memory"])
    hits = [f for f in memory.findings if f.kind != "memory"]
    if not hits and symbol:
        try:
            files = {s.file for s in index.symbols_named(symbol)}
            for file in sorted(files)[:2]:
                hits.extend(f for f in store.query(path=file, text=intent, limit=3).findings if f.kind != "memory")
        except Exception:  # noqa: BLE001
            pass
    for f in hits[:SECTION_LIMITS["memory"]]:
        f.recommendation = f.recommendation or "`python -m lord memory query --path <file>` for more"
        report.add(f)
    report.meta["sections"]["memory"] = len(hits[:SECTION_LIMITS["memory"]])

    detail = brief(config, index, target, intent=intent, names=names)
    kept = 0
    for f in detail.findings:
        if f.kind in ("next", "workspace-state"):
            continue
        if kept >= SECTION_LIMITS["brief"]:
            break
        report.add(f)
        kept += 1
    report.meta["sections"]["brief"] = kept
    report.meta["reuse_decision"] = detail.meta.get("reuse_decision")
    report.meta["overall_confidence"] = detail.meta.get("overall_confidence")
    for key in ("direct_callers", "dependents", "tests"):
        if detail.meta.get(key):
            report.meta[key] = detail.meta[key]

    skills = matching_skills(root, intent, SECTION_LIMITS["skills"])
    if skills:
        report.add(Finding(kind="skills", summary="skills matching the intent: " + ", ".join(n for n, _, _ in skills), severity=OK, confidence=INFERRED,
                           evidence=[f"{n}: {d[:110]}" for n, d, _ in skills]))
    report.meta["sections"]["skills"] = len(skills)
    rules = always_on_rules(root)
    if rules:
        report.add(Finding(kind="rules", summary="always-on rules: " + ", ".join(rules), severity=OK, confidence=CONFIRMED))
    report.meta["sections"]["rules"] = len(rules)
    report.add(Finding(kind="next", summary="open the files the brief points at; record durable discoveries with `lord memory add`; update `lord handoff` before stopping", severity=INFO, confidence=CONFIRMED))
    return report
