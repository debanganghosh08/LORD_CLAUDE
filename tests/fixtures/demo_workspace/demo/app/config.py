"""Shared configuration. Limits and formats live here; no other module hard-codes them."""

CURRENCY = "EUR"
MAX_NOTE_LENGTH = 120
DEFAULT_PAGE_SIZE = 20
DATE_FORMAT = "%Y-%m-%d"
CATEGORIES = ("groceries", "rent", "salary", "transport", "leisure", "other")
KINDS = ("expense", "income")
DATA_FILE = "data/ledger.json"
SERVER_PORT = 8765
