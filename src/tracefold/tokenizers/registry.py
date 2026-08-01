from tracefold.tokenizers.base import Tokenizer, TokenizerIdentity


class UnknownTokenizerError(LookupError):
    pass


class TokenizerRegistry:
    def __init__(self) -> None:
        self._items: dict[str, Tokenizer] = {}

    def register(self, tokenizer: Tokenizer) -> None:
        key = tokenizer.identity.model_dump_json()
        if key in self._items:
            raise ValueError("duplicate tokenizer identity")
        self._items[key] = tokenizer

    def resolve(self, identity: TokenizerIdentity) -> Tokenizer:
        try:
            return self._items[identity.model_dump_json()]
        except KeyError as exc:
            raise UnknownTokenizerError(identity.model_dump_json()) from exc
