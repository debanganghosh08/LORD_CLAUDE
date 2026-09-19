"""Older checks kept for compatibility."""
import re

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_EMAIL_LENGTH = 320


def check_email(addr: str) -> bool:
    if not addr:
        return False
    addr = addr.strip()
    if len(addr) > MAX_EMAIL_LENGTH:
        return False
    if addr.count("@") != 1:
        return False
    return bool(EMAIL_PATTERN.match(addr))


def validate_name(value: str) -> bool:
    return bool(value)
