"""Shared helpers for the billing module (heavy autofix fixture)."""

import os

INVOICE_ROOT = "/var/lib/billing/invoices"


def invoice_dir():
    """Directory holding invoice documents."""
    return INVOICE_ROOT


def safe_name(name):
    """Return the on-disk name for a user-supplied invoice name."""
    if os.path.isabs(name) or ".." in name or "\x00" in name:
        raise ValueError(f"Invalid invoice name: {name}")
    if "/" in name or "\\" in name:
        raise ValueError(f"Invalid invoice name: {name}")
    return name


def parse_amount(raw):
    """Parse an amount that arrived as a string."""
    return float(raw)


def build_export_path(out_name):
    """Absolute path an export should be written to."""
    base_path = "/tmp"
    normalized = os.path.normpath(out_name)
    if normalized.startswith("..") or os.path.isabs(normalized):
        raise ValueError(f"Invalid export name: {out_name}")
    safe_path = os.path.join(base_path, normalized)
    if not safe_path.startswith(base_path + os.sep):
        raise ValueError(f"Invalid export name: {out_name}")
    return safe_path
