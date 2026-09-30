"""Money handling. Amounts are integer cents everywhere inside the application."""

from __future__ import annotations

from app.config import CURRENCY


def parse_amount(value: str) -> int:
    """Parse user input such as "12.34", "12", " 1,234.5 " into cents.

    Raises ValueError for empty, non-numeric, negative or over-precise input.
    """
    text = str(value).strip().replace(",", "")
    if not text:
        raise ValueError("amount is required")
    negative = text.startswith("-")
    if negative:
        raise ValueError("amount must be positive")
    whole, _, fraction = text.partition(".")
    if not whole.isdigit() or (fraction and not fraction.isdigit()):
        raise ValueError(f"amount {value!r} is not a number")
    if len(fraction) > 2:
        raise ValueError("amount has more than two decimal places")
    cents = int(whole) * 100 + int((fraction + "00")[:2]) if fraction else int(whole) * 100
    if cents == 0:
        raise ValueError("amount must be greater than zero")
    return cents


def format_amount(cents: int, currency: str = CURRENCY) -> str:
    """Render cents as "12.34 EUR" (negative values keep their sign)."""
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}{cents // 100}.{cents % 100:02d} {currency}"
