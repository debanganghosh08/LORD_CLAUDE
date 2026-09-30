from app.config import MAX_NOTE_LENGTH
from app.validation import require_description, validate_transaction

VALID = {"date": "2026-03-15", "amount": "12.50", "kind": "expense", "category": "groceries", "description": "Bakery"}


def test_valid_payload_has_no_errors():
    assert validate_transaction(VALID) == []


def test_every_field_is_checked():
    errors = validate_transaction({"date": "x", "amount": "-1", "kind": "gift", "category": "pets", "description": ""})
    assert len(errors) == 5
    assert any("YYYY-MM-DD" in e for e in errors) and any("positive" in e for e in errors)
    assert any(e.startswith("kind must be") for e in errors) and any(e.startswith("category must be") for e in errors)
    assert "description is required" in errors


def test_require_description_limits_length():
    assert require_description("  ok  ") is None
    assert require_description("   ") == "description is required"
    assert require_description("x" * (MAX_NOTE_LENGTH + 1)) == f"description longer than {MAX_NOTE_LENGTH} characters"
