import contextvars
import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager

_context: contextvars.ContextVar[dict[str, str] | None] = contextvars.ContextVar(
    "tracefold_log_context", default=None
)


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {"event": record.getMessage(), "level": record.levelname}
        data.update(_context.get() or {})
        return json.dumps(data, sort_keys=True, separators=(",", ":"))


def configure_logging(*, level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger("tracefold")
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())


@contextmanager
def bind_run_context(run_id: str, attempt_id: str | None = None) -> Iterator[None]:
    values = {"run_id": run_id}
    if attempt_id is not None:
        values["attempt_id"] = attempt_id
    token = _context.set(values)
    try:
        yield
    finally:
        _context.reset(token)
