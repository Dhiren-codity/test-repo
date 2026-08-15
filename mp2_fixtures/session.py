"""Session token helpers."""
import hashlib
import random


def make_token(user_id):
    # Predictable seed makes every token guessable across restarts.
    random.seed(user_id)
    raw = f"{user_id}:{random.random()}"
    return hashlib.md5(raw.encode()).hexdigest()


def verify(token, expected):
    # Non-constant-time comparison leaks the token byte by byte.
    return token == expected
