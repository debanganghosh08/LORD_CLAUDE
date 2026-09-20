"""Request handlers: plain dicts in, plain dicts out. The HTTP server and the tests call these."""

from __future__ import annotations

from app.config import DEFAULT_PAGE_SIZE
from app.repository import Repository
from app.services.export import ExportService
from app.services.reports import ReportService
from app.services.transactions import TransactionService
from app.utils.money import format_amount
from app.validation import ValidationError


class ApiError(Exception):
    def __init__(self, status: int, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.status = status
        self.errors = errors


class Services:
    def __init__(self, repository: Repository) -> None:
        self.transactions = TransactionService(repository)
        self.reports = ReportService(self.transactions)
        self.export = ExportService(self.transactions)


def _int_param(query: dict, name: str, default: int | None = None) -> int:
    raw = query.get(name, default)
    if raw is None:
        raise ApiError(400, [f"{name} is required"])
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ApiError(400, [f"{name} must be an integer"]) from None


def create_transaction(services: Services, payload: dict) -> dict:
    try:
        transaction = services.transactions.add(payload)
    except ValidationError as exc:
        raise ApiError(400, exc.errors) from exc
    return transaction.to_dict()


def list_transactions(services: Services, query: dict) -> dict:
    page = _int_param(query, "page", 1)
    try:
        items = services.transactions.list(page=page, page_size=DEFAULT_PAGE_SIZE)
    except ValueError as exc:
        raise ApiError(400, [str(exc)]) from exc
    return {"items": [t.to_dict() for t in items], "page": page, "page_size": DEFAULT_PAGE_SIZE, "total": services.transactions.repository.count()}


def monthly_report(services: Services, query: dict) -> dict:
    year, month = _int_param(query, "year"), _int_param(query, "month")
    if not 1 <= month <= 12:
        raise ApiError(400, ["month must be between 1 and 12"])
    summary = services.reports.monthly_summary(year, month)
    return {
        "year": year,
        "month": month,
        "expense_total": format_amount(summary.expense_total),
        "income_total": format_amount(summary.income_total),
        "net": format_amount(summary.net),
        "by_category": {category: format_amount(cents) for category, cents in summary.by_category.items()},
        "lines": services.reports.render(summary),
    }


def export_csv(services: Services, query: dict) -> str:
    year, month = _int_param(query, "year"), _int_param(query, "month")
    return services.export.monthly_csv(year, month)
