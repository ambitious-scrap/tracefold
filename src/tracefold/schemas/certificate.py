from datetime import datetime
from typing import Any, Literal

from pydantic import Field, model_validator

from tracefold.schemas.common import (
    Completeness,
    DiscoveryStatus,
    FailedInvariant,
    FinalAction,
    HashValue,
    ParserWarning,
    Ratio,
    SemVer,
    StrictModel,
    TokenizerIdentity,
    VerificationStatus,
)


class HashObservation(StrictModel):
    claimed_hash: HashValue
    verified_hash: HashValue
    match: bool

    @model_validator(mode="after")
    def correct_match(self) -> "HashObservation":
        if self.match != (self.claimed_hash == self.verified_hash):
            raise ValueError("hash match must equal strict hash equality")
        return self


class SourceMapHashObservation(HashObservation):
    stale: bool


class ArtifactHashes(StrictModel):
    source: HashObservation
    query: HashObservation
    request: HashObservation
    raw_compressed_context: HashObservation
    compressed_context: HashObservation
    source_map: SourceMapHashObservation


class CountObservation(StrictModel):
    claimed: int = Field(ge=0)
    verified: int = Field(ge=0)
    match: bool

    @model_validator(mode="after")
    def correct_match(self) -> "CountObservation":
        if self.match != (self.claimed == self.verified):
            raise ValueError("count match must equal strict count equality")
        return self


class Tokenization(StrictModel):
    target_tokenizer: TokenizerIdentity
    original_token_count: CountObservation
    compressed_token_count: CountObservation


class Reduction(StrictModel):
    request_kind: Literal["reduction_ratio", "token_budget"]
    requested_reduction: Ratio | None
    requested_token_budget: int | None = Field(default=None, ge=1)
    achieved_reduction: "ReductionObservation"


class ReductionObservation(StrictModel):
    claimed: Ratio
    verified: Ratio
    match: bool

    @model_validator(mode="after")
    def correct_match(self) -> "ReductionObservation":
        if self.match != (self.claimed == self.verified):
            raise ValueError("reduction match must equal strict value equality")
        return self


class ObligationClassResult(StrictModel):
    applicability: Literal["applicable", "not_applicable", "unknown"]
    compressor_discovered: int = Field(ge=0)
    compressor_claimed_preserved: int = Field(ge=0)
    verifier_discovered: int = Field(ge=0)
    verifier_verified: int = Field(ge=0)
    failed_obligation_ids: list[str]

    @model_validator(mode="after")
    def verified_bound(self) -> "ObligationClassResult":
        if self.verifier_verified > self.verifier_discovered:
            raise ValueError("verified obligations cannot exceed discovered obligations")
        return self


class Obligations(StrictModel):
    by_class: dict[str, ObligationClassResult]


class RelationResult(StrictModel):
    class_name: str
    compressor_discovered: int = Field(ge=0)
    compressor_claimed_preserved: int = Field(ge=0)
    verifier_discovered: int = Field(ge=0)
    verifier_verified: int = Field(ge=0)
    failed_relation_ids: list[str]
    status: Literal["passed", "failed", "indeterminate", "not_applicable"]


class Relations(StrictModel):
    results: list[RelationResult]


class CertificateCoverage(StrictModel):
    verified_discovered: int = Field(ge=0)
    verifier_discovered: int = Field(ge=0)
    value: Ratio | None


class SourceMapCoverage(StrictModel):
    protected_items_with_valid_map: int = Field(ge=0)
    protected_items: int = Field(ge=0)
    value: Ratio | None
    exact_copy_value: Ratio | None
    lineage_value: Ratio | None


class Coverage(StrictModel):
    certificate: CertificateCoverage
    source_map: SourceMapCoverage
    discovery_status: DiscoveryStatus
    completeness: Completeness

    @model_validator(mode="after")
    def complete_requires_known(self) -> "Coverage":
        if (
            self.completeness == Completeness.COMPLETE
            and self.discovery_status != DiscoveryStatus.KNOWN
        ):
            raise ValueError("complete coverage requires known discovery")
        return self


class Risk(StrictModel):
    score: Ratio | None
    recomputed_score: Ratio | None
    match: bool
    calibration_status: Literal["calibrated", "uncalibrated", "not_available"]
    calibrator_id: str | None
    calibrator_version: str | None
    feature_manifest_hash: HashValue | None
    threshold: Ratio | None


