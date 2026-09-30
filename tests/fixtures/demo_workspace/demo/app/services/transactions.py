"""Transaction use cases: create, list, select by month, total."""

from __future__ import annotations

from app.config import DEFAULT_PAGE_SIZE
from app.models import Transaction
from app.repository import Repository
from app.utils.dates import in_range, month_bounds, parse_date
from app.utils.money import parse_amount
from app.validation import ValidationError, validate_transaction


class TransactionService:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository

    def add(self, payload: dict) -> Transaction:
        errors = validate_transaction(payload)
        if errors:
            raise ValidationError(errors)
        transaction = Transaction(
            id=self.repository.next_id(),
            date=parse_date(payload["date"]),
            amount_cents=parse_amount(payload["amount"]),
            kind=payload["kind"],
            category=payload["category"],
            description=str(payload["description"]).strip(),
        )
        return self.repository.add(transaction)

    def list(self, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE) -> list[Transaction]:
        if page < 1 or page_size < 1:
            raise ValueError("page and page_size must be positive")
        items = self.repository.all()
        start = (page - 1) * page_size
        return items[start : start + page_size]

    def in_month(self, year: int, month: int) -> list[Transaction]:
        start, end = month_bounds(year, month)
        return [t for t in self.repository.all() if in_range(t.date, start, end)]

    @staticmethod
    def total(transactions: list[Transaction], kind: str) -> int:
        return sum(t.amount_cents for t in transactions if t.kind == kind)
