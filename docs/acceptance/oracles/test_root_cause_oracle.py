"""ORACLE for acceptance TEST 03 (root cause). Not part of the demo suite.

Expected to FAIL on the unmodified demo and PASS once the real cause is
fixed. Run from the LORD root:

    python -m pytest docs/acceptance/oracles -q -p no:cacheprovider

The planted defect and its expected fix are described in
docs/acceptance/PHASE-8A-TEST-PLAN.md (TEST 03, "Oracle"), not in the demo
README, so the evaluated agent has to find it.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

DEMO = Path(__file__).resolve().parents[3] / "demo"
if str(DEMO) not in sys.path:
    sys.path.insert(0, str(DEMO))

from app.api.handlers import Services  # noqa: E402
from app.repository import InMemoryRepository  # noqa: E402
from app.utils.dates import month_bounds  # noqa: E402

FEB_AND_MARCH = [
    {"date": "2026-02-27", "amount": "19.99", "kind": "expense", "category": "leisure", "description": "Cinema"},
    {"date": "2026-02-28", "amount": "1800.00", "kind": "income", "category": "salary", "description": "February salary"},
    {"date": "2026-03-02", "amount": "650.00", "kind": "expense", "category": "rent", "description": "Rent March"},
    {"date": "2026-04-30", "amount": "30.00", "kind": "expense", "category": "transport", "description": "Monthly pass"},
    {"date": "2026-05-01", "amount": "650.00", "kind": "expense", "category": "rent", "description": "Rent May"},
]


def _services() -> Services:
    services = Services(InMemoryRepository())
    for payload in FEB_AND_MARCH:
        services.transactions.add(payload)
    return services


def test_month_bounds_is_correct_for_every_month_length():
    assert month_bounds(2026, 2) == (date(2026, 2, 1), date(2026, 2, 28))
    assert month_bounds(2024, 2) == (date(2024, 2, 1), date(2024, 2, 29))
    assert month_bounds(2026, 4) == (date(2026, 4, 1), date(2026, 4, 30))
    assert month_bounds(2026, 12) == (date(2026, 12, 1), date(2026, 12, 31))


def test_february_report_excludes_march():
    services = _services()
    summary = services.reports.monthly_summary(2026, 2)
    assert summary.expense_total == 1999 and summary.income_total == 180000
    assert "rent" not in summary.by_category


def test_export_shares_the_fix():
    """The export goes through the same month selection: fixing only the report layer leaves this failing."""
    services = _services()
    lines = services.export.monthly_csv(2026, 4).splitlines()
    assert [line.split(",")[0] for line in lines[1:]] == ["2026-04-30"]
