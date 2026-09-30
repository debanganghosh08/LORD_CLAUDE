# Ledger demo

A small personal expense ledger. It exists as a realistic, self-contained
codebase for evaluating coding agents: it has a tiny web page, a JSON API,
services, shared utilities and configuration, a repository layer, and tests.
Standard library only; runs on Windows with Python 3.11+.

## Layout

```
app/
  config.py            shared constants (currency, limits, date format, categories)
  models.py            Transaction and MonthlySummary
  validation.py        input validation for transactions
  repository.py        Repository base, InMemoryRepository, JsonFileRepository
  utils/money.py       parse_amount / format_amount
  utils/text.py        normalize_text / slugify / truncate_note
  utils/dates.py       parse_date / month_bounds / in_range
  services/transactions.py   TransactionService: add, list, in_month, total
  services/reports.py        ReportService: monthly_summary, render
  services/export.py         ExportService: monthly_csv
  api/handlers.py      request handlers (dict in, dict out) used by the server and the tests
  api/server.py        stdlib HTTP server exposing the handlers and the web page
web/                   index.html + app.js (no build step)
scripts/seed.py        writes sample data to data/ledger.json
tests/                 pytest suite
```

Dependencies flow downward: `web -> api -> services -> utils/config/models -> repository`.
Tests import the layer they cover directly.

## Run

```
cd demo
python -m pytest                      # the test suite
python scripts/seed.py                # create data/ledger.json with sample transactions
python -m app.api.server              # http://127.0.0.1:8765  (Ctrl+C to stop)
```

API:

```
GET  /api/transactions?page=1
POST /api/transactions        {"date": "2026-03-15", "amount": "12.50", "kind": "expense", "category": "groceries", "description": "Market"}
GET  /api/report?year=2026&month=3
GET  /api/export?year=2026&month=3    (CSV)
```

Amounts are stored as integer cents. Dates are ISO `YYYY-MM-DD`.
