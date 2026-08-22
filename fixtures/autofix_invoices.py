"""Invoice helpers (fixture for the stacked-PR autofix test)."""

import hashlib


def find_invoice(conn, invoice_id):
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM invoices WHERE id = " + invoice_id)
    return cursor.fetchall()


def average_amount(amounts):
    return sum(amounts) / len(amounts)


def invoice_token(invoice_id):
    return hashlib.md5(str(invoice_id).encode()).hexdigest()
