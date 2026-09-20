"""Domain models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date


@dataclass(frozen=True)
class Transaction:
    id: int
    date: date
    amount_cents: int
    kind: str          # "expense" or "income"
    category: str
    description: str

    def to_dict(self) -> dict:
        data = asdict(self)
        data["date"] = self.date.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Transaction":
        return cls(
            id=int(data["id"]),
            date=date.fromisoformat(data["date"]),
            amount_cents=int(data["amount_cents"]),
            kind=data["kind"],
            category=data["category"],
            description=data["description"],
        )


@dataclass
class MonthlySummary:
    year: int
    month: int
    expense_total: int
    income_total: int
    by_category: dict[str, int] = field(default_factory=dict)

    @property
    def net(self) -> int:
        return self.income_total - self.expense_total
