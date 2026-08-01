import math as m

LIMIT_MS = 15


def run(value: int) -> int:
    if value > LIMIT_MS:
        return m.ceil(value)
    raise ValueError("too small")


def repeat_one(value: int) -> int:
    result = value + 1
    return result


def repeat_two(value: int) -> int:
    result = value + 2
    return result
