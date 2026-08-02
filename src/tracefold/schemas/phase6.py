"""Frozen typed records for Phase 6 CPRGC."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from tracefold.schemas.certificate import PreservationCertificate
from tracefold.schemas.common import FinalAction, HashValue, Ratio, StrictModel
from tracefold.schemas.phase2 import ContentType, RelationExactness
from tracefold.schemas.phase3 import RawCompressionResult
from tracefold.schemas.phase4 import CertificateCandidate, VerificationReport
from tracefold.schemas.phase5 import RecoveryResult
from tracefold.schemas.source_map import SourceSpan


class CPRGCMode(StrEnum):
    CONSERVATIVE = "conservative"
    TARGET = "target"
    AGGRESSIVE = "aggressive"


class CPRGCStatus(StrEnum):
    VERIFIED_COMPRESSED = "verified_compressed"
    VERIFIED_REPAIRED = "verified_repaired"
    VERIFIED_FALLBACK = "verified_fallback"
    INCOMPRESSIBLE = "incompressible"
    FAILED = "failed"


class IRNodeKind(StrEnum):
    EXACT_SPAN = "exact_span"
    FACT = "fact"
    RELATION = "relation"
    STRUCTURE = "structure"
    AGGREGATE = "aggregate"
    OMISSION = "omission"


class GraphEdgeType(StrEnum):
    CONTAINS = "contains"
    SOURCE_ORDER = "source_order"
    OBLIGATION_EVIDENCE = "obligation_evidence"
    RELATION_ENDPOINT = "relation_endpoint"
    RELATION_EVIDENCE = "relation_evidence"
    SCOPE = "scope"
    CORRECTION = "correction"
    CONDITION = "condition"
    EXCEPTION = "exception"
    OWNERSHIP = "ownership"
    DEFINITION_USE = "definition_use"
    CALLER_CALLEE = "caller_callee"
    EVENT_TRACE = "event_trace"
    EVENT_TIME = "event_time"
    ERROR_PREDECESSOR = "error_predecessor"
    STRUCTURAL_PARENT = "structural_parent"


class RepresentationKind(StrEnum):
    EXACT = "exact"
    FACT_LEDGER = "fact_ledger"
    RELATION_LEDGER = "relation_ledger"
    SCHEMA_FACTORED = "schema_factored"
    JSON_SLICE = "json_slice"
    LOG_TEMPLATE = "log_template"
    PYTHON_SLICE = "python_slice"
    AGGREGATE = "aggregate"


class ExactSpanNode(StrictModel):
    node_type: Literal["exact_span"] = "exact_span"
    node_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_kind: ContentType
    original_spans: list[SourceSpan] = Field(min_length=1)
    normalized_spans: list[SourceSpan] = Field(default_factory=list)
    exact_text: str
    obligation_ids: list[str] = Field(default_factory=list)
    relation_ids: list[str] = Field(default_factory=list)
    token_cost: int = Field(ge=0)
    protection: Literal["hard", "optional"]
    source_order: int = Field(ge=0)
    extraction_method: str = Field(min_length=1)


class FactNode(StrictModel):
    node_type: Literal["fact"] = "fact"
    node_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_kind: ContentType
    fact_type: str = Field(min_length=1)
    exact_value: str = Field(min_length=1)
    owner: str | None = None
    unit: str | None = None
    scope: str | None = None
    polarity: str | None = None
    temporal_qualifier: str | None = None
    source_spans: list[SourceSpan] = Field(min_length=1)
    obligation_ids: list[str] = Field(default_factory=list)
    relation_ids: list[str] = Field(default_factory=list)
    token_cost: int = Field(ge=0)
    exactness: Literal["exact", "inferred"] = "exact"
    ambiguity: str | None = None

    @model_validator(mode="after")
    def reject_ambiguous_fact(self) -> FactNode:
        if self.ambiguity:
            raise ValueError("ambiguous facts must remain exact source spans")
        return self


class RelationNode(StrictModel):
    node_type: Literal["relation"] = "relation"
    node_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    relation_id: str = Field(min_length=1)
    represented_relation_ids: list[str] = Field(default_factory=list)
    relation_type: str = Field(min_length=1)
    endpoint_node_ids: list[str] = Field(min_length=2)
    evidence_spans: list[SourceSpan] = Field(min_length=1)
    compact_rendering: str = Field(min_length=1)
    exactness: RelationExactness
    mandatory: bool
    token_cost: int = Field(ge=0)


class StructureNode(StrictModel):
    node_type: Literal["structure"] = "structure"
    node_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_kind: ContentType
    structure_type: str = Field(min_length=1)
    exact_text: str
    source_spans: list[SourceSpan] = Field(min_length=1)
    child_node_ids: list[str] = Field(default_factory=list)
    obligation_ids: list[str] = Field(default_factory=list)
    token_cost: int = Field(ge=0)
    source_order: int = Field(ge=0)


class AggregateNode(StrictModel):
    node_type: Literal["aggregate"] = "aggregate"
    node_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    aggregation_rule: str = Field(min_length=1)
    exact_count: int = Field(ge=1)
    first_source_span: SourceSpan
    last_source_span: SourceSpan
    represented_source_ids: list[str] = Field(min_length=1)
    exceptions_excluded: list[str] = Field(default_factory=list)
    token_cost: int = Field(ge=0)


class OmissionNode(StrictModel):
    node_type: Literal["omission"] = "omission"
    node_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    omitted_span_ids: list[str] = Field(min_length=1)
    reason: str = Field(min_length=1)
    represented_by_node_ids: list[str] = Field(default_factory=list)
    token_cost: int = Field(ge=0)


IRNode = ExactSpanNode | FactNode | RelationNode | StructureNode | AggregateNode | OmissionNode


class ContextIR(StrictModel):
    ir_version: Literal["1.0.0"] = "1.0.0"
    source_ids: list[str] = Field(min_length=1)
    source_kind: ContentType
    source_hash: HashValue
    query_hash: HashValue
    nodes: list[IRNode]
    obligation_count: int = Field(ge=0)
    relation_count: int = Field(ge=0)
    component_version: str = Field(min_length=1)


class GraphEdge(StrictModel):
    edge_id: str = Field(min_length=1)
    edge_type: GraphEdgeType
    from_node_id: str = Field(min_length=1)
    to_node_id: str = Field(min_length=1)
    source_ids: list[str] = Field(min_length=1)
    relation_id: str | None = None
    explicit: bool = True


class RelationGraph(StrictModel):
    graph_version: Literal["1.0.0"] = "1.0.0"
    graph_hash: HashValue
    node_ids: list[str]
    edges: list[GraphEdge]
    component_version: str = Field(min_length=1)


class ProtectedClosure(StrictModel):
    node_ids: list[str]
    relation_ids: list[str]
    bridge_node_ids: list[str]
    mandatory_token_cost: int = Field(ge=0)
    reasons: dict[str, list[str]] = Field(default_factory=dict)


class QueryMatch(StrictModel):
    node_id: str = Field(min_length=1)
    exact_identifier_match: int = Field(ge=0)
    exact_numeric_match: int = Field(ge=0)
    exact_path_or_symbol_match: int = Field(ge=0)
    lexical_overlap: int = Field(ge=0)
    bm25_score: str
    graph_distance: int = Field(ge=0)
    relation_bridge_bonus: int = Field(ge=0)
    total_score: str


class BudgetAllocation(StrictModel):
    mode: CPRGCMode
    original_token_count: int = Field(ge=0)
    requested_token_budget: int = Field(ge=1)
    envelope_tokens: int = Field(ge=0)
    mandatory_token_cost: int = Field(ge=0)
    query_neighborhood_tokens: int = Field(ge=0)
    anomaly_tokens: int = Field(ge=0)
    structure_tokens: int = Field(ge=0)
    optional_tokens: int = Field(ge=0)
    recovery_reserve_tokens: int = Field(ge=0)
    incompressible: bool


class RepresentationChoice(StrictModel):
    source_id: str = Field(min_length=1)
    kind: RepresentationKind
    token_count: int = Field(ge=0)
    mandatory_coverage: Ratio | None
    relation_coverage: Ratio | None
    verifier_compatible: bool
    source_map_valid: bool
    parseable: bool | None
    selected: bool
    reason: str = Field(min_length=1)


class CPRGCDiagnostics(StrictModel):
    original_tokens: int = Field(ge=0)
    raw_compressed_tokens: int | None = Field(default=None, ge=0)
    final_tokens: int | None = Field(default=None, ge=0)
    requested_reduction: Ratio | None = None
    raw_reduction: Ratio | None = None
    final_reduction: Ratio | None = None
    mandatory_closure_tokens: int = Field(ge=0)
    compact_fact_tokens: int = Field(ge=0)
    relation_tokens: int = Field(ge=0)
    structure_tokens: int = Field(ge=0)
    optional_evidence_tokens: int = Field(ge=0)
    envelope_tokens: int = Field(ge=0)
    omitted_tokens: int = Field(ge=0)
    certificate_status: str = Field(min_length=1)
    verification_status: str = Field(min_length=1)
    recovery_action: FinalAction
    restored_tokens: int = Field(ge=0)
    representation_choices: list[RepresentationChoice] = Field(default_factory=list)
    budget_allocation: BudgetAllocation
    latency_ms: dict[str, float] = Field(default_factory=dict)


class CompactVerificationReport(StrictModel):
    report_version: Literal["1.0.0"] = "1.0.0"
    status: Literal["valid", "invalid"]
    source_hash: HashValue
    query_hash: HashValue
    verified_fact_count: int = Field(ge=0)
    verified_relation_count: int = Field(ge=0)
    source_map_valid: bool
    parseable: bool | None
    failed_checks: list[str] = Field(default_factory=list)
    component_version: str = Field(min_length=1)


class CPRGCResult(StrictModel):
    status: CPRGCStatus
    final_action: FinalAction
    context: str
    context_ir: ContextIR
    graph: RelationGraph
    protected_closure: ProtectedClosure
    raw_result: RawCompressionResult
    final_result: RawCompressionResult | None
    certificate: CertificateCandidate | PreservationCertificate | None
    verification_report: VerificationReport | None
    recovery_result: RecoveryResult | None
    diagnostics: CPRGCDiagnostics
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def fallback_is_honest(self) -> CPRGCResult:
        if self.status == CPRGCStatus.VERIFIED_FALLBACK:
            if self.diagnostics.final_reduction not in {None, "0.000000"}:
                raise ValueError("fallback cannot report positive reduction")
        return self


__all__ = [
    "AggregateNode",
    "BudgetAllocation",
    "CPRGCMode",
    "CPRGCResult",
    "CPRGCStatus",
    "CPRGCDiagnostics",
    "CompactVerificationReport",
    "ContextIR",
    "ExactSpanNode",
    "FactNode",
    "GraphEdge",
    "GraphEdgeType",
    "IRNode",
    "IRNodeKind",
    "OmissionNode",
    "ProtectedClosure",
    "QueryMatch",
    "RelationGraph",
    "RelationNode",
    "RepresentationChoice",
    "RepresentationKind",
    "StructureNode",
]
