"""Repository index: inventory plus per-file extractions, persisted as JSON.

The index lives in `<root>/.lord/index.json` (machine-local, ignored by Git)
and is rebuilt incrementally: a file is re-extracted only when its size or
modification time changed and its content hash differs. Queries call
`ensure_index`, so results always reflect the current working tree.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from lord.config import LordConfig
from lord.extractors import SUPPORTED, extract
from lord.inventory import FileRecord, Inventory, build_inventory
from lord.paths import state_dir
from lord.report import INFO, OK, WARN, Finding, Report
from lord.symbols import Extraction, Symbol

INDEX_VERSION = 1
INDEX_FILENAME = "index.json"


@dataclass
class FileEntry:
    record: FileRecord
    size: int
    mtime_ns: int
    sha1: str
    extraction: Extraction | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "record": self.record.__dict__,
            "size": self.size,
            "mtime_ns": self.mtime_ns,
            "sha1": self.sha1,
            "extraction": self.extraction.to_dict() if self.extraction else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FileEntry":
        return cls(
            record=FileRecord(**data["record"]),
            size=data["size"],
            mtime_ns=data["mtime_ns"],
            sha1=data["sha1"],
            extraction=Extraction.from_dict(data["extraction"]) if data.get("extraction") else None,
        )


@dataclass
class Index:
    root: str
    inventory: Inventory
    entries: dict[str, FileEntry] = field(default_factory=dict)
    built_at: float = 0.0
    version: int = INDEX_VERSION

    # -- lookups ---------------------------------------------------------------
    def extractions(self) -> Iterator[Extraction]:
        for entry in self.entries.values():
            if entry.extraction is not None:
                yield entry.extraction

    def symbols(self) -> Iterator[Symbol]:
        for ex in self.extractions():
            yield from ex.symbols

    def symbols_named(self, name: str) -> list[Symbol]:
        return [s for s in self.symbols() if s.name == name or s.qualname == name or s.qualname.endswith("." + name)]

    def symbols_in(self, path: str) -> list[Symbol]:
        entry = self.entries.get(path)
        return list(entry.extraction.symbols) if entry and entry.extraction else []

    def extraction_for(self, path: str) -> Extraction | None:
        entry = self.entries.get(path)
        return entry.extraction if entry else None

    def importers_of(self, path: str) -> list[tuple[str, Any]]:
        """(importing file, Import) pairs whose import resolves to `path`."""
        found = []
        for ex in self.extractions():
            for imp in ex.imports:
                if imp.resolved == path:
                    found.append((ex.file, imp))
        return found

    def unsupported_languages(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for entry in self.entries.values():
            rec = entry.record
            if rec.analyzable and rec.language not in SUPPORTED:
                counts[rec.language] = counts.get(rec.language, 0) + 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "root": self.root,
            "built_at": self.built_at,
            "inventory": self.inventory.to_dict(),
            "entries": {path: entry.to_dict() for path, entry in self.entries.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Index":
        return cls(
            root=data["root"],
            inventory=Inventory.from_dict(data["inventory"]),
            entries={path: FileEntry.from_dict(e) for path, e in data.get("entries", {}).items()},
            built_at=data.get("built_at", 0.0),
            version=data.get("version", 0),
        )


def index_path(root: Path, state: Path | None = None) -> Path:
    return (state or state_dir(root)) / INDEX_FILENAME


def load_index(root: Path, state: Path | None = None) -> Index | None:
    path = index_path(root, state)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if data.get("version") != INDEX_VERSION or data.get("root") != str(root.resolve()):
        return None
    return Index.from_dict(data)


def save_index(index: Index, root: Path, state: Path | None = None) -> Path:
    path = index_path(root, state)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(index.to_dict(), separators=(",", ":")), encoding="utf-8")
    return path


def build_index(config: LordConfig, previous: Index | None = None, state: Path | None = None, save: bool = True) -> tuple[Index, Report]:
    """Build (or incrementally refresh) the index and persist it."""
    root = config.root.resolve()
    inventory = build_inventory(config)
    index = Index(root=str(root), inventory=inventory, built_at=time.time())
    report = Report(title="LORD index", meta={"root": str(root)})
    reused = extracted = failed = 0

    for record in inventory.files:
        full = root / record.path
        try:
            stat = full.stat()
        except OSError:
            continue
        old = previous.entries.get(record.path) if previous else None
        if old and old.size == stat.st_size and old.mtime_ns == stat.st_mtime_ns:
            old.record = record
            index.entries[record.path] = old
            reused += 1
            continue

        try:
            data = full.read_bytes()
        except OSError:
            continue
        sha1 = hashlib.sha1(data).hexdigest()
        if old and old.sha1 == sha1:
            old.size, old.mtime_ns, old.record = stat.st_size, stat.st_mtime_ns, record
            index.entries[record.path] = old
            reused += 1
            continue

        extraction = None
        if record.analyzable and record.language in SUPPORTED:
            extraction = extract(root, record.path, record.language, data.decode("utf-8", "replace"))
            extracted += 1
            if extraction.error:
                failed += 1
        index.entries[record.path] = FileEntry(record, stat.st_size, stat.st_mtime_ns, sha1, extraction)

    if save:
        report.meta["index_path"] = str(save_index(index, root, state))

    report.add(Finding(kind="index", summary=f"{len(index.entries)} files indexed ({extracted} extracted, {reused} reused)", severity=OK,
                       data={"files": len(index.entries), "extracted": extracted, "reused": reused, "symbols": sum(1 for _ in index.symbols())}))
    if failed:
        errors = [f"{ex.file}: {ex.error}" for ex in index.extractions() if ex.error]
        report.add(Finding(kind="parse-errors", summary=f"{failed} file(s) could not be parsed; their symbols are unknown", severity=WARN, confidence="unknown", evidence=errors[:20]))
    unsupported = index.unsupported_languages()
    if unsupported:
        report.add(Finding(kind="unsupported-languages", summary="analysis unavailable for: " + ", ".join(f"{k} ({v})" for k, v in sorted(unsupported.items())),
                           severity=INFO, confidence="unknown", consequence="symbols in these files are not indexed; text search still covers them"))
    return index, report


def ensure_index(config: LordConfig, state: Path | None = None, rebuild: bool = False) -> Index:
    """Load the persisted index and refresh it incrementally (or rebuild)."""
    root = config.root.resolve()
    previous = None if rebuild else load_index(root, state)
    index, _ = build_index(config, previous=previous, state=state)
    return index
