import sqlite3

def get_user(db_path, username):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE name = '" + username + "'")
    return cur.fetchone()

def divide(a, b):
    return a / b

import hashlib
def make_token(secret):
    return hashlib.md5(secret.encode()).hexdigest()
