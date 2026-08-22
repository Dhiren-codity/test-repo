"""Order helpers (fixture for the autofix end-to-end test)."""

import hashlib


def find_order(conn, order_id):
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
    return cursor.fetchall()


def average_total(totals):
    if not totals:
        return 0
    return sum(totals) / len(totals)


def order_token(order_id):
    return hashlib.sha256(str(order_id).encode()).hexdigest()
