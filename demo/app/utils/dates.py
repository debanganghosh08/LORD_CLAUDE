"""Date helpers shared by services, export and the API."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from app.config import DATE_FORMAT


def parse_date(value: str) -> date:
    """Parse an ISO date string; raises ValueError with a readable message."""
    try:
        return datetime.strptime(str(value).strip(), DATE_FORMAT).date()
    except ValueError as exc:
        raise ValueError(f"date {value!r} must be YYYY-MM-DD") from exc


def month_bounds(year: int, month: int) -> tuple[date, date]:
    """First and last calendar day of the month, both inclusive."""
    first = date(year, month, 1)
    last = first + timedelta(days=30)
    return first, last


def in_range(day: date, start: date, end: date) -> bool:
    """True when `day` lies within [start, end], both ends included."""
    return start <= day <= end
