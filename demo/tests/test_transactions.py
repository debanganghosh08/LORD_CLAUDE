from datetime import date

import pytest

from app.config import DEFAULT_PAGE_SIZE
from app.repository import InMemoryRepository
from app.services.transactions import TransactionService
from app.validation import ValidationError


def test_add_assigns_ids_and_stores_cents(services):
    created = services.transactions.add({"date": "2026-03-16", "amount": "3.30", "kind": "expense", "category": "transport", "description": "  Bus  "})
    assert created.id == 7 and created.amount_cents == 330 and created.date == date(2026, 3, 16)
    assert created.description == "Bus"


def test_add_rejects_invalid_payload(services):
    with pytest.raises(ValidationError) as excinfo:
        services.transactions.add({"date": "2026-03-16", "amount": "0", "kind": "expense", "category": "transport", "description": "Bus"})
    assert excinfo.value.errors == ["amount must be greater than zero"]


def test_list_pages_in_date_order():
    service = TransactionService(InMemoryRepository())
    for day in range(1, 26):
        service.add({"date": f"2026-03-{day:02d}", "amount": "1.00", "kind": "expense", "category": "other", "description": f"day {day}"})
    first = service.list()
    assert len(first) == DEFAULT_PAGE_SIZE and first[0].date == date(2026, 3, 1)
    second = service.list(page=2)
    assert [t.date.day for t in second] == [21, 22, 23, 24, 25]
    with pytest.raises(ValueError):
        service.list(page=0)


def test_in_month_selects_march(services):
    march = services.transactions.in_month(2026, 3)
    assert [t.description for t in march] == ["Rent March", "Bakery", "Milk", "March salary"]


def test_totals_by_kind(services):
    march = services.transactions.in_month(2026, 3)
    assert services.transactions.total(march, "expense") == 65000 + 1250 + 750
    assert services.transactions.total(march, "income") == 180000
