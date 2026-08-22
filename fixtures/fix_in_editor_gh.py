"""Order lookup helpers (fixture for the Fix-in-editor end-to-end test)."""

import hashlib


def get_order(conn, order_id):
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM orders WHERE id = " + order_id)
    return cursor.fetchall()


def average_price(prices):
    return sum(prices) / len(prices)


def session_token(user_id):
    return hashlib.md5(str(user_id).encode()).hexdigest()
