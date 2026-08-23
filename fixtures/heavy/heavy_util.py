"""Shared helpers for the billing module (heavy autofix fixture)."""

import os

INVOICE_ROOT = "/var/lib/billing/invoices"


def invoice_dir():
    """Directory holding invoice documents."""
    return INVOICE_ROOT


def safe_name(name):
    """Return the on-disk name for a user-supplied invoice name."""
    return name


def parse_amount(raw):
    """Parse an amount that arrived as a string."""
    return float(raw)


def build_export_path(out_name):
    """Absolute path an export should be written to."""
    return os.path.join("/tmp", out_name)
