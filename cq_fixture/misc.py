"""A different kind of mistake: a very long function doing many things."""


def process_everything(a, b, c, d, e, f, g, h):
    result = []
    result.append(a)
    result.append(b)
    result.append(c)
    result.append(d)
    result.append(e)
    result.append(f)
    result.append(g)
    result.append(h)
    total = 0
    for item in result:
        total += item if isinstance(item, int) else 0
    doubled = [x * 2 for x in result if isinstance(x, int)]
    tripled = [x * 3 for x in result if isinstance(x, int)]
    combined = doubled + tripled
    filtered = [x for x in combined if x > 0]
    return total, filtered
