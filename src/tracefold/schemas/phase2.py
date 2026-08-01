from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator

from tracefold.schemas.common import DiscoveryStatus, HashValue, StrictModel
from tracefold.schemas.source_map import SourceSpan


class ContentType(StrEnum):
    DOCUMENT = "document"
    DIALOGUE = "dialogue"
    JSON = "json"
    LOG = "log"
    PYTHON = "python"
    UNKNOWN = "unknown"


class CoverageState(StrEnum):
    KNOWN = "known"
    PARTIAL = "partial"
    UNKNOWN = "unknown"
    FAILED = "failed"


class ExtractionConfidence(StrEnum):
    EXACT = "exact"
    INFERRED = "inferred"
    UNKNOWN = "unknown"


class RelationExactness(StrEnum):
    EXACT = "exact"
    INFERRED = "inferred"


OBLIGATION_CLASSES = (
    "instruction.system_developer",
    "role.boundary",
    "identifier.generic",
    "entity.named",
    "numeric.number",
    "numeric.currency",
    "numeric.percentage",
    "numeric.unit",
    "temporal.date",
    "identifier.version",
    "logic.negation",
    "logic.quantifier",
    "policy.permission",
    "policy.prohibition",
    "logic.condition",
    "logic.exception",
    "temporal.correction",
    "dialogue.commitment",
    "structured.json_schema_path",
    "structured.anomalous_row",
    "log.severity_change",
    "temporal.timestamp",
    "identifier.trace_request",
    "code.definition",
    "code.import",
    "code.call",
    "code.constant",
    "code.branch_guard",
    "code.exception_path",
)

RELATION_CLASSES = (
    "relation.value_unit_owner",
    "relation.rule_exception",
    "relation.condition_consequence",
    "relation.statement_correction",
    "relation.instruction_scope",
    "relation.definition_use",
    "relation.caller_callee",
    "relation.import_symbol",
    "relation.event_timestamp",
    "relation.event_trace",
    "relation.error_causal_predecessor",
)


class SourceArtifact(StrictModel):
    source_id: str = Field(min_length=1)
    input_ordinal: int = Field(ge=0)
    kind: str = Field(min_length=1)
    authority: str = Field(min_length=1)
    media_type: str = Field(min_length=1)
    raw_bytes: bytes
    file_path: str | None = None
    message_id: str | None = None
    role: str | None = None


class OffsetMapping(StrictModel):
    original_char_start: int = Field(ge=0)
    original_char_end: int = Field(ge=0)
    normalized_char_start: int = Field(ge=0)
    normalized_char_end: int = Field(ge=0)
    transform: str = Field(min_length=1)

    @model_validator(mode="after")
    def valid_range(self) -> "OffsetMapping":
        if self.original_char_start > self.original_char_end:
            raise ValueError("original normalization range is reversed")
        if self.normalized_char_start > self.normalized_char_end:
            raise ValueError("normalized normalization range is reversed")
        return self


class NormalizationOperation(StrictModel):
    rule_id: str = Field(min_length=1)
    original_char_start: int = Field(ge=0)
    original_char_end: int = Field(ge=0)
    normalized_char_start: int = Field(ge=0)
    normalized_char_end: int = Field(ge=0)
    exactness: str = Field(min_length=1)


class NormalizedSource(StrictModel):
    source: SourceArtifact
    normalized_text: str
    normalized_bytes: bytes
    original_hash: HashValue
    normalized_hash: HashValue
    operations: list[NormalizationOperation]
    original_to_normalized: list[OffsetMapping]
    normalized_to_original: list[OffsetMapping]


class DialogueMessage(StrictModel):
    message_id: str | None = None
    role: str = Field(min_length=1)
    ordinal: int = Field(ge=0)
    text: str


class Obligation(StrictModel):
    obligation_id: str
    class_name: str
    value: Any
    lexeme: str | None = None
    source_id: str
    source_span_ids: list[str] = Field(min_length=1)
    owner_span_ids: list[str] = Field(default_factory=list)
    extraction_method: str = Field(min_length=1)
    confidence: ExtractionConfidence
    discovery_status: DiscoveryStatus
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_class(self) -> "Obligation":
        if self.class_name not in OBLIGATION_CLASSES:
            raise ValueError(f"unsupported obligation class: {self.class_name}")
        return self

    @property
    def spans(self) -> list[str]:
        return self.source_span_ids


class Relation(StrictModel):
    relation_id: str
    relation_type: str
    obligation_ids: list[str] = Field(min_length=2)
    evidence_span_ids: list[str] = Field(min_length=1)
    source_ids: list[str] = Field(min_length=1)
    extraction_method: str = Field(min_length=1)
    discovery_status: DiscoveryStatus
    exactness: RelationExactness
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_class(self) -> "Relation":
        if self.relation_type not in RELATION_CLASSES:
            raise ValueError(f"unsupported relation class: {self.relation_type}")
        if len(set(self.obligation_ids)) != len(self.obligation_ids):
            raise ValueError("relation endpoints must be unique")
        return self


class ExtractionWarning(StrictModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    source_ids: list[str]
    severity: str = Field(min_length=1)


class ExtractionFailure(StrictModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    source_ids: list[str]


class ExtractionResult(StrictModel):
    content_type: ContentType
    sources: list[SourceArtifact]
    normalized_sources: list[NormalizedSource]
    spans: list[SourceSpan]
    obligations: list[Obligation]
    relations: list[Relation]
    coverage: CoverageState
    warnings: list[ExtractionWarning] = Field(default_factory=list)
    failure: ExtractionFailure | None = None

    @model_validator(mode="after")
    def check_ids(self) -> "ExtractionResult":
        span_ids = {getattr(span, "span_id", None) for span in self.spans}
        obligation_ids = {item.obligation_id for item in self.obligations}
        if None in span_ids:
            raise ValueError("extraction spans must expose span_id")
        for obligation in self.obligations:
            if not set(obligation.source_span_ids).issubset(span_ids):
                raise ValueError("obligation references missing source span")
        for relation in self.relations:
            if not set(relation.obligation_ids).issubset(obligation_ids):
                raise ValueError("relation references missing obligation")
            if not set(relation.evidence_span_ids).issubset(span_ids):
                raise ValueError("relation references missing evidence span")
        if self.coverage == CoverageState.FAILED and self.failure is None:
            raise ValueError("failed extraction requires failure")
        return self


class SourceMapValidation(StrictModel):
    valid: bool
    stale: bool
    errors: list[str] = Field(default_factory=list)
