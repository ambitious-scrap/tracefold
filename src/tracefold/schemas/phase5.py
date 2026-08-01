from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from tracefold.run_ids import validate_run_id
from tracefold.schemas.certificate import (
    FallbackReason,
    PreservationCertificate,
    RestoredSpan,
)
from tracefold.schemas.common import (
    FinalAction,
    HashValue,
    Ratio,
    StrictModel,
    VerificationStatus,
)
from tracefold.schemas.phase2 import ContentType, ExtractionResult, SourceArtifact
from tracefold.schemas.phase3 import RawCompressionRequest, RawCompressionResult
from tracefold.schemas.phase4 import (
    CertificateCandidate,
    VerificationReport,
)


class CalibrationStatus(StrEnum):
    CALIBRATED = "calibrated"
    INSUFFICIENT_DATA = "insufficient_data"
    NOT_AVAILABLE = "not_available"


class DataSplit(StrEnum):
    TRAIN = "train"
    VALIDATION = "validation"


class StructuralRiskFeatures(StrictModel):
    feature_version: Literal["1.0.0"] = "1.0.0"
    run_id: str = Field(min_length=1)
    verification_status: str = Field(min_length=1)
    failed_invariant_count: int = Field(ge=0)
    failed_by_severity: dict[str, int] = Field(default_factory=dict)
    failed_by_class: dict[str, int] = Field(default_factory=dict)
    obligation_coverage: dict[str, Ratio | None] = Field(default_factory=dict)
    hard_obligation_coverage: Ratio | None = None
    relation_coverage: Ratio | None = None
    source_map_coverage: Ratio | None = None
    discovery_status_counts: dict[str, int] = Field(default_factory=dict)
    parser_warning_count: int = Field(default=0, ge=0)
    extraction_warning_count: int = Field(default=0, ge=0)
    omitted_span_count: int = Field(default=0, ge=0)
    omitted_mandatory_intersection_count: int = Field(default=0, ge=0)
    requested_reduction: Ratio | None = None
    achieved_reduction: Ratio | None = None
    mandatory_token_floor: int = Field(default=0, ge=0)
    requested_budget: int | None = Field(default=None, ge=1)
    final_token_count: int | None = Field(default=None, ge=0)
    budget_to_floor_margin: int | None = None
    unknown_tokenizer: bool = False
    stale_map: bool = False
    hash_failure: bool = False
    query_hash_failure: bool = False
    incompressible: bool = False
    failed_compression: bool = False

    @model_validator(mode="after")
    def valid_run(self) -> StructuralRiskFeatures:
        validate_run_id(self.run_id)
        if self.budget_to_floor_margin is not None and self.requested_budget is None:
            raise ValueError("budget margin requires requested budget")
        return self


class CalibrationPoint(StrictModel):
    score: Ratio
    probability: Ratio


class StructuralRiskAssessment(StrictModel):
    assessment_version: Literal["1.0.0"]
    run_id: str = Field(min_length=1)
    feature_vector_hash: HashValue
    raw_structural_risk_score: Ratio
    structural_failure_probability: Ratio | None
    calibration_status: CalibrationStatus
    calibration_model_id: str | None
    calibration_sample_count: int = Field(ge=0)
    decision_threshold: Ratio | None
    recommended_action: FinalAction
    reasons: list[str]
    component_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def valid_run(self) -> StructuralRiskAssessment:
        validate_run_id(self.run_id)
        if self.calibration_status == CalibrationStatus.CALIBRATED:
            if self.structural_failure_probability is None:
                raise ValueError("calibrated assessment requires probability")
            if self.calibration_model_id is None:
                raise ValueError("calibrated assessment requires model ID")
        elif self.structural_failure_probability is not None:
            raise ValueError("uncalibrated assessment cannot expose probability")
        return self


class CalibrationRecord(StrictModel):
    example_id: str = Field(min_length=1)
    feature_vector: StructuralRiskFeatures
    observed_outcome: Literal[0, 1]
    data_split: DataSplit
    corruption_type: str = Field(min_length=1)
    source_kind: ContentType
    compressor_status: str = Field(min_length=1)
    verifier_status: str = Field(min_length=1)


class CalibrationModel(StrictModel):
    model_version: Literal["1.0.0"]
    model_kind: Literal["isotonic-pav"]
    training_sample_count: int = Field(ge=0)
    validation_sample_count: int = Field(ge=0)
    feature_names: list[str]
    fitted_parameters: list[CalibrationPoint]
    thresholds: list[Ratio]
    fit_metrics: dict[str, Ratio | None]
    brier_score: Ratio | None
    calibration_error: Ratio | None
    model_hash: HashValue
    training_data_hash: HashValue
    status: CalibrationStatus

    @model_validator(mode="after")
    def valid_status(self) -> CalibrationModel:
        if self.status == CalibrationStatus.CALIBRATED and not self.fitted_parameters:
            raise ValueError("calibrated model requires fitted parameters")
        if self.status != CalibrationStatus.CALIBRATED and self.brier_score is not None:
            raise ValueError("uncalibrated model cannot expose validation metrics")
        return self


