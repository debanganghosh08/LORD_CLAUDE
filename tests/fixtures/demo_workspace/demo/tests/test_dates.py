from datetime import date

import pytest

from app.utils.dates import in_range, month_bounds, parse_date


def test_parse_date():
    assert parse_date("2026-03-15") == date(2026, 3, 15)
    assert parse_date(" 2026-01-01 ") == date(2026, 1, 1)
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        parse_date("15/03/2026")


def test_month_bounds_march():
    assert month_bounds(2026, 3) == (date(2026, 3, 1), date(2026, 3, 31))


def test_in_range_is_inclusive():
    assert in_range(date(2026, 3, 1), date(2026, 3, 1), date(2026, 3, 31))
    assert in_range(date(2026, 3, 31), date(2026, 3, 1), date(2026, 3, 31))
    assert not in_range(date(2026, 4, 1), date(2026, 3, 1), date(2026, 3, 31))
