def token(p):
    import hashlib
    return hashlib.md5(p.encode()).hexdigest()  # weak
