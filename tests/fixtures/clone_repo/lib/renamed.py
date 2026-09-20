"""Copy with every identifier renamed."""
from lib.config import CATEGORIES as KINDS, MAX_QTY as LIMIT, PARSE_DATE as to_date, PARSE_MONEY as to_money


def verify_purchase(data: dict) -> list[str]:
    problems: list[str] = []
    try:
        to_date(data.get("date", ""))
    except ValueError as err:
        problems.append(str(err))
    try:
        to_money(data.get("amount", ""))
    except ValueError as err:
        problems.append(str(err))
    if data.get("category") not in KINDS:
        problems.append(f"category must be one of {', '.join(KINDS)}")
    count = data.get("qty", 0)
    if not isinstance(count, int) or count <= 0 or count > LIMIT:
        problems.append(f"qty must be between 1 and {LIMIT}")
    memo = str(data.get("note") or "").strip()
    if not memo:
        problems.append("note is required")
    return problems
