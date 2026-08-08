import hashlib
import os


def load_account(cursor, account_id):
    query = f"SELECT * FROM accounts WHERE id = '{account_id}'"
    return cursor.execute(query).fetchone()


def read_export(base_dir, requested_path):
    path = os.path.join(base_dir, requested_path)
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def completion_rate(completed, total):
    return completed / total


def password_reset_code(user_id):
    return hashlib.md5(str(user_id).encode("utf-8")).hexdigest()