class Action(StrictModel):
    selected_action: FinalAction
    recomputed_action: FinalAction
    match: bool
    policy_id: str
    policy_version: SemVer

    @model_validator(mode="after")
    def correct_match(self) -> "Action":
        if self.match != (self.selected_action == self.recomputed_action):
            raise ValueError("action match must equal strict action equality")
        return self


class RestoredSpan(StrictModel):
    restoration_id: str
    source_span_id: str
    original_hash: HashValue
    compressed_span_id: str
    inserted_hash: HashValue
    reason_invariant_ids: list[str]
    byte_exact: bool
    verified_byte_exact: bool

    @model_validator(mode="after")
    def exact_verified(self) -> "RestoredSpan":
        if not self.verified_byte_exact:
            raise ValueError("restored spans must be verified byte-exact")
        return self


class RecoveryRecord(StrictModel):
    sequence: int = Field(ge=0)
    attempt_id: str
    artifact_hash: HashValue
    effective_token_budget: int = Field(ge=1)
    verification_status: VerificationStatus
    failed_invariant_ids: list[str]
    action_taken: FinalAction
    next_attempt_id: str | None
    references_valid: bool
    previous_event_hash: HashValue | None
    event_hash: HashValue


class RecoveryHistoryIntegrity(StrictModel):
    claimed_hash: HashValue
    verified_hash: HashValue
    match: bool
    record_count: int = Field(ge=0)
    head_event_hash: HashValue | None

    @model_validator(mode="after")
    def correct_match(self) -> "RecoveryHistoryIntegrity":
        if self.match != (self.claimed_hash == self.verified_hash):
            raise ValueError("history match must equal strict hash equality")
        return self


class FallbackReason(StrictModel):
    code: str
    message: str
    trigger_invariant_ids: list[str]
    trigger_attempt_id: str
    correctness_policy: str


class ComponentVersions(StrictModel):
    gateway: str
    normalizer: str
    router: str
    analyzer_registry: str
    compiler_registry: str
    certificate_generator: str
    independent_verifier: str
    risk_calibrator: str
    recovery_policy: str
    source_map_generator: str
    canonical_serializer: str
    hashing: str
    tokenizer_adapter: str


class CertificateTimestamps(StrictModel):
    run_started_at: datetime
    verification_started_at: datetime
    verification_completed_at: datetime
    certificate_finalized_at: datetime

    @model_validator(mode="after")
    def ordered(self) -> "CertificateTimestamps":
        values = [
            self.run_started_at,
            self.verification_started_at,
            self.verification_completed_at,
            self.certificate_finalized_at,
        ]
        if values != sorted(values):
            raise ValueError("certificate timestamps must be nondecreasing")
        return self


class PreservationCertificate(StrictModel):
    schema_id: Literal["tracefold.preservation-certificate"]
    certificate_version: Literal["1.0.0"]
    run_id: str
    attempt_id: str
    parent_attempt_id: str | None
    artifact_role: Literal["raw", "certified", "end_to_end"]
    artifacts: ArtifactHashes
    tokenization: Tokenization
    reduction: Reduction
    obligations: Obligations
    relations: Relations
    coverage: Coverage
    failed_invariants: list[FailedInvariant]
    parser_warnings: list[ParserWarning]
    risk: Risk
    action: Action
    restored_spans: list[RestoredSpan]
    recovery_history: list[RecoveryRecord]
    recovery_history_integrity: RecoveryHistoryIntegrity
    fallback_reason: FallbackReason | None
    component_versions: ComponentVersions
    timestamps: CertificateTimestamps
    verification_status: VerificationStatus
    informational: dict[str, Any]

    @model_validator(mode="after")
    def action_constraints(self) -> "PreservationCertificate":
        action = self.action.selected_action
        if (
            action == FinalAction.EMIT
            and self.artifacts.raw_compressed_context.claimed_hash
            != self.artifacts.compressed_context.claimed_hash
        ):
            raise ValueError("emit requires raw and final context hashes to match")
        if action == FinalAction.RESTORE_SPANS and not self.restored_spans:
            raise ValueError("restore_spans requires non-empty restoration list")
        if action == FinalAction.FULL_FALLBACK and self.fallback_reason is None:
            raise ValueError("full_fallback requires fallback reason")
        if action != FinalAction.EMIT and self.artifact_role != "end_to_end":
            raise ValueError("non-emit action requires end_to_end artifact role")
        return self


Reduction.model_rebuild()
