"""Shared report model.

Every LORD analysis (doctor, forensics, reuse, impact, review) returns a
`Report` made of `Finding`s so that a model, a human, a test, or a hook can
consume the same structure. Confidence is always explicit: LORD never presents
an inference as a confirmed fact, and it never turns "could not analyze" into
"nothing found".
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

# Confidence vocabulary shared by tooling and specialist agents.
CONFIRMED = "confirmed"  # backed by direct evidence (parsed source, git, fs)
INFERRED = "inferred"    # heuristic evidence; may be wrong
UNKNOWN = "unknown"      # analysis unavailable or inconclusive
CONFIDENCE_LEVELS = (CONFIRMED, INFERRED, UNKNOWN)

# Severity vocabulary for findings that describe problems.
OK = "ok"
INFO = "info"
WARN = "warn"
ERROR = "error"
SEVERITIES = (OK, INFO, WARN, ERROR)


@dataclass
class Finding:
    kind: str                    # short machine-readable tag, e.g. "git-root"
    summary: str                 # one sentence, human readable
    severity: str = INFO
    confidence: str = CONFIRMED
    evidence: list[str] = field(default_factory=list)   # file:line, commands, facts
    consequence: str = ""        # what this means for the task, if anything
    recommendation: str = ""     # what to do about it, if anything
    data: dict[str, Any] = field(default_factory=dict)  # structured extras

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f"invalid severity {self.severity!r}")
        if self.confidence not in CONFIDENCE_LEVELS:
            raise ValueError(f"invalid confidence {self.confidence!r}")


@dataclass
class Report:
    title: str
    findings: list[Finding] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def add(self, finding: Finding) -> Finding:
        self.findings.append(finding)
        return finding

    def extend(self, findings: Iterable[Finding]) -> None:
        self.findings.extend(findings)

    @property
    def worst_severity(self) -> str:
        order = {s: i for i, s in enumerate(SEVERITIES)}
        return max((f.severity for f in self.findings), key=order.__getitem__, default=OK)

    @property
    def has_errors(self) -> bool:
        return any(f.severity == ERROR for f in self.findings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "worst_severity": self.worst_severity,
            "meta": self.meta,
            "findings": [asdict(f) for f in self.findings],
        }

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    def to_markdown(self) -> str:
        lines = [f"## {self.title}", ""]
        for key, value in self.meta.items():
            lines.append(f"- {key}: {value}")
        if self.meta:
            lines.append("")
        if not self.findings:
            lines.append("_No findings._")
        for f in self.findings:
            marker = {OK: "OK", INFO: "INFO", WARN: "WARN", ERROR: "ERROR"}[f.severity]
            lines.append(f"### [{marker}] {f.kind}: {f.summary}")
            lines.append(f"- confidence: {f.confidence}")
            for item in f.evidence:
                lines.append(f"- evidence: {item}")
            if f.consequence:
                lines.append(f"- consequence: {f.consequence}")
            if f.recommendation:
                lines.append(f"- recommendation: {f.recommendation}")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"
