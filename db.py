"""SQLite persistence for the finance command center."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "app.db"

ACCOUNT_TYPES = (
    "checking",
    "savings",
    "brokerage",
    "crypto",
    "credit",
    "loan",
    "other",
)

SCHEMA = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    institution TEXT DEFAULT '',
    type TEXT NOT NULL,
    balance REAL NOT NULL DEFAULT 0,
    apr REAL,
    min_payment REAL,
    due_day INTEGER,
    currency TEXT NOT NULL DEFAULT 'USD',
    color TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    include_in_cash INTEGER NOT NULL DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS obligations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    vendor TEXT DEFAULT '',
    account_id INTEGER NOT NULL,
    dest_account_id INTEGER,
    amount REAL NOT NULL,
    direction TEXT NOT NULL DEFAULT 'out',
    cadence TEXT NOT NULL DEFAULT 'monthly',
    due_day INTEGER,
    due_day_2 INTEGER,
    weekday INTEGER,
    next_date TEXT,
    end_date TEXT,
    category TEXT DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    notes TEXT DEFAULT '',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
    FOREIGN KEY (dest_account_id) REFERENCES accounts(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    obligation_id INTEGER NOT NULL,
    occur_date TEXT NOT NULL,
    paid INTEGER NOT NULL DEFAULT 1,
    UNIQUE (obligation_id, occur_date),
    FOREIGN KEY (obligation_id) REFERENCES obligations(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    tx_date TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    check_number TEXT DEFAULT '',
    amount REAL NOT NULL,
    balance REAL,
    source TEXT DEFAULT 'csv',
    external_id TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_tx_dedupe
    ON transactions(account_id, tx_date, amount, description, check_number);

CREATE TABLE IF NOT EXISTS snapshots (
    as_of TEXT PRIMARY KEY,
    cash REAL NOT NULL DEFAULT 0,
    investments REAL NOT NULL DEFAULT 0,
    crypto REAL NOT NULL DEFAULT 0,
    debt REAL NOT NULL DEFAULT 0,
    net_worth REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sinking_funds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    vendor TEXT DEFAULT '',
    category TEXT DEFAULT 'other',
    target_amount REAL NOT NULL,
    reserved REAL NOT NULL DEFAULT 0,
    next_date TEXT NOT NULL,
    cadence TEXT NOT NULL DEFAULT 'yearly',
    account_id INTEGER,
    dest_account_id INTEGER,
    reserve_obligation_id INTEGER,
    payout_obligation_id INTEGER,
    active INTEGER NOT NULL DEFAULT 1,
    notes TEXT DEFAULT '',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE SET NULL,
    FOREIGN KEY (dest_account_id) REFERENCES accounts(id) ON DELETE SET NULL,
    FOREIGN KEY (reserve_obligation_id) REFERENCES obligations(id) ON DELETE SET NULL,
    FOREIGN KEY (payout_obligation_id) REFERENCES obligations(id) ON DELETE SET NULL
);
"""


@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def _migrate(con: sqlite3.Connection) -> None:
    cols = {r["name"] for r in con.execute("PRAGMA table_info(obligations)").fetchall()}
    if "due_day_2" not in cols:
        con.execute("ALTER TABLE obligations ADD COLUMN due_day_2 INTEGER")
    if "end_date" not in cols:
        con.execute("ALTER TABLE obligations ADD COLUMN end_date TEXT")


def init_db(seed: bool = True) -> None:
    with connect() as con:
        con.executescript(SCHEMA)
        _migrate(con)
        row = con.execute("SELECT COUNT(*) AS n FROM accounts").fetchone()
        if seed and row["n"] == 0:
            seed_demo(con)


