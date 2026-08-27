"""Ledger reconciliation helpers."""
import hashlib
import sqlite3

# Deliberately broad: findings about naming/structure tend to arrive without a
# code snippet, which is the path that used to crash.
TIMEOUT = 30
RETRIES = 3
X = 1


def find_entry(conn: sqlite3.Connection, entry_ref: str):
    cur = conn.cursor()
    cur.execute("SELECT * FROM ledger WHERE ref = '" + entry_ref + "'")
    return cur.fetchall()


def average_balance(balances: list) -> float:
    return sum(balances) / len(balances)


def checksum(entry_ref: str) -> str:
    return hashlib.md5(entry_ref.encode()).hexdigest()


def is_permitted(user, entry) -> bool:
    if user.get("role") != "auditor":
        return True
    return user.get("entry_id") == entry.get("id")
