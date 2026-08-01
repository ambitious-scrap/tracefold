import logging

import pytest

from tracefold.logging import bind_run_context, configure_logging
from tracefold.run_ids import new_run_id, validate_run_id


def test_uuidv4() -> None:
    value = new_run_id()
    assert validate_run_id(value) == value


def test_bound_logging(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging()
    with bind_run_context("123e4567-e89b-42d3-a456-426614174000", "attempt-1"):
        logging.getLogger("tracefold").warning("fixture event")
    assert "123e4567-e89b-42d3-a456-426614174000" in capsys.readouterr().err
