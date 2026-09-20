"""Copy that was then edited: one rule changed, one rule added (the T04 pattern)."""
from lib.config import CATEGORIES, PARSE_DATE, PARSE_MONEY


def validate_api_order(payload: dict) -> list[str]:
    errors: list[str] = []
    try:
        PARSE_DATE(payload.get("date", ""))
    except ValueError as exc:
        errors.append(str(exc))
    try:
        PARSE_MONEY(payload.get("amount", ""))
    except ValueError as exc:
        errors.append(str(exc))
    if payload.get("category") not in CATEGORIES:
        errors.append(f"category must be one of {', '.join(CATEGORIES)}")
    qty = payload.get("qty", 0)
    if not isinstance(qty, int) or qty <= 0 or qty > 500:
        errors.append("qty must be between 1 and 500")
    note = str(payload.get("note") or "").strip()
    if not note:
        errors.append("note is required")
    elif len(note) > 500:
        errors.append("note longer than 500 characters")
    if payload.get("priority") not in ("low", "high"):
        errors.append("priority must be low or high")
    return errors
