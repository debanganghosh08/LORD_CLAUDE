def test_monthly_summary_march(services):
    summary = services.reports.monthly_summary(2026, 3)
    assert summary.expense_total == 67000 and summary.income_total == 180000 and summary.net == 113000
    assert summary.by_category == {"groceries": 2000, "rent": 65000}


def test_render_lines_use_shared_formatting(services):
    lines = services.reports.render(services.reports.monthly_summary(2026, 3))
    assert lines[0] == "2026-03: expenses 670.00 EUR, income 1800.00 EUR, net 1130.00 EUR"
    assert lines[1:] == ["  groceries: 20.00 EUR", "  rent: 650.00 EUR"]


def test_empty_month(services):
    summary = services.reports.monthly_summary(2025, 12)
    assert summary.expense_total == 0 and summary.by_category == {}
