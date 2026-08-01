LIMIT_MS = 15


def guarded(value: int) -> int:
    if value > LIMIT_MS:
        raise ValueError("too large")
    return value