class RecoveryRequest(StrictModel):
    source: SourceArtifact
    request: RawCompressionRequest
    extraction: ExtractionResult
    raw_result: RawCompressionResult
    certificate: CertificateCandidate | None = None
    verification_report: VerificationReport | None = None
    maximum_attempts: int = Field(default=3, ge=1)
    maximum_final_token_budget: int = Field(gt=0)
    maximum_permitted_reduction_loss: Ratio = "1.000000"
    allowed_actions: list[FinalAction] = Field(
        default_factory=lambda: [
            FinalAction.EMIT,
            FinalAction.RESTORE_SPANS,
            FinalAction.EXPAND_BUDGET,
            FinalAction.FULL_FALLBACK,
        ]
    )
    deterministic_options: dict[str, str | bool | int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def coherent_request(self) -> RecoveryRequest:
        if self.raw_result.run_id != self.request.run_id:
            raise ValueError("recovery request and raw result run IDs differ")
        if self.raw_result.source_id != self.request.source_id:
            raise ValueError("recovery request and raw result source IDs differ")
        if self.maximum_final_token_budget < 1:
            raise ValueError("maximum final budget must be positive")
        return self


class RecoveryPlan(StrictModel):
    selected_action: FinalAction
    reason_codes: list[str]
    failed_invariant_ids: list[str]
    candidate_source_span_ids: list[str]
    current_budget: int | None = Field(default=None, ge=1)
    proposed_budget: int | None = Field(default=None, ge=1)
    minimum_mandatory_budget: int = Field(ge=0)
    expected_token_increase: int = Field(ge=0)
    terminal: bool


class RecoveryAttempt(StrictModel):
    attempt_number: int = Field(ge=0)
    parent_attempt_hash: HashValue | None
    action: FinalAction
    input_artifact_hash: HashValue
    output_artifact_hash: HashValue
    effective_token_budget: int = Field(ge=1)
    restored_spans: list[RestoredSpan]
    verification_report_hash: HashValue
    result_status: VerificationStatus
    failed_invariant_ids: list[str]
    timestamp: datetime
    event_hash: HashValue
    attempt_hash: HashValue


class RecoveryHistory(StrictModel):
    records: list[RecoveryAttempt]
    history_hash: HashValue
    head_attempt_hash: HashValue | None

    @model_validator(mode="after")
    def ordered_chain(self) -> RecoveryHistory:
        for index, record in enumerate(self.records):
            if record.attempt_number != index:
                raise ValueError("recovery attempts must use contiguous sequence numbers")
            if index and record.parent_attempt_hash != self.records[index - 1].attempt_hash:
                raise ValueError("recovery attempt parent hash does not match prior attempt")
            if not index and record.parent_attempt_hash is not None:
                raise ValueError("first recovery attempt cannot have a parent hash")
        expected_head = self.records[-1].attempt_hash if self.records else None
        if self.head_attempt_hash != expected_head:
            raise ValueError("recovery history head does not match records")
        return self


class RecoveryFailure(StrictModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)


class RecoveryResult(StrictModel):
    final_action: FinalAction
    final_status: str = Field(min_length=1)
    original_raw_result: RawCompressionResult
    final_raw_result: RawCompressionResult | None
    final_certificate: PreservationCertificate | None
    final_verification_report: VerificationReport | None
    structural_risk_assessment: StructuralRiskAssessment
    attempts: list[RecoveryAttempt]
    recovery_history_hash: HashValue
    final_token_count: int | None = Field(default=None, ge=0)
    final_reduction: Ratio | None
    restored_span_count: int = Field(ge=0)
    fallback_reason: FallbackReason | None
    warnings: list[str]
    failure: RecoveryFailure | None


class Phase5Report(StrictModel):
    calibration_record_count: int = Field(ge=0)
    calibration_status: CalibrationStatus
    brier_score: Ratio | None
    calibration_error: Ratio | None
    action_counts: dict[str, int]
    recovery_success_count: int = Field(ge=0)
    fallback_count: int = Field(ge=0)
    mean_restored_tokens: Ratio | None
    final_reductions: dict[str, Ratio | None]
    verification_statuses_before_after: list[tuple[str, str, str]]


__all__ = [
    "CalibrationModel",
    "CalibrationPoint",
    "CalibrationRecord",
    "CalibrationStatus",
    "DataSplit",
    "Phase5Report",
    "RecoveryAttempt",
    "RecoveryFailure",
    "RecoveryHistory",
    "RecoveryPlan",
    "RecoveryRequest",
    "RecoveryResult",
    "StructuralRiskAssessment",
    "StructuralRiskFeatures",
]
