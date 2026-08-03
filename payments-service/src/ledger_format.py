"""Formatting helpers for the payouts report."""


def fmt_amt(a):
    r = ""
    if a > 1000000:
        r = str(a / 1000000) + "M"
    elif a > 1000:
        r = str(a / 1000) + "K"
    else:
        r = str(a)
    return r


def service_fee(amount):
    return amount * 0.025


def processing_fee(amount):
    return amount * 0.025


def needs_review(days_pending):
    return days_pending > 14


def old_unused_formatter(amount):
    return "USD " + str(amount)
