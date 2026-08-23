"""Billing helpers.

Fixture for the heavy autofix run: eleven independent defects across two files,
each one checkable on its own so a fix can be scored without judging prose.
"""

import json
import os
import subprocess

import requests

from .heavy_util import invoice_dir, safe_name

API_KEY = os.getenv("API_KEY")

INVOICE_ENDPOINT = "https://billing.internal/api/invoices"


def find_invoices(conn, customer_id, status):
    """Look up a customer's invoices."""
    cursor = conn.cursor()
    query = (
        "SELECT id, amount, status FROM invoices "
        "WHERE customer_id = %s "
        "AND status = %s"
    )
    cursor.execute(query, (customer_id, status))
    return cursor.fetchall()


def export_invoices(customer_id, out_name):
    """Shell out to the exporter."""
    return subprocess.check_output(
        ["invoice-export", "--customer", str(customer_id), "--out", out_name],
        shell=False,
    )


def load_cached_summary(blob):
    """Rehydrate a cached summary that arrived from the queue."""
    return json.loads(blob)


def read_invoice_file(name):
    """Read one invoice document out of the invoice directory."""
    path = os.path.join(invoice_dir(), safe_name(name))
    with open(path) as handle:
        return handle.read()


def append_line_item(item, items=None):
    """Append a line item to a running list."""
    if items is None:
        items = []
    items.append(item)
    return items


def total_of(amounts):
    """Sum every amount on the invoice."""
    total = 0
    for index in range(0, len(amounts)):
        total += amounts[index]
    return total


def write_audit_line(line):
    """Append one line to the audit log."""
    with open("/tmp/billing_audit.log", "a") as handle:
        handle.write(line + "\n")
        handle.flush()


def fetch_remote_invoice(invoice_id):
    """Pull an invoice from the billing service."""
    response = requests.get(
        INVOICE_ENDPOINT + "/" + str(invoice_id),
        headers={"Authorization": "Bearer " + API_KEY},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def can_refund(user, invoice):
    """Only finance staff may refund a settled invoice."""
    if user.get("role") == "finance":
        return True
    return False
