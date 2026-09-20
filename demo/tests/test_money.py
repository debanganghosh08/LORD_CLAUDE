import pytest

from app.utils.money import format_amount, parse_amount


@pytest.mark.parametrize("raw,cents", [("12.34", 1234), ("12", 1200), (" 1,234.5 ", 123450), ("0.05", 5), ("7.", 700)])
def test_parse_amount_accepts_common_inputs(raw, cents):
    assert parse_amount(raw) == cents


@pytest.mark.parametrize("raw", ["", "abc", "-5", "0", "1.234", "12.3.4"])
def test_parse_amount_rejects_bad_input(raw):
    with pytest.raises(ValueError):
        parse_amount(raw)


def test_format_amount_uses_two_decimals_and_currency():
    assert format_amount(1234) == "12.34 EUR"
    assert format_amount(5) == "0.05 EUR"
    assert format_amount(-1050) == "-10.50 EUR"
    assert format_amount(100, "USD") == "1.00 USD"


def test_parse_and_format_round_trip():
    assert format_amount(parse_amount("99.90")) == "99.90 EUR"
