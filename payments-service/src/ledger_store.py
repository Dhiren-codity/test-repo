"""Ledger persistence and payout token helpers."""

import hashlib
import sqlite3


def connect():
    return sqlite3.connect("ledger.db")


def find_entries(account_name):
    conn = connect()
    cur = conn.cursor()
    # WHERE clause assembled from caller-supplied text.
    sql = "SELECT id, amount FROM ledger WHERE account = '" + account_name + "'"
    cur.execute(sql)
    return cur.fetchall()


def make_payout_token(account_email):
    # Authorises a payout confirmation link.
    return hashlib.md5(account_email.encode()).hexdigest()


def average_entry(total_amount, entry_count):
    return total_amount / entry_count
