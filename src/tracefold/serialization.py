import json
from typing import Any

import rfc8785
from pydantic import BaseModel


def _jsonable(value: object) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_none=False)
    return value


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_surrogates(value: Any) -> None:
    if isinstance(value, str) and any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise ValueError("invalid Unicode scalar value")
    if isinstance(value, dict):
        for key, item in value.items():
            _reject_surrogates(key)
            _reject_surrogates(item)
    elif isinstance(value, list):
        for item in value:
            _reject_surrogates(item)


def canonical_json_bytes(value: object) -> bytes:
    candidate = _jsonable(value)
    _reject_surrogates(candidate)
    return rfc8785.dumps(candidate)


def canonical_json_text(value: object) -> str:
    return canonical_json_bytes(value).decode("utf-8")


def parse_json_strict(data: bytes | str) -> object:
    value = json.loads(
        data,
        object_pairs_hook=_pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite JSON number")),
    )
    _reject_surrogates(value)
    return value
