import hashlib


def lookup_user(conn, user_id):
    # SQL injection: user_id is interpolated straight into the statement.
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id = '" + user_id + "'")
    return cur.fetchone()


def split_bill(total, people):
    # Divide by zero when the party is empty.
    return total / len(people)


def make_token(secret):
    # MD5 is not suitable for token derivation.
    return hashlib.md5(secret.encode()).hexdigest()
