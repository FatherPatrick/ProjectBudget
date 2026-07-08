"""SQLite storage layer for ProjectBudget.

Single local database file under ./data/budget.db. Nothing leaves the machine.
"""
import sqlite3
from pathlib import Path
from contextlib import contextmanager

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "budget.db"

# Default categories shown in the UI. Editable later; "Uncategorized" and
# "Transfer/Payment" are special (the latter is excluded from spend totals).
DEFAULT_CATEGORIES = [
    "Bills",
    "Food",
    "Grocery",
    "Fun",
    "Subscriptions",
    "Transport",
    "Shopping",
    "Health",
    "Travel",
    "Fees",
    "Income",
    "Transfer/Payment",
    "Uncategorized",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    txn_date       TEXT    NOT NULL,            -- ISO YYYY-MM-DD
    description    TEXT    NOT NULL,
    amount         REAL    NOT NULL,            -- positive = spend, negative = money in
    source_account TEXT    NOT NULL,
    raw_category   TEXT    DEFAULT '',          -- bank-provided category, if any
    category       TEXT    NOT NULL DEFAULT 'Uncategorized',
    manually_set   INTEGER NOT NULL DEFAULT 0,  -- 1 = user pinned the category; rules won't touch it
    hash           TEXT    NOT NULL UNIQUE,     -- dedupe key for re-uploads
    created_at     TEXT    DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_txn_date ON transactions(txn_date);
CREATE INDEX IF NOT EXISTS idx_txn_category ON transactions(category);

CREATE TABLE IF NOT EXISTS categories (
    name       TEXT PRIMARY KEY,
    sort_order INTEGER DEFAULT 100
);

CREATE TABLE IF NOT EXISTS rules (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern    TEXT NOT NULL UNIQUE,            -- matched as case-insensitive substring of description
    category   TEXT NOT NULL,
    priority   INTEGER DEFAULT 100,             -- lower = checked first
    direction  TEXT NOT NULL DEFAULT 'any',     -- 'any' | 'in' (money in) | 'out' (spend)
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def _migrate(conn) -> None:
    """Lightweight column additions for DBs created by older versions."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(rules)").fetchall()}
    if "direction" not in cols:
        conn.execute("ALTER TABLE rules ADD COLUMN direction TEXT NOT NULL DEFAULT 'any'")
    txn_cols = {r["name"] for r in conn.execute("PRAGMA table_info(transactions)").fetchall()}
    if "manually_set" not in txn_cols:
        conn.execute(
            "ALTER TABLE transactions ADD COLUMN manually_set INTEGER NOT NULL DEFAULT 0"
        )


def get_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Create tables and seed default categories. Safe to call repeatedly."""
    with db() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)
        for i, name in enumerate(DEFAULT_CATEGORIES):
            conn.execute(
                "INSERT OR IGNORE INTO categories(name, sort_order) VALUES (?, ?)",
                (name, i),
            )
