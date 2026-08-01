from enum import StrEnum
from typing import Any

from pydantic import Field, StrictFloat, StrictInt, model_validator

from tracefold.run_ids import validate_run_id
from tracefold.schemas.common import HashValue, StrictModel
from tracefold.schemas.phase2 import ContentType
from tracefold.schemas.source_map import SourceMap, SourceSpan
from tracefold.tokenizers.base import TokenizerIdentity


class CompressionStatus(StrEnum):
    COMPRESSED = "compressed"
    UNCHANGED = "unchanged"
    INCOMPRESSIBLE = "incompressible"
    FAILED = "failed"


class CompilerStrategy(StrEnum):
    AUTO = "auto"
    DETERMINISTIC_EXTRACTIVE = "deterministic-extractive"


class CandidatePriority(StrEnum):
    MANDATORY = "mandatory"
    STRUCTURAL = "structural"
    OPTIONAL = "optional"


class CompressionWarning(StrictModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    severity: str = Field(min_length=1)
    source_ids: list[str] = Field(default_factory=list)
    candidate_ids: list[str] = Field(default_factory=list)


class CompressionFailure(StrictModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    source_ids: list[str] = Field(default_factory=list)
    candidate_ids: list[str] = Field(default_factory=list)


class CoverageCount(StrictModel):
    discovered: int = Field(ge=0)
    mandatory: int = Field(ge=0)
    represented: int = Field(ge=0)

    @model_validator(mode="after")
    def represented_is_bounded(self) -> "CoverageCount":
        if self.mandatory > self.discovered:
            raise ValueError("mandatory coverage cannot exceed discovered count")
        if self.represented > self.discovered:
            raise ValueError("represented coverage cannot exceed discovered count")
        return self


class MandatorySet(StrictModel):
    candidate_ids: list[str]
    obligation_ids: list[str]
    relation_ids: list[str]
    minimum_token_count: int = Field(ge=0)


class SelectionResult(StrictModel):
    selected_candidate_ids: list[str]
    omitted_candidate_ids: list[str]
    token_count: int = Field(ge=0)
    minimum_token_count: int = Field(ge=0)
    fits_budget: bool


class RawCompressionRequest(StrictModel):
    run_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_kind: ContentType
    tokenizer_id: TokenizerIdentity
    target_token_budget: StrictInt | None = Field(default=None, gt=0)
    requested_reduction: StrictFloat | None = Field(default=None, ge=0, lt=1)
    compiler_strategy: CompilerStrategy = CompilerStrategy.AUTO
    deterministic_options: dict[str, str | bool | int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_request(self) -> "RawCompressionRequest":
        validate_run_id(self.run_id)
        if self.source_kind == ContentType.UNKNOWN:
            raise ValueError("source_kind must be a supported Phase 3 content type")
        if self.target_token_budget is None and self.requested_reduction is None:
            raise ValueError("target_token_budget or requested_reduction is required")
        return self


class CompressionCandidate(StrictModel):
    candidate_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    candidate_kind: str = Field(min_length=1)
    emitted_text: str = Field(min_length=1)
    token_cost: int = Field(ge=0)
    priority_class: CandidatePriority
    original_source_spans: list[SourceSpan] = Field(default_factory=list)
    normalized_source_spans: list[SourceSpan] = Field(default_factory=list)
    obligation_ids: list[str] = Field(default_factory=list)
    relation_ids: list[str] = Field(default_factory=list)
    mandatory: bool
    source_map_mapping_ids: list[str] = Field(default_factory=list)
    compiler_rule: str = Field(min_length=1)
    tie_break_key: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class OmittedSpan(StrictModel):
    source_id: str = Field(min_length=1)
    original_span_id: str = Field(min_length=1)
    normalized_span_id: str | None = None
    omission_reason: str = Field(min_length=1)
    obligation_ids: list[str] = Field(default_factory=list)
    relation_ids: list[str] = Field(default_factory=list)
    reversible_from_source_map: bool
    omission_group_id: str = Field(min_length=1)


class RawCompressionResult(StrictModel):
    run_id: str = Field(min_length=1)
    attempt_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_hash: HashValue | None = None
    normalized_source_hash: HashValue | None = None
    tokenizer_id: TokenizerIdentity
    original_token_count: int = Field(ge=0)
    requested_token_budget: int | None = Field(default=None, ge=1)
    requested_reduction: float | None = Field(default=None, ge=0, lt=1)
    compressed_token_count: int | None = Field(default=None, ge=0)
    achieved_reduction: float | None = None
    status: CompressionStatus
    compiler_strategy: CompilerStrategy
    compressed_text: str | None = None
    selected_candidate_ids: list[str] = Field(default_factory=list)
    omitted_spans: list[OmittedSpan] = Field(default_factory=list)
    obligation_coverage: dict[str, CoverageCount] = Field(default_factory=dict)
    relation_coverage: dict[str, CoverageCount] = Field(default_factory=dict)
    minimum_mandatory_token_count: int = Field(ge=0)
    compressed_hash: HashValue | None = None
    source_map: SourceMap | None = None
    warnings: list[CompressionWarning] = Field(default_factory=list)
    failure: CompressionFailure | None = None
    component_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def valid_status_payload(self) -> "RawCompressionResult":
        validate_run_id(self.run_id)
        if self.status == CompressionStatus.FAILED and self.failure is None:
            raise ValueError("failed result requires failure")
        if self.status in {CompressionStatus.COMPRESSED, CompressionStatus.UNCHANGED}:
            if self.compressed_text is None or self.source_map is None:
                raise ValueError("successful result requires text and source map")
            if self.compressed_token_count is None or self.compressed_hash is None:
                raise ValueError("successful result requires compressed token/hash")
        if self.status == CompressionStatus.INCOMPRESSIBLE and self.compressed_text is not None:
            raise ValueError("incompressible result cannot contain compressed text")
        return self


__all__ = [
    "CandidatePriority",
    "CompilerStrategy",
    "CompressionCandidate",
    "CompressionFailure",
    "CompressionStatus",
    "CompressionWarning",
    "CoverageCount",
    "MandatorySet",
    "OmittedSpan",
    "RawCompressionRequest",
    "RawCompressionResult",
    "SelectionResult",
]
