from __future__ import annotations

import pytest

from app.api.handlers import Services
from app.repository import InMemoryRepository

MARCH = [
    {"date": "2026-03-02", "amount": "650.00", "kind": "expense", "category": "rent", "description": "Rent March"},
    {"date": "2026-03-15", "amount": "12.50", "kind": "expense", "category": "groceries", "description": "Bakery"},
    {"date": "2026-03-20", "amount": "7.50", "kind": "expense", "category": "groceries", "description": "Milk"},
    {"date": "2026-03-31", "amount": "1800.00", "kind": "income", "category": "salary", "description": "March salary"},
]
JANUARY = [
    {"date": "2026-01-05", "amount": "650.00", "kind": "expense", "category": "rent", "description": "Rent January"},
    {"date": "2026-01-31", "amount": "1800.00", "kind": "income", "category": "salary", "description": "January salary"},
]


@pytest.fixture
def services() -> Services:
    svc = Services(InMemoryRepository())
    for payload in JANUARY + MARCH:
        svc.transactions.add(payload)
    return svc
