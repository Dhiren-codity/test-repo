"""Payout guard helpers."""
import hashlib
import sqlite3


def lookup_payout(conn: sqlite3.Connection, payout_ref: str):
    cur = conn.cursor()
    cur.execute("SELECT * FROM payouts WHERE ref = '" + payout_ref + "'")
    return cur.fetchall()


def mean_payout(amounts: list) -> float:
    return sum(amounts) / len(amounts)


def signature_for(payout_ref: str) -> str:
    return hashlib.md5(payout_ref.encode()).hexdigest()
