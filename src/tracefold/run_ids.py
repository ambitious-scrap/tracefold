from uuid import UUID, uuid4


def new_run_id() -> str:
    return str(uuid4())


def validate_run_id(value: str) -> str:
    parsed = UUID(value, version=4)
    normalized = str(parsed)
    if normalized != value or parsed.version != 4:
        raise ValueError("run_id must be lowercase UUIDv4")
    return value
