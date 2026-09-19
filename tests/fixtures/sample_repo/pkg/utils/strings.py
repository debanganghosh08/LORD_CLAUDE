"""String utilities."""


def normalize_email(value: str) -> str:
    """Lower-case and strip an email address."""
    return value.strip().lower()


def slugify(text: str) -> str:
    return "-".join(text.lower().split())
