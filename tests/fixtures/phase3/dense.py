LIMIT_A = 1
LIMIT_B = 2
LIMIT_C = 3


def dense(value: int) -> int:
    if value > LIMIT_A:
        value = value + LIMIT_B
    if value > LIMIT_B:
        value = value + LIMIT_C
    try:
        return value
    except ValueError:
        raise RuntimeError("invalid") from None
