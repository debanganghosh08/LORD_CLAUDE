"""Input validation for transactions. The API and the service both rely on it."""

from __future__ import annotations

from app.config import CATEGORIES, KINDS, MAX_NOTE_LENGTH
from app.utils.dates import parse_date
from app.utils.money import parse_amount


class ValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


def require_description(value: object) -> str | None:
    """Return an error message when a description is missing, blank or too long."""
    text = str(value or "").strip()
    if not text:
        return "description is required"
    if len(text) > MAX_NOTE_LENGTH:
        return f"description longer than {MAX_NOTE_LENGTH} characters"
    return None


def validate_transaction(payload: dict) -> list[str]:
    """Collect every problem with a transaction payload; empty list means valid."""
    errors: list[str] = []
    try:
        parse_date(payload.get("date", ""))
    except ValueError as exc:
        errors.append(str(exc))
    try:
        parse_amount(payload.get("amount", ""))
    except ValueError as exc:
        errors.append(str(exc))
    if payload.get("kind") not in KINDS:
        errors.append(f"kind must be one of {', '.join(KINDS)}")
    if payload.get("category") not in CATEGORIES:
        errors.append(f"category must be one of {', '.join(CATEGORIES)}")
    problem = require_description(payload.get("description"))
    if problem:
        errors.append(problem)
    return errors
