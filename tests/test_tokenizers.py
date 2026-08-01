import pytest

from tracefold.tokenizers import TokenizerIdentity, TokenizerRegistry, UnknownTokenizerError


class FixtureTokenizer:
    """Deterministic non-production tokenizer used only by Phase 1 tests."""

    identity = TokenizerIdentity(
        implementation="fixture",
        identifier="fixture",
        revision="1",
        configuration_hash="sha256:" + "a" * 64,
    )

    def encode(self, text: str) -> list[int]:
        return list(text.encode("utf-8"))

    def count(self, text: str) -> int:
        return len(self.encode(text))


def test_fixture_tokenizer_and_registry() -> None:
    tokenizer = FixtureTokenizer()
    assert tokenizer.encode("é") == tokenizer.encode("é")
    assert tokenizer.count("é") == 2
    registry = TokenizerRegistry()
    registry.register(tokenizer)
    assert registry.resolve(tokenizer.identity) is tokenizer
    with pytest.raises(ValueError):
        registry.register(tokenizer)
    with pytest.raises(UnknownTokenizerError):
        registry.resolve(
            TokenizerIdentity(
                implementation="fixture",
                identifier="other",
                revision="1",
                configuration_hash="sha256:" + "a" * 64,
            )
        )
