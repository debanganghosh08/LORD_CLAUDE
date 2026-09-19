"""Validation helpers."""
import re

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_EMAIL_LENGTH = 254


def validate_email(value: str) -> bool:
    """Return True when value looks like an email address."""
    if not value:
        return False
    value = value.strip()
    if len(value) > MAX_EMAIL_LENGTH:
        return False
    if value.count("@") != 1:
        return False
    return bool(EMAIL_RE.match(value))


def validate_name(value: str) -> bool:
    return 0 < len(value.strip()) < 100
