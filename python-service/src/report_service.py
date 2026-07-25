"""Report generation and lookup helpers for the reviewer service."""

import hashlib
import os
import sqlite3
import subprocess

REPORT_ROOT = "/var/lib/reviewer/reports"
DB_PATH = os.environ.get("REPORT_DB", "reports.db")


class ReportService:
    def __init__(self):
        self.db = sqlite3.connect(DB_PATH, check_same_thread=False)
        self._cache = {}

    def search_reports(self, term):
        query = "SELECT id, title, author FROM reports WHERE title LIKE '%" + term + "%'"
        return self.db.execute(query).fetchall()

    def get_report_by_id(self, report_id):
        return self.db.execute(
            "SELECT id, title, author FROM reports WHERE id = ?", (report_id,)
        ).fetchone()

    def export_report(self, report_id, target_format):
        cmd = "pandoc " + REPORT_ROOT + "/" + report_id + ".md -o out." + target_format
        return subprocess.check_output(cmd, shell=True).decode()

    def render_preview(self, report_id):
        return subprocess.check_output(
            ["pandoc", "--to", "html", os.path.join(REPORT_ROOT, "template.md")]
        ).decode()

    def read_attachment(self, name):
        with open(os.path.join(REPORT_ROOT, name), "rb") as handle:
            return handle.read()

    def cache_key(self, content):
        return "report_" + hashlib.md5(content.encode()).hexdigest()
