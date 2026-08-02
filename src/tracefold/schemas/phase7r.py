"""Public Phase 7R compression request and response records."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from tracefold.schemas.common import FailedInvariant, FinalAction, Ratio, StrictModel
from tracefold.schemas.phase6 import CPRGCMode, CPRGCStatus
from tracefold.tokenizers import TokenizerIdentity


class PublicCompressionRequest(StrictModel):
    source_text: str
    source_kind: Literal["document", "dialogue", "json", "log", "python"]
    media_type: str = Field(default="text/plain", min_length=1)
    file_path: str | None = None
    mode: CPRGCMode = CPRGCMode.TARGET
    target_token_budget: int | None = Field(default=None, ge=1)
    query: str | None = None
    tokenizer_backend: str = Field(min_length=1)
    tokenizer_encoding: str = Field(min_length=1)
    maximum_recovery_attempts: int = Field(default=3, ge=1, le=20)
    maximum_final_budget: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def final_budget_is_coherent(self) -> PublicCompressionRequest:
        if (
            self.target_token_budget is not None
            and self.maximum_final_budget is not None
            and self.maximum_final_budget < self.target_token_budget
        ):
            raise ValueError("maximum_final_budget cannot be below target_token_budget")
        return self


class SourceMapSummary(StrictModel):
    map_id: str | None = None
    artifact_count: int = Field(ge=0)
    span_count: int = Field(ge=0)
    mapping_count: int = Field(ge=0)
    omission_count: int = Field(ge=0)


class RecoverySummary(StrictModel):
    final_status: str | None = None
    final_action: FinalAction
    attempt_count: int = Field(ge=0)
    restored_token_count: int = Field(ge=0)


class PublicCompressionResponse(StrictModel):
    run_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    status: CPRGCStatus
    compressed_context: str
    tokenizer_identity: TokenizerIdentity
    original_tokens: int = Field(ge=0)
    raw_tokens: int | None = Field(default=None, ge=0)
    final_tokens: int | None = Field(default=None, ge=0)
    raw_reduction: Ratio | None = None
    final_reduction: Ratio | None = None
    final_action: FinalAction
    certificate: dict[str, Any] | None = None
    verification_report: dict[str, Any] | None = None
    compact_verification_report: dict[str, Any] | None = None
    failed_invariants: list[FailedInvariant] = Field(default_factory=list)
    recovery: RecoverySummary
    source_map: SourceMapSummary
    warnings: list[str] = Field(default_factory=list)


__all__ = [
    "PublicCompressionRequest",
    "PublicCompressionResponse",
    "RecoverySummary",
    "SourceMapSummary",
]
