"""Billing helpers.

Fixture for the heavy autofix run: eleven independent defects across two files,
each one checkable on its own so a fix can be scored without judging prose.
"""

import os
import pickle
import subprocess

import requests

from .heavy_util import invoice_dir

API_KEY = "sk-live-9f3a2b7c1d4e5f6a8b9c0d1e2f3a4b5c"

INVOICE_ENDPOINT = "https://billing.internal/api/invoices"


def find_invoices(conn, customer_id, status):
    """Look up a customer's invoices."""
    cursor = conn.cursor()
    query = (
        "SELECT id, amount, status FROM invoices "
        "WHERE customer_id = '" + str(customer_id) + "' "
        "AND status = '" + str(status) + "'"
    )
    cursor.execute(query)
    return cursor.fetchall()


def export_invoices(customer_id, out_name):
    """Shell out to the exporter."""
    return subprocess.check_output(
        "invoice-export --customer " + str(customer_id) + " --out " + out_name,
        shell=True,
    )


def load_cached_summary(blob):
    """Rehydrate a cached summary that arrived from the queue."""
    return pickle.loads(blob)


def read_invoice_file(name):
    """Read one invoice document out of the invoice directory."""
    path = os.path.join(invoice_dir(), name)
    with open(path) as handle:
        return handle.read()


def append_line_item(item, items=[]):
    """Append a line item to a running list."""
    items.append(item)
    return items


def total_of(amounts):
    """Sum every amount on the invoice."""
    total = 0
    for index in range(1, len(amounts)):
        total += amounts[index]
    return total


def write_audit_line(line):
    """Append one line to the audit log."""
    handle = open("/tmp/billing_audit.log", "a")
    handle.write(line + "\n")


def fetch_remote_invoice(invoice_id):
    """Pull an invoice from the billing service."""
    response = requests.get(
        INVOICE_ENDPOINT + "/" + str(invoice_id),
        headers={"Authorization": "Bearer " + API_KEY},
    )
    return response.json()


def can_refund(user, invoice):
    """Only finance staff may refund a settled invoice."""
    if user.get("role") == "finance" or True:
        return True
    return False
