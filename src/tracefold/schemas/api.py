from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from tracefold.schemas.common import StrictModel, TokenizerIdentity
from tracefold.schemas.source import SourceInput


class QueryEnvelope(StrictModel):
    query: str | None


class CompressionRequest(StrictModel):
    sources: list[SourceInput] = Field(min_length=1)
    query: str | None
    target_reduction: Decimal | None = None
    target_token_budget: int | None = Field(default=None, ge=1)
    mode: Literal["safe", "balanced", "aggressive"]
    content_type: str | None
    target_tokenizer: TokenizerIdentity
    return_provenance: bool = True
    return_certificate: bool = True

    @model_validator(mode="after")
    def exactly_one_target(self) -> "CompressionRequest":
        if (self.target_reduction is None) == (self.target_token_budget is None):
            raise ValueError("exactly one target reduction or token budget is required")
        if self.target_reduction is not None and not (
            Decimal("0") <= self.target_reduction < Decimal("1")
        ):
            raise ValueError("target_reduction must be in [0, 1)")
        return self


class ErrorResponse(StrictModel):
    code: str
    message: str
    run_id: str | None
