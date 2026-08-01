import math

import pytest

from tracefold.serialization import canonical_json_bytes, parse_json_strict


def test_canonical_order_nested_arrays_unicode() -> None:
    assert canonical_json_bytes(
        {"b": {"z": 1, "a": "é"}, "a": [True, None]}
    ) == canonical_json_bytes({"a": [True, None], "b": {"a": "é", "z": 1}})


def test_parse_rejects_duplicates_and_nonfinite() -> None:
    with pytest.raises(ValueError):
        parse_json_strict('{"a": 1, "a": 2}')
    with pytest.raises(ValueError):
        parse_json_strict('{"a": NaN}')


def test_unsupported_values_rejected() -> None:
    with pytest.raises((TypeError, ValueError)):
        canonical_json_bytes(object())
    with pytest.raises((TypeError, ValueError)):
        canonical_json_bytes(math.inf)
