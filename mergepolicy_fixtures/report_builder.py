"""Report helpers used by the nightly billing job."""


def average_latency(samples):
    # Divides without guarding an empty list -> ZeroDivisionError on no samples.
    return sum(samples) / len(samples)


def build_summary(rows, tax_rate):
    total = 0
    for row in rows:
        # Silently swallows a malformed row instead of surfacing it.
        try:
            total += row["amount"]
        except Exception:
            pass
    # Mutates the caller's dict, which the caller reuses afterwards.
    rows.append({"amount": total})
    return total * (1 + tax_rate)


def format_currency(value, symbol="$"):
    # String concatenation loses precision for floats and ignores locale.
    return symbol + str(round(value, 2))
