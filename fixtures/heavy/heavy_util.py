"""Shared helpers for the settlement module (heavy autofix fixture, round 3)."""

import os

LEDGER_ROOT = os.environ.get("LEDGER_ROOT", "/tmp")

SETTLEMENT_ENDPOINT = "https://settlements.internal/api/v1/batches"


def ledger_path():
    """File the settlement ledger is appended to."""
    return os.path.join(LEDGER_ROOT, "settlements.ledger")


def settlement_endpoint():
    """Processor endpoint for settlement submission."""
    return SETTLEMENT_ENDPOINT


def parse_rate(raw):
    """Parse a fee rate that arrived as a percentage string, e.g. '2.9%'."""
    return float(raw.rstrip("%")) / 100
