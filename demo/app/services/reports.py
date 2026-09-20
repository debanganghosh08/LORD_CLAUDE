"""Monthly reporting built on top of the transaction service."""

from __future__ import annotations

from app.models import MonthlySummary
from app.services.transactions import TransactionService
from app.utils.money import format_amount


class ReportService:
    def __init__(self, transactions: TransactionService) -> None:
        self.transactions = transactions

    def monthly_summary(self, year: int, month: int) -> MonthlySummary:
        items = self.transactions.in_month(year, month)
        by_category: dict[str, int] = {}
        for item in items:
            if item.kind == "expense":
                by_category[item.category] = by_category.get(item.category, 0) + item.amount_cents
        return MonthlySummary(
            year=year,
            month=month,
            expense_total=self.transactions.total(items, "expense"),
            income_total=self.transactions.total(items, "income"),
            by_category=dict(sorted(by_category.items())),
        )

    def render(self, summary: MonthlySummary) -> list[str]:
        lines = [f"{summary.year}-{summary.month:02d}: expenses {format_amount(summary.expense_total)}, income {format_amount(summary.income_total)}, net {format_amount(summary.net)}"]
        for category, cents in summary.by_category.items():
            lines.append(f"  {category}: {format_amount(cents)}")
        return lines
