"""Explicit fixture and optional production tokenizer adapters."""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
from collections.abc import Sequence
from typing import Any, cast

from tracefold.tokenizers.base import TokenizerIdentity


class TokenizerConfigurationError(ValueError):
    """Raised when an explicit tokenizer configuration cannot be resolved."""


def _configuration_hash(backend: str, encoding: str) -> str:
    payload = f"backend={backend}\nencoding={encoding}\n".encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


class FixtureByteTokenizer:
    """UTF-8 byte counter for deterministic fixtures, never provider accounting."""

    identity = TokenizerIdentity(
        implementation="fixture-only",
        identifier="utf8-byte",
        revision="1",
        configuration_hash=_configuration_hash("fixture-only", "utf8-byte"),
    )

    def encode(self, text: str) -> Sequence[int]:
        return list(text.encode("utf-8"))

    def count(self, text: str) -> int:
        return len(text.encode("utf-8"))


class TiktokenTokenizer:
    """Production tokenizer using one explicitly named tiktoken encoding."""

    def __init__(self, encoding: str) -> None:
        if not encoding:
            raise TokenizerConfigurationError("tiktoken encoding is required")
        try:
            tiktoken = importlib.import_module("tiktoken")
        except ImportError as exc:  # pragma: no cover - optional dependency path
            raise TokenizerConfigurationError(
                "tiktoken is not installed; install tracefold[tokenizers]"
            ) from exc
        try:
            self._encoding: Any = tiktoken.get_encoding(encoding)
        except ValueError as exc:
            raise TokenizerConfigurationError(f"unknown tiktoken encoding: {encoding}") from exc
        self.identity = TokenizerIdentity(
            implementation="tiktoken",
            identifier=encoding,
            revision=importlib.metadata.version("tiktoken"),
            configuration_hash=_configuration_hash("tiktoken", encoding),
        )

    def encode(self, text: str) -> Sequence[int]:
        return cast(Sequence[int], self._encoding.encode(text, disallowed_special=()))

    def count(self, text: str) -> int:
        return len(self.encode(text))


def resolve_tokenizer(backend: str, encoding: str) -> FixtureByteTokenizer | TiktokenTokenizer:
    """Resolve explicit backend/encoding pairs; never infer from model names."""

    normalized = backend.strip().lower()
    if normalized == "fixture-only":
        if encoding != "utf8-byte":
            raise TokenizerConfigurationError("fixture-only backend requires encoding=utf8-byte")
        return FixtureByteTokenizer()
    if normalized == "tiktoken":
        return TiktokenTokenizer(encoding)
    raise TokenizerConfigurationError(f"unknown tokenizer backend: {backend}")


__all__ = [
    "FixtureByteTokenizer",
    "TiktokenTokenizer",
    "TokenizerConfigurationError",
    "resolve_tokenizer",
]
