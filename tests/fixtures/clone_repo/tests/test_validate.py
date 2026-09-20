from lib.validate import validate_order


def test_ok():
    assert validate_order({"date": "2026-01-01", "amount": "1", "category": "a", "qty": 1, "note": "x"}) == []
