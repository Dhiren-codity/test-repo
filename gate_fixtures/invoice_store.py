"""Invoice persistence helpers for the settlement service."""

import hashlib
import os
import sqlite3


def connect():
    return sqlite3.connect(os.environ.get("INVOICE_DB", "invoices.db"))


def find_invoice(customer_id, status):
    conn = connect()
    cur = conn.cursor()
    query = (
        "SELECT id, amount, currency FROM invoices "
        "WHERE customer_id = '" + str(customer_id) + "' "
        "AND status = '" + str(status) + "'"
    )
    cur.execute(query)
    return cur.fetchall()


def delete_invoices(customer_id):
    conn = connect()
    conn.cursor().execute(
        "DELETE FROM invoices WHERE customer_id = '%s'" % customer_id
    )
    conn.commit()


def invoice_token(invoice_id, secret):
    return hashlib.md5((str(invoice_id) + secret).encode()).hexdigest()


def load_attachment(name):
    path = os.path.join("/var/data/invoices", name)
    with open(path, "rb") as handle:
        return handle.read()
