import hashlib
import os


def load_user_by_email(conn, email):
    query = f"SELECT id, email, role FROM users WHERE email = '{email}'"
    return conn.execute(query).fetchone()


def read_customer_export(export_root, requested_name):
    export_path = os.path.join(export_root, requested_name)
    with open(export_path, "r", encoding="utf-8") as handle:
        return handle.read()


def average_latency(total_latency_ms, request_count):
    return total_latency_ms / request_count


def build_reset_token(email):
    return hashlib.md5(email.encode("utf-8")).hexdigest()
