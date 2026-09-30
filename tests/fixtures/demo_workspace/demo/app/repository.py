"""Persistence. `Repository` holds the shared behaviour; subclasses decide where data lives."""

from __future__ import annotations

import json
from pathlib import Path

from app.models import Transaction


class Repository:
    """In-memory index of transactions with id allocation and ordering.

    Subclasses override `_persist` to write the current state somewhere.
    """

    def __init__(self) -> None:
        self._items: dict[int, Transaction] = {}

    def next_id(self) -> int:
        return max(self._items, default=0) + 1

    def add(self, transaction: Transaction) -> Transaction:
        if transaction.id in self._items:
            raise ValueError(f"transaction {transaction.id} already exists")
        self._items[transaction.id] = transaction
        self._persist()
        return transaction

    def get(self, transaction_id: int) -> Transaction | None:
        return self._items.get(transaction_id)

    def all(self) -> list[Transaction]:
        return sorted(self._items.values(), key=lambda t: (t.date, t.id))

    def count(self) -> int:
        return len(self._items)

    def _persist(self) -> None:  # pragma: no cover - overridden where persistence exists
        return None


class InMemoryRepository(Repository):
    """Volatile store used by tests and the seed script."""


class JsonFileRepository(Repository):
    """Stores the whole ledger in one JSON file, rewritten on every change."""

    def __init__(self, path: str | Path) -> None:
        super().__init__()
        self.path = Path(path)
        if self.path.is_file():
            for item in json.loads(self.path.read_text(encoding="utf-8")):
                transaction = Transaction.from_dict(item)
                self._items[transaction.id] = transaction

    def _persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps([t.to_dict() for t in self.all()], indent=2), encoding="utf-8")
