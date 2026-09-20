from app.config import MAX_NOTE_LENGTH
from app.utils.text import normalize_text, slugify, truncate_note


def test_normalize_text_trims_and_collapses():
    assert normalize_text("  Weekly   groceries \n run ") == "Weekly groceries run"
    assert normalize_text("") == ""


def test_slugify():
    assert slugify("  Public Transport ") == "public-transport"
    assert slugify("Café & Bar!") == "caf-bar"


def test_truncate_note_respects_limit():
    long = "word " * 60
    cut = truncate_note(long)
    assert len(cut) <= MAX_NOTE_LENGTH and cut.endswith("…")
    assert truncate_note("short") == "short"
