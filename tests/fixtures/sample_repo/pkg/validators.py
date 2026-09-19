"""Validation helpers."""
import re

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_EMAIL_LENGTH = 254


def validate_email(value: str) -> bool:
    """Return True when value looks like an email address."""
    return bool(EMAIL_RE.match(value)) and len(value) <= MAX_EMAIL_LENGTH


def _private_helper(x):
    return x
