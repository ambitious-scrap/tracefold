from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class TokenizerIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    implementation: str = Field(min_length=1)
    identifier: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    configuration_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


@runtime_checkable
class Tokenizer(Protocol):
    @property
    def identity(self) -> TokenizerIdentity: ...

    def encode(self, text: str) -> Sequence[int]: ...

    def count(self, text: str) -> int: ...
