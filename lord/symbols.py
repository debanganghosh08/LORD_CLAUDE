"""Symbol model: the entities and relationships LORD discovers in source.

Everything here is plain data with explicit confidence so it can be stored in
the index, rendered in reports and reasoned about by a model. Relationships
are only recorded when an extractor saw evidence for them.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from lord.report import CONFIRMED

SYMBOL_KINDS = (
    "function", "method", "class", "interface", "type", "enum",
    "constant", "variable", "route",
)


@dataclass
class Symbol:
    name: str
    kind: str
    file: str            # workspace-relative POSIX path
    line: int
    qualname: str        # e.g. "UserService.create"
    language: str
    confidence: str = CONFIRMED
    end_line: int | None = None
    parent: str = ""     # qualname of enclosing class/function, if any
    signature: str = ""  # short human-readable signature or decorator info
    exported: bool = True
    doc: str = ""        # first line of docstring/comment, if any

    @property
    def id(self) -> str:
        return f"{self.file}::{self.qualname}"


@dataclass
class Import:
    module: str                  # specifier as written ("pkg.validators", "./lib/helper")
    names: list[str]             # imported names ([] for whole-module import)
    aliases: list[str]           # local binding names, parallel to `names`
    line: int
    resolved: str | None = None  # workspace-relative file the import points at, if found
    confidence: str = CONFIRMED
    is_relative: bool = False


@dataclass
class Ref:
    """A name used at a location: a call or a plain reference."""
    name: str
    line: int
    scope: str = ""              # qualname of the enclosing symbol, "" at module level


@dataclass
class Base:
    qualname: str                # class qualname
    base: str                    # base/interface name as written
    line: int
    relation: str = "extends"    # "extends" or "implements"


@dataclass
class Extraction:
    file: str
    language: str
    confidence: str                          # confirmed (AST), inferred (heuristic), unknown (failed)
    symbols: list[Symbol] = field(default_factory=list)
    imports: list[Import] = field(default_factory=list)
    calls: list[Ref] = field(default_factory=list)
    references: list[Ref] = field(default_factory=list)
    bases: list[Base] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Extraction":
        return cls(
            file=data["file"],
            language=data["language"],
            confidence=data["confidence"],
            symbols=[Symbol(**s) for s in data.get("symbols", [])],
            imports=[Import(**i) for i in data.get("imports", [])],
            calls=[Ref(**r) for r in data.get("calls", [])],
            references=[Ref(**r) for r in data.get("references", [])],
            bases=[Base(**b) for b in data.get("bases", [])],
            exports=list(data.get("exports", [])),
            error=data.get("error", ""),
        )
