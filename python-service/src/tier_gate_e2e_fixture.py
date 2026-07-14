"""Intentional E2E fixtures for Codity review and navigation tests."""

from pathlib import Path
from typing import Any


def load_customer_report(connection: Any, customer_name: str) -> list[tuple[Any, ...]]:
    query = f"SELECT * FROM customer_reports WHERE customer_name = '{customer_name}'"
    return connection.execute(query).fetchall()


def read_export(export_root: Path, requested_name: str) -> str:
    export_path = export_root / requested_name
    return export_path.read_text(encoding="utf-8")
