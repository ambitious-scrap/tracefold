import math as m

LIMIT_MS = 15


def run(value: int) -> int:
    if value > LIMIT_MS:
        return m.ceil(value)
    raise ValueError("too small")
