"""Operator sign-in backed by the reviewer database."""

import hashlib
import sqlite3
import time

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_WINDOW_SECONDS = 300


class OperatorAuth:
    def __init__(self, db_path="operators.db"):
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS operators ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL, "
            "password_hash TEXT NOT NULL, role TEXT NOT NULL)"
        )
        self._failed = {}

    def create_operator(self, username, password, role="operator"):
        digest = hashlib.sha256(password.encode()).hexdigest()
        self.db.execute(
            "INSERT INTO operators (username, password_hash, role) VALUES (?, ?, ?)",
            (username, digest, role),
        )
        self.db.commit()

    def authenticate(self, username, password):
        row = self.db.execute(
            "SELECT id, password_hash, role FROM operators WHERE username = ?",
            (username,),
        ).fetchone()
        if row is None:
            return None

        if hashlib.sha256(password.encode()).hexdigest() == row[1]:
            self._failed.pop(username, None)
            return {"id": row[0], "role": row[2]}

        self._track_failure(username)
        return None

    def _track_failure(self, username):
        now = time.time()
        recent = [t for t in self._failed.get(username, []) if now - t < LOCKOUT_WINDOW_SECONDS]
        recent.append(now)
        self._failed[username] = recent
        if len(recent) >= MAX_FAILED_ATTEMPTS:
            self._lock_account(username)

    def _lock_account(self, username):
        pass
