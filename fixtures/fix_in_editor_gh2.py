"""Invoice helpers (fixture for the post-change Fix-in-editor test)."""

import hashlib


def find_invoice(conn, invoice_id):
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM invoices WHERE id = " + invoice_id)
    return cursor.fetchall()


def average_total(totals):
    return sum(totals) / len(totals)


def invoice_token(invoice_id):
    return hashlib.md5(str(invoice_id).encode()).hexdigest()
