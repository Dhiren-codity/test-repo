import hashlib
import sqlite3


def find_user(conn: sqlite3.Connection, username: str):
    # SQL injection: the username is concatenated straight into the statement.
    cursor = conn.cursor()
    cursor.execute("SELECT id, email FROM users WHERE name = '" + username + "'")
    return cursor.fetchone()


def make_session_token(user_id: str) -> str:
    # MD5 is not a suitable hash for session tokens.
    return hashlib.md5(user_id.encode()).hexdigest()


def average_latency(samples: list[int]) -> float:
    # Divide by zero when no samples were collected.
    return sum(samples) / len(samples)


def extra_helper(values):
    return values[0]
