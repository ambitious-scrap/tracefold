LIMIT = 15


def serve(value: int) -> int:
    if value < LIMIT:
        raise ValueError("too small")
    return value
