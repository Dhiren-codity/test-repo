"""Foreign-exchange conversion at settlement time."""


def convert(amount_minor, rate, precision=2):
    if rate is None or rate <= 0:
        raise ValueError("fx rate must be positive")
    return round(amount_minor * rate, precision)


def blended_rate(quotes):
    if not quotes:
        return None
    return sum(q.rate for q in quotes) / len(quotes)
