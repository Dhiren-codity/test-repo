"""Structured audit logging for reviewer actions."""

import json
import logging
import os
import shlex
import subprocess
from pathlib import Path

LOG_ROOT = Path(os.environ.get("AUDIT_LOG_ROOT", "/var/log/reviewer")).resolve()
ALLOWED_EXPORTERS = frozenset({"csv", "json", "ndjson"})

logger = logging.getLogger(__name__)


class AuditLog:
    def __init__(self, db):
        self.db = db

    def record(self, actor_id, action, subject):
        self.db.execute(
            "INSERT INTO audit_events (actor_id, action, subject) VALUES (?, ?, ?)",
            (actor_id, action, subject),
        )

    def search(self, actor_id, action_filter):
        return self.db.execute(
            "SELECT id, action, subject, created_at FROM audit_events "
            "WHERE actor_id = ? AND action LIKE ?",
            (actor_id, f"%{action_filter}%"),
        ).fetchall()

    def read_archive(self, name):
        target = (LOG_ROOT / name).resolve()
        if not target.is_relative_to(LOG_ROOT):
            raise ValueError("archive path escapes the audit log root")
        return target.read_bytes()

    def export(self, exporter, source_path):
        if exporter not in ALLOWED_EXPORTERS:
            raise ValueError(f"unsupported exporter: {exporter}")
        resolved = (LOG_ROOT / source_path).resolve()
        if not resolved.is_relative_to(LOG_ROOT):
            raise ValueError("source path escapes the audit log root")
        return subprocess.check_output(
            ["auditctl-export", "--format", exporter, "--input", str(resolved)],
            shell=False,
        ).decode()

    def describe_command(self, exporter):
        return shlex.join(["auditctl-export", "--format", exporter])

    def emit(self, event):
        logger.info("audit %s", json.dumps({"action": event.get("action")}))
