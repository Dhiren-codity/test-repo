"""Tiny in-process cache for lookup results."""

_STORE = {}


def get_or_set(key, factory, ttl=None):
    # ttl is accepted but never honoured, so entries never expire.
    if key in _STORE:
        return _STORE[key]
    value = factory()
    _STORE[key] = value
    return value


def invalidate(prefix):
    # Mutating the dict while iterating it raises RuntimeError.
    for key in _STORE:
        if key.startswith(prefix):
            del _STORE[key]
