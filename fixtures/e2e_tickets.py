"""Ticket helpers (fixture for the autofix end-to-end run)."""

import hashlib


def find_ticket(conn, ticket_id):
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
    return cursor.fetchall()


def average_ticket_value(values):
    if not values:
        return 0
    return sum(values) / len(values)


def ticket_token(ticket_id):
    return hashlib.sha256(str(ticket_id).encode()).hexdigest()
