"""
Seed script for the SME Loan Triage Agent demo.

Creates a SQLite database `bank.db` with three tables and synthetic data
representing a small UK SME bank's loan operations.

Run once:
    python seed.py
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "bank.db"

if DB_PATH.exists():
    DB_PATH.unlink()

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# ---------- Schema ----------
cur.executescript("""
CREATE TABLE customers (
    customer_id        TEXT PRIMARY KEY,
    business_name      TEXT NOT NULL,
    industry           TEXT NOT NULL,
    years_with_bank    INTEGER NOT NULL,
    annual_revenue_gbp INTEGER NOT NULL
);

CREATE TABLE repayment_history (
    record_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id      TEXT NOT NULL,
    loan_amount_gbp  INTEGER NOT NULL,
    due_date         DATE NOT NULL,
    paid_date        DATE,
    status           TEXT NOT NULL CHECK (status IN ('on_time', 'late', 'defaulted')),
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
);

CREATE TABLE loan_applications (
    application_id       TEXT PRIMARY KEY,
    customer_id          TEXT NOT NULL,
    requested_amount_gbp INTEGER NOT NULL,
    purpose              TEXT NOT NULL,
    submitted_at         TIMESTAMP NOT NULL,
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
);
""")

# ---------- Customers (5 SMEs across 3 risk profiles) ----------
customers = [
    # Strong: long relationship, healthy revenue
    ("CUS001", "ABC Bakery Ltd",        "Food & Beverage",   6, 520000),
    ("CUS002", "GreenLeaf Landscaping", "Services",          8, 380000),
    # Medium
    ("CUS003", "Pixel Print Studio",    "Creative Services", 3, 210000),
    # Weak: short relationship, payment issues
    ("CUS004", "QuickFix Auto Repairs", "Automotive",        2, 180000),
    ("CUS005", "Sunrise Cafe",          "Food & Beverage",   1,  95000),
]
cur.executemany(
    "INSERT INTO customers VALUES (?, ?, ?, ?, ?)",
    customers,
)

# ---------- Repayment history (20 records) ----------
repayments = [
    # CUS001 — strong: 5 records, all on_time
    ("CUS001", 25000, "2023-06-15", "2023-06-12", "on_time"),
    ("CUS001", 30000, "2024-02-15", "2024-02-14", "on_time"),
    ("CUS001", 20000, "2024-09-15", "2024-09-15", "on_time"),
    ("CUS001", 35000, "2025-04-15", "2025-04-14", "on_time"),
    ("CUS001", 40000, "2025-11-15", "2025-11-13", "on_time"),
    # CUS002 — strong: 4 records, 1 minor late
    ("CUS002", 15000, "2023-08-20", "2023-08-18", "on_time"),
    ("CUS002", 22000, "2024-03-20", "2024-03-25", "late"),
    ("CUS002", 28000, "2024-10-20", "2024-10-19", "on_time"),
    ("CUS002", 35000, "2025-05-20", "2025-05-19", "on_time"),
    # CUS003 — medium: 4 records, 1 late
    ("CUS003", 12000, "2024-01-10", "2024-01-09", "on_time"),
    ("CUS003", 18000, "2024-08-10", "2024-08-22", "late"),
    ("CUS003", 15000, "2025-03-10", "2025-03-09", "on_time"),
    ("CUS003", 20000, "2025-10-10", "2025-10-11", "on_time"),
    # CUS004 — weak: 4 records, 3 late
    ("CUS004",  8000, "2024-05-12", "2024-05-28", "late"),
    ("CUS004", 12000, "2024-11-12", "2024-11-30", "late"),
    ("CUS004", 15000, "2025-06-12", "2025-06-13", "on_time"),
    ("CUS004", 10000, "2025-12-12", "2026-01-05", "late"),
    # CUS005 — weak: 3 records, 1 defaulted
    ("CUS005",  5000, "2025-02-08", "2025-02-15", "late"),
    ("CUS005",  7000, "2025-08-08", None,         "defaulted"),
    ("CUS005",  6000, "2026-01-08", "2026-01-22", "late"),
]
cur.executemany(
    "INSERT INTO repayment_history (customer_id, loan_amount_gbp, due_date, paid_date, status) "
    "VALUES (?, ?, ?, ?, ?)",
    repayments,
)

# ---------- Loan applications (3 current applications) ----------
applications = [
    ("APP001", "CUS001", 50000, "Equipment upgrade for new bakery line",        "2026-05-06 09:12:00"),
    ("APP002", "CUS003", 30000, "Working capital for seasonal stock",           "2026-05-06 10:34:00"),
    ("APP003", "CUS005", 25000, "Cafe expansion to second location",            "2026-05-06 11:08:00"),
]
cur.executemany(
    "INSERT INTO loan_applications VALUES (?, ?, ?, ?, ?)",
    applications,
)

conn.commit()

# ---------- Verify ----------
print("=== Seed complete ===")
print(f"DB file: {DB_PATH}")
for table in ["customers", "repayment_history", "loan_applications"]:
    count = cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    print(f"  {table:22s} {count:3d} rows")

conn.close()
