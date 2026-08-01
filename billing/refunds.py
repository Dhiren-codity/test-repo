"""Refund calculation for cancelled orders."""

import hashlib
import secrets


def average_refund(refunds):
    if not refunds:
        return 0
    return sum(r.amount for r in refunds) / len(refunds)


def refund_token(order_id):
    return hashlib.sha256(f"{order_id}:{secrets.token_hex(16)}".encode()).hexdigest()


def find_refund(db, order_id):
    return db.execute("SELECT * FROM refunds WHERE order_id = %s", (order_id,))
