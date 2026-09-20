import pytest

from app.api import handlers
from app.config import DEFAULT_PAGE_SIZE


def test_create_and_list(services):
    created = handlers.create_transaction(services, {"date": "2026-03-18", "amount": "4.20", "kind": "expense", "category": "leisure", "description": "Coffee"})
    assert created["id"] == 7 and created["amount_cents"] == 420
    listed = handlers.list_transactions(services, {})
    assert listed["page"] == 1 and listed["page_size"] == DEFAULT_PAGE_SIZE and listed["total"] == 7
    assert listed["items"][-1]["description"] == "March salary"


def test_create_maps_validation_errors_to_400(services):
    with pytest.raises(handlers.ApiError) as excinfo:
        handlers.create_transaction(services, {"date": "2026-03-18", "amount": "x", "kind": "expense", "category": "leisure", "description": "Coffee"})
    assert excinfo.value.status == 400 and excinfo.value.errors == ["amount 'x' is not a number"]


def test_monthly_report_formats_totals(services):
    report = handlers.monthly_report(services, {"year": "2026", "month": "3"})
    assert report["expense_total"] == "670.00 EUR" and report["net"] == "1130.00 EUR"
    assert report["by_category"] == {"groceries": "20.00 EUR", "rent": "650.00 EUR"}
    assert report["lines"][0].startswith("2026-03: expenses 670.00 EUR")


def test_report_requires_valid_month(services):
    with pytest.raises(handlers.ApiError) as excinfo:
        handlers.monthly_report(services, {"year": "2026", "month": "13"})
    assert excinfo.value.status == 400
    with pytest.raises(handlers.ApiError):
        handlers.monthly_report(services, {"year": "2026"})


def test_export_endpoint_returns_csv(services):
    text = handlers.export_csv(services, {"year": "2026", "month": "3"})
    assert text.startswith("date,kind,category,description,amount\n")
