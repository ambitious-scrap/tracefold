from datetime import datetime
from typing import Any, Literal

from pydantic import Field, model_validator

from tracefold.schemas.common import ArtifactStage, HashValue, Ratio, StrictModel


class ArtifactRecord(StrictModel):
    artifact_id: str
    stage: ArtifactStage
    source_id: str | None = None
    attempt_id: str | None = None
    media_type: str
    encoding: str
    byte_length: int = Field(ge=0)
    char_length: int = Field(ge=0)
    line_count: int = Field(ge=0)
    hash: HashValue
    file_path: str | None = None
    message_id: str | None = None
    role: str | None = None

    @model_validator(mode="after")
    def has_owner(self) -> "ArtifactRecord":
        if (self.source_id is None) == (self.attempt_id is None):
            raise ValueError("artifact needs exactly one source_id or attempt_id")
        return self


class SourceSpan(StrictModel):
    span_id: str
    artifact_id: str
    kind: Literal[
        "text",
        "boundary",
        "json_value",
        "json_key",
        "json_container",
        "log_event",
        "code_node",
        "dialogue_turn",
        "tombstone",
        "synthesized",
    ]
    byte_start: int = Field(ge=0)
    byte_end: int = Field(ge=0)
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    line_start: int = Field(ge=1)
    column_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    column_end: int = Field(ge=1)
    span_hash: HashValue
    json_path: str | None = None
    file_path: str | None = None
    code_symbol_id: str | None = None
    log_event_id: str | None = None
    conversation_message_id: str | None = None
    role: str | None = None
    structured_identity: dict[str, Any] | None = None

    @model_validator(mode="after")
    def valid_range(self) -> "SourceSpan":
        if self.byte_start > self.byte_end or self.char_start > self.char_end:
            raise ValueError("span ranges must be half-open and nondecreasing")
        return self


class MappingRecord(StrictModel):
    mapping_id: str
    transform: Literal[
        "exact_copy",
        "normalize_line_ending",
        "delete_normalization_marker",
        "synthesize_boundary",
        "deduplicate",
        "reorder",
        "aggregate",
        "delete",
        "synthesize_summary",
        "restore_exact",
    ]
    from_span_ids: list[str]
    to_span_ids: list[str]
    exactness: Literal[
        "byte_exact",
        "character_equivalent",
        "structurally_equivalent",
        "semantic_lineage_only",
        "none_deleted",
    ]
    ordering: Literal[
        "preserved", "declared_reordered", "many_to_one", "one_to_many", "not_applicable"
    ]
    reason_code: str | None = None
    obligation_ids: list[str] = Field(default_factory=list)
    relation_ids: list[str] = Field(default_factory=list)
    transform_component: str | None = None
    transform_version: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MapCoverage(StrictModel):
    lineage_coverage: Ratio | None = None
    exact_copy_coverage: Ratio | None = None
    protected_item_map_coverage: Ratio | None = None
    original_deletion_coverage: Ratio | None = None
    synthesized_span_count: int = Field(ge=0)
    restored_span_count: int = Field(ge=0)


class NormalizationProfile(StrictModel):
    profile_id: str
    version: str
    rules: list[str]


class SourceMap(StrictModel):
    schema_id: Literal["tracefold.source-map"]
    source_map_version: Literal["1.0.0"]
    map_id: str
    run_id: str
    attempt_id: str
    source_manifest_hash: HashValue
    query_hash: HashValue
    artifacts: list[ArtifactRecord]
    spans: list[SourceSpan]
    mappings: list[MappingRecord]
    forward_index: dict[str, list[str]]
    reverse_index: dict[str, list[str]]
    coverage: MapCoverage
    normalization_profile: NormalizationProfile
    component_version: str
    created_at: datetime

    @model_validator(mode="after")
    def indexes_match(self) -> "SourceMap":
        mappings = {item.mapping_id: item for item in self.mappings}
        if len(mappings) != len(self.mappings):
            raise ValueError("duplicate mapping IDs")
        forward: dict[str, list[str]] = {}
        reverse: dict[str, list[str]] = {}
        for mapping in self.mappings:
            for span_id in mapping.from_span_ids:
                forward.setdefault(span_id, []).append(mapping.mapping_id)
            for span_id in mapping.to_span_ids:
                reverse.setdefault(span_id, []).append(mapping.mapping_id)
        if forward != self.forward_index or reverse != self.reverse_index:
            raise ValueError("source-map indexes do not match mappings")
        return self
