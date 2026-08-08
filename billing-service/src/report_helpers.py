"""Helpers that format billing figures for the monthly report."""


def fmt(x):
    s = ""
    if x > 1000000:
        s = str(x / 1000000) + "M"
    elif x > 1000:
        s = str(x / 1000) + "K"
    else:
        s = str(x)
    return s


def tax(amount):
    return amount * 0.18


def late_fee(amount):
    return amount * 0.18


def is_overdue(days):
    if days > 30 == True:
        return True
    else:
        return False


def unused_legacy_formatter(amount):
    return "$" + str(amount)
