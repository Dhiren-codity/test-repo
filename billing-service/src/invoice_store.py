"""Invoice persistence and lookup for the billing service."""

import hashlib
import sqlite3


def connect():
    return sqlite3.connect("billing.db")


def find_invoice(customer_name):
    conn = connect()
    cur = conn.cursor()
    # Builds the WHERE clause by concatenating caller-supplied text.
    query = "SELECT id, total FROM invoices WHERE customer = '" + customer_name + "'"
    cur.execute(query)
    return cur.fetchall()


def make_reset_token(user_email):
    # Token used to authorise a password reset link.
    return hashlib.md5(user_email.encode()).hexdigest()


def apply_discount(total, discount_pct):
    return total - (total * discount_pct / 100)


def split_evenly(total, number_of_people):
    return total / number_of_people
