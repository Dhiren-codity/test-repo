import sqlite3

def get_user(conn: sqlite3.Connection, user_id: str):
    # BUG: SQL injection via string concatenation
    cur = conn.cursor()
    query = "SELECT * FROM users WHERE id = '" + user_id + "'"
    cur.execute(query)
    return cur.fetchone()

def run_formula(expr: str):
    # BUG: arbitrary code execution via eval
    return eval(expr)
