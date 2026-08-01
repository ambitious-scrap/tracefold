from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from tracefold.run_ids import validate_run_id
from tracefold.schemas.certificate import (
    PreservationCertificate,
    SourceMapCoverage,
)
from tracefold.schemas.common import (
    Completeness,
    DiscoveryStatus,
    FailedInvariant,
    FinalAction,
    HashValue,
    ParserWarning,
    Ratio,
    StrictModel,
    TokenizerIdentity,
)


class VerificationReportStatus(StrEnum):
    VALID = "valid"
    INVALID = "invalid"
    UNVERIFIABLE = "unverifiable"
    FAILED = "failed"


class CertificateCandidate(StrictModel):
    candidate_version: Literal["1.0.0"]
    source_id: str = Field(min_length=1)
    normalized_source_hash: HashValue
    certificate_hash: HashValue
    certificate: PreservationCertificate


class VerifiedObligationResult(StrictModel):
    applicability: Literal["applicable", "not_applicable", "unknown"]
    discovery_status: DiscoveryStatus
    discovered: int = Field(ge=0)
    verified: int = Field(ge=0)
    failed_obligation_ids: list[str]

    @model_validator(mode="after")
    def verified_is_bounded(self) -> "VerifiedObligationResult":
        if self.verified > self.discovered:
            raise ValueError("verified obligations cannot exceed discovered obligations")
        return self


class VerifiedRelationResult(StrictModel):
    class_name: str = Field(min_length=1)
    discovery_status: DiscoveryStatus
    discovered: int = Field(ge=0)
    verified: int = Field(ge=0)
    failed_relation_ids: list[str]
    status: Literal["passed", "failed", "indeterminate", "not_applicable"]

    @model_validator(mode="after")
    def verified_is_bounded(self) -> "VerifiedRelationResult":
        if self.verified > self.discovered:
            raise ValueError("verified relations cannot exceed discovered relations")
        return self


class VerificationReport(StrictModel):
    report_version: Literal["1.0.0"]
    certificate_hash: HashValue
    verification_run_id: str = Field(min_length=1)
    status: VerificationReportStatus
    verified_source_hash: HashValue | None
    verified_normalized_hash: HashValue | None
    verified_query_hash: HashValue | None
    verified_request_hash: HashValue | None
    verified_compressed_artifact_hash: HashValue | None
    verified_tokenizer: TokenizerIdentity | None
    original_token_count: int | None = Field(default=None, ge=0)
    compressed_token_count: int | None = Field(default=None, ge=0)
    achieved_reduction: Ratio | None
    obligation_results: dict[str, VerifiedObligationResult]
    relation_results: list[VerifiedRelationResult]
    source_map_coverage: SourceMapCoverage | None
    discovery_status: DiscoveryStatus
    completeness: Completeness
    failed_checks: list[FailedInvariant]
    warnings: list[ParserWarning]
    recommended_action: FinalAction
    verifier_component_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def valid_run_id(self) -> "VerificationReport":
        validate_run_id(self.verification_run_id)
        if self.completeness == Completeness.COMPLETE:
            if self.discovery_status != DiscoveryStatus.KNOWN:
                raise ValueError("complete report requires known discovery")
        return self


__all__ = [
    "CertificateCandidate",
    "VerifiedObligationResult",
    "VerifiedRelationResult",
    "VerificationReport",
    "VerificationReportStatus",
]
