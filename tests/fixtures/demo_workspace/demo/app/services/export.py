"""CSV export of a month's transactions."""

from __future__ import annotations

import csv
import io

from app.services.transactions import TransactionService

COLUMNS = ("date", "kind", "category", "description", "amount")


class ExportService:
    def __init__(self, transactions: TransactionService) -> None:
        self.transactions = transactions

    def monthly_csv(self, year: int, month: int) -> str:
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(COLUMNS)
        for item in self.transactions.in_month(year, month):
            writer.writerow([item.date.isoformat(), item.kind, item.category, item.description, f"{item.amount_cents / 100:.2f}"])
        return buffer.getvalue()
