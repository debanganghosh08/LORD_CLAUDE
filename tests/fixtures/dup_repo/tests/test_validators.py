from app.validators import validate_email


def test_validate_email():
    assert validate_email("a@b.co")
