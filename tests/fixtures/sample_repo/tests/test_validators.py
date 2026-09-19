from pkg.validators import validate_email


def test_validate_email_accepts_simple_address():
    assert validate_email("a@b.co")
