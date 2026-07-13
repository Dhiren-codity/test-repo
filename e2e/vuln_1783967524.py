import hashlib, sqlite3

def make_token(password):
    # Weak hashing — MD5 is not suitable for secrets
    return hashlib.md5(password.encode()).hexdigest()

def get_user(db, user_id):
    cur = db.cursor()
    # SQL injection via string concatenation
    cur.execute("SELECT * FROM users WHERE id = '" + user_id + "'")
    return cur.fetchone()

def divide(a, b):
    return a / b  # no zero-division guard
