"""Text helpers shared by the services and the API layer."""

from __future__ import annotations

import re

from app.config import MAX_NOTE_LENGTH

_WHITESPACE = re.compile(r"\s+")
_NON_SLUG = re.compile(r"[^a-z0-9]+")


def normalize_text(value: str) -> str:
    """Trim the ends and collapse internal runs of whitespace to one space."""
    return _WHITESPACE.sub(" ", str(value)).strip()


def slugify(value: str) -> str:
    """Lower-case, dash-separated identifier suitable for category keys."""
    return _NON_SLUG.sub("-", normalize_text(value).lower()).strip("-")


def truncate_note(value: str, limit: int = MAX_NOTE_LENGTH) -> str:
    """Normalise and cut a note to `limit` characters, marking the cut with an ellipsis."""
    text = normalize_text(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"
