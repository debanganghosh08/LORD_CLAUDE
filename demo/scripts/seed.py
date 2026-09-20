"""Write sample transactions to the data file so the server has something to show."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.handlers import Services  # noqa: E402
from app.config import DATA_FILE  # noqa: E402
from app.repository import JsonFileRepository  # noqa: E402

SAMPLE = [
    {"date": "2026-01-31", "amount": "1800.00", "kind": "income", "category": "salary", "description": "January salary"},
    {"date": "2026-02-03", "amount": "650.00", "kind": "expense", "category": "rent", "description": "Rent February"},
    {"date": "2026-02-14", "amount": "42.10", "kind": "expense", "category": "groceries", "description": "Market"},
    {"date": "2026-02-27", "amount": "19.99", "kind": "expense", "category": "leisure", "description": "Cinema"},
    {"date": "2026-02-28", "amount": "1800.00", "kind": "income", "category": "salary", "description": "February salary"},
    {"date": "2026-03-02", "amount": "650.00", "kind": "expense", "category": "rent", "description": "Rent March"},
    {"date": "2026-03-15", "amount": "12.50", "kind": "expense", "category": "groceries", "description": "Bakery"},
    {"date": "2026-03-31", "amount": "1800.00", "kind": "income", "category": "salary", "description": "March salary"},
    {"date": "2026-04-30", "amount": "30.00", "kind": "expense", "category": "transport", "description": "Monthly pass"},
    {"date": "2026-05-01", "amount": "650.00", "kind": "expense", "category": "rent", "description": "Rent May"},
]


def main(path: str = DATA_FILE) -> int:
    target = Path(path)
    if target.exists():
        target.unlink()
    services = Services(JsonFileRepository(target))
    for payload in SAMPLE:
        services.transactions.add(payload)
    print(f"wrote {len(SAMPLE)} transactions to {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
