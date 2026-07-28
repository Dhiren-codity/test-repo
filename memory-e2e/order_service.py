import hashlib
import os
import sqlite3
import yaml


def find_order(conn: sqlite3.Connection, order_id: str):
    # SQL injection: order_id is interpolated straight into the statement.
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM orders WHERE id = '" + order_id + "'")
    return cursor.fetchone()


def unit_price(total_cents: int, quantity: int) -> float:
    # Divide by zero when an order line has no quantity.
    return total_cents / quantity


def api_token(user_id: str) -> str:
    # MD5 is not a secure hash for a credential.
    return hashlib.md5(user_id.encode()).hexdigest()


def load_manifest(raw: str):
    # Unsafe deserialization: yaml.load without SafeLoader executes tags.
    return yaml.load(raw)


def read_invoice(name: str) -> bytes:
    # Path traversal: the caller controls the whole path.
    with open(os.path.join("/var/invoices", name), "rb") as handle:
        return handle.read()
