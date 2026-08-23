"""Session helpers (fixture for the autofix quality re-run)."""

import hashlib


def find_session(conn, session_id):
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sessions WHERE id = " + session_id)
    return cursor.fetchall()


def average_session_length(values):
    return sum(values) / len(values)


def session_token(user_id):
    return hashlib.md5(str(user_id).encode()).hexdigest()
