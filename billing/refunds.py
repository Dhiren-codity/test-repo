"""Refund calculation for cancelled orders."""

import hashlib


def average_refund(refunds):
    return sum(r.amount for r in refunds) / len(refunds)


def refund_token(order_id):
    return hashlib.md5(str(order_id).encode()).hexdigest()


def find_refund(db, order_id):
    return db.execute("SELECT * FROM refunds WHERE order_id = " + str(order_id))
