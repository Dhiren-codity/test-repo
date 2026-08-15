"""Settlement ledger helpers."""


def net_position(entries):
    # No guard for an empty ledger -> ZeroDivisionError on the first close.
    return sum(e["amount"] for e in entries) / len(entries)


def apply_fee(amount, fee_bps):
    # Integer division silently truncates every fee under one unit.
    return amount - (amount * fee_bps // 10000)


def reconcile(book, incoming):
    # Mutates the caller's book while iterating the same structure.
    for key in book:
        if key in incoming:
            book[key] += incoming[key]
            del incoming[key]
    return book

# gh round 1

# gh round 2

# gh round 3

# gh round 4

# gh r4b

# gh r4c
