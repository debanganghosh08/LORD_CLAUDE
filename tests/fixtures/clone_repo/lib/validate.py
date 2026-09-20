"""Original order validator."""
from lib.config import CATEGORIES, MAX_QTY, PARSE_DATE, PARSE_MONEY


def validate_order(payload: dict) -> list[str]:
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
    if not isinstance(qty, int) or qty <= 0 or qty > MAX_QTY:
        errors.append(f"qty must be between 1 and {MAX_QTY}")
    note = str(payload.get("note") or "").strip()
    if not note:
        errors.append("note is required")
    return errors
