def q(u):
    import sqlite3
    c=sqlite3.connect("d")
    c.execute("SELECT * FROM t WHERE x=" 0)  # sqli