def get_setting(con: sqlite3.Connection, key: str, default: str = "") -> str:
    row = con.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(con: sqlite3.Connection, key: str, value: str) -> None:
    con.execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def seed_demo(con: sqlite3.Connection) -> None:
    set_setting(con, "buffer", "750")
    set_setting(con, "demo", "1")
    set_setting(con, "household", "Household")

    accounts = [
        ("Everyday Checking", "First National", "checking", 3240.18, None, None, None, "#3d8bfd"),
        ("Emergency Savings", "First National", "savings", 8900.00, None, None, None, "#2f9e71"),
        ("Brokerage", "Fidelity", "brokerage", 42150.40, None, None, None, "#7c6af7"),
        ("Crypto", "Coinbase + cold", "crypto", 4800.00, None, None, None, "#e0a106"),
        ("Visa Rewards", "Chase", "credit", -2180.44, 24.99, 75.00, 12, "#e35d6a"),
        ("Auto Loan", "Credit Union", "loan", -14600.00, 6.20, 385.00, 3, "#c47a3a"),
        ("Student Loan", "MOHELA", "loan", -9200.00, 5.50, 110.00, 15, "#8a8f98"),
    ]
    ids = {}
    for name, inst, typ, bal, apr, minp, due, color in accounts:
        cur = con.execute(
            """INSERT INTO accounts(name, institution, type, balance, apr, min_payment, due_day, color)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, inst, typ, bal, apr, minp, due, color),
        )
        ids[name] = cur.lastrowid

    checking = ids["Everyday Checking"]
    visa = ids["Visa Rewards"]
    auto = ids["Auto Loan"]
    student = ids["Student Loan"]
    savings = ids["Emergency Savings"]

    bills = [
        ("Paycheck", "Employer", checking, 2850.00, "in", "semimonthly", 15, "income"),  # due_day_2 set below
        ("Rent", "Oak Street Apts", checking, 1850.00, "out", "monthly", 1, "housing"),
        ("Auto loan", "Credit Union", checking, 385.00, "out", "monthly", 3, "debt"),
        ("Electric", "City Power", checking, 142.00, "out", "monthly", 8, "utilities"),
        ("Internet", "FiberCo", checking, 79.99, "out", "monthly", 10, "utilities"),
        ("Visa minimum", "Chase", checking, 75.00, "out", "monthly", 12, "debt"),
        ("Student loan", "MOHELA", checking, 110.00, "out", "monthly", 15, "debt"),
        ("Phone", "Visible", checking, 35.00, "out", "monthly", 18, "utilities"),
        ("Car insurance", "State Farm", checking, 168.00, "out", "monthly", 22, "insurance"),
        ("Gym", "FitHaus", checking, 49.00, "out", "monthly", 5, "subscriptions"),
        ("Netflix", "Netflix", checking, 15.49, "out", "monthly", 4, "subscriptions"),
        ("Spotify", "Spotify", checking, 11.99, "out", "monthly", 7, "subscriptions"),
        ("iCloud+", "Apple", checking, 2.99, "out", "monthly", 6, "subscriptions"),
        ("Savings sweep", "Self", checking, 200.00, "out", "monthly", 16, "savings"),
    ]
    for name, vendor, acct, amount, direction, cadence, due_day, category in bills:
        dest = None
        if name == "Savings sweep":
            dest = savings
        elif name == "Auto loan":
            dest = auto
        elif name == "Visa minimum":
            dest = visa
        elif name == "Student loan":
            dest = student
        due_day_2 = None
        if name == "Paycheck":
            due_day = 15
            due_day_2 = -1  # last weekday of month; weekends roll back to Friday
        con.execute(
            """INSERT INTO obligations(
                name, vendor, account_id, dest_account_id, amount, direction,
                cadence, due_day, due_day_2, category, active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
            (name, vendor, acct, dest, amount, direction, cadence, due_day, due_day_2, category),
        )

    funds = [
        ("Holiday gifts", "Self", "other", 600.00, 120.00, "2026-12-15", "yearly"),
        ("Car registration", "DMV", "transport", 180.00, 40.00, "2027-03-01", "yearly"),
        ("Replacement tires", "Shop", "transport", 800.00, 150.00, "2027-02-01", "yearly"),
    ]
    for name, vendor, cat, target, reserved, nxt, cad in funds:
        con.execute(
            """INSERT INTO sinking_funds(
                name, vendor, category, target_amount, reserved, next_date, cadence,
                account_id, dest_account_id, active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
            (name, vendor, cat, target, reserved, nxt, cad, checking, savings),
        )


def rows(con: sqlite3.Connection, sql: str, params=()) -> list[dict]:
    return [dict(r) for r in con.execute(sql, params).fetchall()]
