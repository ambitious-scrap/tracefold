from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from tracefold.certificates import (
    certificate_hash,
    generate_certificate,
    seal_certificate,
)
from tracefold.compression import compress_source
from tracefold.hashing import hash_canonical, sha256_domain
from tracefold.risk import assess_structural_risk, extract_structural_risk_features
from tracefold.schemas.certificate import (
    Action,
    ComponentVersions,
    FallbackReason,
    PreservationCertificate,
    RecoveryHistoryIntegrity,
    RecoveryRecord,
    RestoredSpan,
    Risk,
)
from tracefold.schemas.common import (
    ArtifactStage,
    FinalAction,
    HashDomain,
    VerificationStatus,
)
from tracefold.schemas.phase2 import ExtractionResult, SourceArtifact
from tracefold.schemas.phase3 import (
    CompressionStatus,
    RawCompressionRequest,
    RawCompressionResult,
)
from tracefold.schemas.phase4 import (
    CertificateCandidate,
    VerificationReport,
    VerificationReportStatus,
)
from tracefold.schemas.phase5 import (
    CalibrationModel,
    RecoveryAttempt,
    RecoveryFailure,
    RecoveryHistory,
    RecoveryPlan,
    RecoveryRequest,
    RecoveryResult,
    StructuralRiskAssessment,
    StructuralRiskFeatures,
)
from tracefold.schemas.source_map import SourceMap
from tracefold.serialization import canonical_json_bytes
from tracefold.sources import normalize_source
from tracefold.tokenizers import TokenizerRegistry, UnknownTokenizerError
from tracefold.tokenizers.base import TokenizerIdentity
from tracefold.verifier import VerificationEvidence, verify_certificate

COMPONENT_VERSION = "tracefold.recovery/0.1.0"
POLICY_VERSION = "1.0.0"
FIXED_TIME = datetime(2000, 1, 1, tzinfo=UTC)
DEFAULT_RESTORE_SPAN_LIMIT = 8
DEFAULT_SAFETY_MARGIN = 8


class RecoveryExecutionError(ValueError):
    """Recovery could not produce verifiable final evidence."""


@dataclass(frozen=True)
class _AttemptDraft:
    number: int
    action: FinalAction
    input_artifact_hash: str
    output_artifact_hash: str
    effective_token_budget: int
    restored_spans: list[RestoredSpan]
    verification_report_hash: str
    result_status: VerificationStatus
    failed_invariant_ids: list[str]
    timestamp: datetime


def _status(report: VerificationReport) -> VerificationStatus:
    if report.status == VerificationReportStatus.VALID:
        return VerificationStatus.PASSED
    if report.status == VerificationReportStatus.UNVERIFIABLE:
        return VerificationStatus.INDETERMINATE
    return VerificationStatus.FAILED


def _empty_history_hash() -> str:
    return hash_canonical(HashDomain.RECOVERY_HISTORY, [])


def _certificate_records(attempts: list[RecoveryAttempt]) -> list[RecoveryRecord]:
    records: list[RecoveryRecord] = []
    previous_event_hash: str | None = None
    for index, attempt in enumerate(attempts):
        records.append(
            RecoveryRecord(
                sequence=index,
                attempt_id=f"recovery:{index}",
                artifact_hash=attempt.output_artifact_hash,
                effective_token_budget=attempt.effective_token_budget,
                verification_status=attempt.result_status,
                failed_invariant_ids=attempt.failed_invariant_ids,
                action_taken=attempt.action,
                next_attempt_id=(f"recovery:{index + 1}" if index + 1 < len(attempts) else None),
                references_valid=True,
                previous_event_hash=previous_event_hash,
                event_hash=attempt.event_hash,
            )
        )
        previous_event_hash = attempt.event_hash
    return records


def _freeze_attempts(drafts: list[_AttemptDraft]) -> list[RecoveryAttempt]:
    attempts: list[RecoveryAttempt] = []
    previous_attempt_hash: str | None = None
    previous_event_hash: str | None = None
    for draft in drafts:
        record = {
            "sequence": draft.number,
            "attempt_id": f"recovery:{draft.number}",
            "artifact_hash": draft.output_artifact_hash,
            "effective_token_budget": draft.effective_token_budget,
            "verification_status": draft.result_status.value,
            "failed_invariant_ids": draft.failed_invariant_ids,
            "action_taken": draft.action.value,
            "next_attempt_id": (
                f"recovery:{draft.number + 1}" if draft.number + 1 < len(drafts) else None
            ),
            "references_valid": True,
            "previous_event_hash": previous_event_hash,
        }
        event_hash = sha256_domain(HashDomain.RECOVERY_EVENT, canonical_json_bytes(record))
        attempt_payload = {
            "attempt_number": draft.number,
            "parent_attempt_hash": previous_attempt_hash,
            "action": draft.action.value,
            "input_artifact_hash": draft.input_artifact_hash,
            "output_artifact_hash": draft.output_artifact_hash,
            "effective_token_budget": draft.effective_token_budget,
            "restored_spans": [item.model_dump(mode="json") for item in draft.restored_spans],
            "verification_report_hash": draft.verification_report_hash,
            "result_status": draft.result_status.value,
            "failed_invariant_ids": draft.failed_invariant_ids,
            "timestamp": draft.timestamp.isoformat(),
            "event_hash": event_hash,
        }
        attempt_hash = sha256_domain(
            HashDomain.RECOVERY_EVENT,
            canonical_json_bytes({"phase5_attempt": attempt_payload}),
        )
        attempt = RecoveryAttempt(
            attempt_number=draft.number,
            parent_attempt_hash=previous_attempt_hash,
            action=draft.action,
            input_artifact_hash=draft.input_artifact_hash,
            output_artifact_hash=draft.output_artifact_hash,
            effective_token_budget=draft.effective_token_budget,
            restored_spans=draft.restored_spans,
            verification_report_hash=draft.verification_report_hash,
            result_status=draft.result_status,
            failed_invariant_ids=draft.failed_invariant_ids,
            timestamp=draft.timestamp,
            event_hash=event_hash,
            attempt_hash=attempt_hash,
        )
        attempts.append(attempt)
        previous_attempt_hash = attempt_hash
        previous_event_hash = event_hash
    return attempts


def build_recovery_history(attempts: Iterable[RecoveryAttempt]) -> RecoveryHistory:
    ordered = list(attempts)
    records = _certificate_records(ordered)
    history_hash = hash_canonical(
        HashDomain.RECOVERY_HISTORY,
        [item.model_dump(mode="json") for item in records],
    )
    return RecoveryHistory(
        records=ordered,
        history_hash=history_hash,
        head_attempt_hash=ordered[-1].attempt_hash if ordered else None,
    )


def verify_recovery_history(history: RecoveryHistory) -> bool:
    records = _certificate_records(history.records)
    expected_history_hash = hash_canonical(
        HashDomain.RECOVERY_HISTORY,
        [item.model_dump(mode="json") for item in records],
    )
    if history.history_hash != expected_history_hash:
        return False
    previous_attempt_hash: str | None = None
    for index, (attempt, record) in enumerate(zip(history.records, records, strict=True)):
        if attempt.attempt_number != index or attempt.parent_attempt_hash != previous_attempt_hash:
            return False
        record_payload = record.model_dump(mode="json", exclude={"event_hash"})
        expected_event_hash = sha256_domain(
            HashDomain.RECOVERY_EVENT,
            canonical_json_bytes(record_payload),
        )
        if attempt.event_hash != expected_event_hash:
            return False
        attempt_payload = {
            "attempt_number": attempt.attempt_number,
            "parent_attempt_hash": attempt.parent_attempt_hash,
            "action": attempt.action.value,
            "input_artifact_hash": attempt.input_artifact_hash,
            "output_artifact_hash": attempt.output_artifact_hash,
            "effective_token_budget": attempt.effective_token_budget,
            "restored_spans": [item.model_dump(mode="json") for item in attempt.restored_spans],
            "verification_report_hash": attempt.verification_report_hash,
            "result_status": attempt.result_status.value,
            "failed_invariant_ids": attempt.failed_invariant_ids,
            "timestamp": attempt.timestamp.isoformat(),
            "event_hash": attempt.event_hash,
        }
        expected_attempt_hash = sha256_domain(
            HashDomain.RECOVERY_EVENT,
            canonical_json_bytes({"phase5_attempt": attempt_payload}),
        )
        if attempt.attempt_hash != expected_attempt_hash:
            return False
        previous_attempt_hash = attempt.attempt_hash
    return history.head_attempt_hash == previous_attempt_hash


def _plan_action(
    raw_result: RawCompressionResult,
    report: VerificationReport,
    *,
    maximum_final_token_budget: int,
    allowed_actions: list[FinalAction],
    restore_span_limit: int,
    original_achieved_reduction: float | None,
    maximum_permitted_reduction_loss: str,
) -> RecoveryPlan:
    codes = {item.code for item in report.failed_checks}
    failed_span_ids = sorted(
        {span_id for item in report.failed_checks for span_id in item.source_span_ids}
    )
    current_budget = raw_result.requested_token_budget or max(raw_result.original_token_count, 1)
    floor = raw_result.minimum_mandatory_token_count
    restoration_codes = {
        "MANDATORY_EVIDENCE_OMITTED",
        "OBLIGATION_NOT_REPRESENTED",
        "RELATION_NOT_REPRESENTED",
    }
    hard_failure_codes = {
        "UNKNOWN_TOKENIZER",
        "EXTRACTION_FAILURE",
        "VERIFIER_EXECUTION_FAILURE",
        "STALE_SOURCE_MAP",
        "SOURCE_MAP_VALIDATION_FAILED",
        "INVALID_SOURCE_MAP",
        "HASH_MISMATCH",
    }
    action = FinalAction.FULL_FALLBACK
    reason_codes = sorted(codes)
    proposed_budget: int | None = None
    expected_increase = 0
    terminal = True
    reduction_loss = 0.0
    if original_achieved_reduction is not None and raw_result.achieved_reduction is not None:
        reduction_loss = max(
            0.0,
            float(original_achieved_reduction) - float(raw_result.achieved_reduction),
        )
    if report.status == VerificationReportStatus.VALID and reduction_loss <= float(
        maximum_permitted_reduction_loss
    ):
        action = FinalAction.EMIT
        terminal = True
    elif report.status == VerificationReportStatus.VALID:
        reason_codes.append("REDUCTION_LOSS_LIMIT")
    elif raw_result.status == CompressionStatus.INCOMPRESSIBLE or codes & {
        "BUDGET_MISMATCH",
        "TOKEN_BUDGET_EXCEEDED",
    }:
        proposed_budget = min(
            maximum_final_token_budget,
            max(current_budget + DEFAULT_SAFETY_MARGIN, floor + DEFAULT_SAFETY_MARGIN),
        )
        expected_increase = max(0, proposed_budget - current_budget)
        if proposed_budget > current_budget:
            action = FinalAction.EXPAND_BUDGET
            terminal = False
    elif codes & restoration_codes and 0 < len(failed_span_ids) <= restore_span_limit:
        proposed_budget = min(
            maximum_final_token_budget,
            max(current_budget + DEFAULT_SAFETY_MARGIN, floor + DEFAULT_SAFETY_MARGIN),
        )
        expected_increase = max(0, proposed_budget - current_budget)
        if proposed_budget >= current_budget and FinalAction.RESTORE_SPANS in allowed_actions:
            action = FinalAction.RESTORE_SPANS
            terminal = False
    elif (
        not codes & hard_failure_codes
        and failed_span_ids
        and FinalAction.RESTORE_SPANS in allowed_actions
    ):
        action = FinalAction.RESTORE_SPANS
        proposed_budget = current_budget
        terminal = False
    if action not in allowed_actions:
        action = FinalAction.FULL_FALLBACK
        terminal = True
    return RecoveryPlan(
        selected_action=action,
        reason_codes=reason_codes,
        failed_invariant_ids=sorted(item.invariant_id for item in report.failed_checks),
        candidate_source_span_ids=failed_span_ids,
        current_budget=current_budget,
        proposed_budget=proposed_budget,
        minimum_mandatory_budget=floor,
        expected_token_increase=expected_increase,
        terminal=terminal,
    )


def _required_span_tokens(
    source: SourceArtifact,
    source_map: SourceMap | None,
    span_ids: Iterable[str],
    registry: TokenizerRegistry,
    tokenizer_id: TokenizerIdentity,
) -> int:
    if source_map is None:
        return 0
    tokenizer = registry.resolve(tokenizer_id)
    spans = {item.span_id: item for item in source_map.spans}
    source_raw = source.raw_bytes
    ranges: list[tuple[int, int]] = []
    for span_id in span_ids:
        span = spans.get(span_id)
        if span is None or span.artifact_id not in {
            artifact.artifact_id
            for artifact in source_map.artifacts
            if artifact.stage == ArtifactStage.ORIGINAL
        }:
            continue
        ranges.append((span.byte_start, span.byte_end))
    ranges.sort()
    total = 0
    end = -1
    for start, stop in ranges:
        if start < end:
            start = end
        if stop > start:
            total += tokenizer.count(source_raw[start:stop].decode("utf-8", "strict"))
            end = stop
    return total


def _restored_spans(
    source_map: SourceMap | None,
    source_span_ids: Iterable[str],
    reason_ids: list[str],
) -> list[RestoredSpan]:
    if source_map is None:
        return []
    spans = {item.span_id: item for item in source_map.spans}
    output_ids = {
        artifact.artifact_id
        for artifact in source_map.artifacts
        if artifact.stage in {ArtifactStage.RAW_COMPRESSED, ArtifactStage.FINAL_COMPRESSED}
    }
    original_ids = {
        artifact.artifact_id
        for artifact in source_map.artifacts
        if artifact.stage == ArtifactStage.ORIGINAL
    }
    restored: list[RestoredSpan] = []
    for source_span_id in sorted(set(source_span_ids)):
        original = spans.get(source_span_id)
        if original is None:
            continue
        source_candidates = [original]
        if original.artifact_id in original_ids:
            source_candidates.extend(
                span
                for span in spans.values()
                if span.span_id != source_span_id
                and span.artifact_id == original.artifact_id
                and span.byte_start < original.byte_end
                and original.byte_start < span.byte_end
            )
        for source_candidate in sorted(
            source_candidates,
            key=lambda span: (span.byte_start, span.byte_end, span.span_id),
        ):
            mapping = None
            output = None
            for item in source_map.mappings:
                if source_candidate.span_id not in item.from_span_ids:
                    continue
                if item.exactness != "byte_exact":
                    continue
                mapped = next(
                    (
                        spans[span_id]
                        for span_id in item.to_span_ids
                        if span_id in spans and spans[span_id].artifact_id in output_ids
                    ),
                    None,
                )
                if mapped is not None:
                    mapping = item
                    output = mapped
                    break
            if output is None or mapping is None:
                continue
            restoration_id = f"restoration:{source_candidate.span_id}:{output.span_id}"
            restored.append(
                RestoredSpan(
                    restoration_id=restoration_id,
                    source_span_id=source_candidate.span_id,
                    original_hash=source_candidate.span_hash,
                    compressed_span_id=output.span_id,
                    inserted_hash=output.span_hash,
                    reason_invariant_ids=reason_ids,
                    byte_exact=True,
                    verified_byte_exact=True,
                )
            )
            break
    return restored


def _request_at_budget(
    request: RawCompressionRequest,
    budget: int,
    attempt: int,
    *,
    restore_span_ids: Iterable[str] = (),
) -> RawCompressionRequest:
    options = dict(request.deterministic_options)
    options["recovery_attempt"] = attempt
    restored = sorted(set(restore_span_ids))
    if restored:
        options["restore_span_ids"] = ",".join(restored)
    else:
        options.pop("restore_span_ids", None)
    return request.model_copy(
        update={
            "target_token_budget": budget,
            "requested_reduction": None,
            "deterministic_options": options,
        }
    )


def _compile_and_verify(
    request: RawCompressionRequest,
    source: SourceArtifact,
    extraction: ExtractionResult,
    registry: TokenizerRegistry,
    verification_run_id: str,
) -> tuple[RawCompressionResult, CertificateCandidate, VerificationReport]:
    raw = compress_source(request, source, registry, extraction=extraction)
    candidate = generate_certificate(request, source, extraction, raw)
    report = verify_certificate(
        candidate,
        VerificationEvidence(
            source=source,
            raw_result=raw,
            registry=registry,
            request=request,
            extraction=extraction,
            normalized_source=normalize_source(source),
            source_map=raw.source_map,
            compressed_text=raw.compressed_text,
            verification_run_id=verification_run_id,
        ),
    )
    return raw, candidate, report


def _enrich_certificate(
    candidate: CertificateCandidate,
    report: VerificationReport,
    assessment: StructuralRiskAssessment,
    action: FinalAction,
    history: RecoveryHistory,
    restored_spans: list[RestoredSpan],
    original_raw: RawCompressionResult,
    *,
    fallback_reason: FallbackReason | None,
    created_at: datetime,
) -> PreservationCertificate:
    sealed = seal_certificate(candidate, report)
    payload = sealed.model_dump(mode="json")
    risk_value = (
        assessment.structural_failure_probability
        if assessment.structural_failure_probability is not None
        else assessment.raw_structural_risk_score
    )
    records = _certificate_records(history.records)
    payload["artifact_role"] = "end_to_end"
    payload["parent_attempt_id"] = original_raw.attempt_id if history.records else None
    payload["artifacts"]["raw_compressed_context"] = {
        "claimed_hash": original_raw.compressed_hash
        or sealed.artifacts.raw_compressed_context.claimed_hash,
        "verified_hash": original_raw.compressed_hash
        or sealed.artifacts.raw_compressed_context.verified_hash,
        "match": True,
    }
    payload["risk"] = Risk(
        score=risk_value,
        recomputed_score=risk_value,
        match=True,
        calibration_status=(
            "calibrated"
            if assessment.calibration_status.value == "calibrated"
            else (
                "not_available"
                if assessment.calibration_status.value == "not_available"
                else "uncalibrated"
            )
        ),
        calibrator_id=assessment.calibration_model_id,
        calibrator_version=("1.0.0" if assessment.calibration_model_id else None),
        feature_manifest_hash=assessment.feature_vector_hash,
        threshold=assessment.decision_threshold,
    ).model_dump(mode="json")
    payload["action"] = Action(
        selected_action=action,
        recomputed_action=action,
        match=True,
        policy_id="tracefold.phase5.recovery",
        policy_version=POLICY_VERSION,
    ).model_dump(mode="json")
    payload["restored_spans"] = [item.model_dump(mode="json") for item in restored_spans]
    payload["recovery_history"] = [item.model_dump(mode="json") for item in records]
    payload["recovery_history_integrity"] = RecoveryHistoryIntegrity(
        claimed_hash=history.history_hash,
        verified_hash=history.history_hash,
        match=True,
        record_count=len(records),
        head_event_hash=(records[-1].event_hash if records else None),
    ).model_dump(mode="json")
    payload["fallback_reason"] = (
        fallback_reason.model_dump(mode="json") if fallback_reason is not None else None
    )
    payload["component_versions"] = ComponentVersions(
        **{
            **sealed.component_versions.model_dump(mode="json"),
            "risk_calibrator": "tracefold.structural-risk/0.1.0",
            "recovery_policy": "tracefold.recovery/0.1.0",
        }
    ).model_dump(mode="json")
    payload["timestamps"] = {
        "run_started_at": created_at.isoformat(),
        "verification_started_at": created_at.isoformat(),
        "verification_completed_at": created_at.isoformat(),
        "certificate_finalized_at": created_at.isoformat(),
    }
    payload["informational"] = {
        **sealed.informational,
        "extensions": {
            **sealed.informational.get("extensions", {}),
            "phase5": True,
            "structural_risk_assessment_hash": assessment.feature_vector_hash,
            "recovery_action": action.value,
        },
    }
    return PreservationCertificate.model_validate(payload)


def _result(
    original_raw: RawCompressionResult,
    final_raw: RawCompressionResult | None,
    certificate: PreservationCertificate | None,
    report: VerificationReport | None,
    assessment: StructuralRiskAssessment,
    attempts: list[RecoveryAttempt],
    action: FinalAction,
    *,
    fallback_reason: FallbackReason | None = None,
    failure: RecoveryFailure | None = None,
    warnings: list[str] | None = None,
) -> RecoveryResult:
    return RecoveryResult(
        final_action=action,
        final_status=report.status.value if report else "failed",
        original_raw_result=original_raw,
        final_raw_result=final_raw,
        final_certificate=certificate,
        final_verification_report=report,
        structural_risk_assessment=assessment,
        attempts=attempts,
        recovery_history_hash=(
            build_recovery_history(attempts).history_hash if attempts else _empty_history_hash()
        ),
        final_token_count=report.compressed_token_count if report else None,
        final_reduction=report.achieved_reduction if report else None,
        restored_span_count=sum(len(item.restored_spans) for item in attempts),
        fallback_reason=fallback_reason,
        warnings=warnings or [],
        failure=failure,
    )


def recover_and_verify(
    request: RecoveryRequest,
    registry: TokenizerRegistry,
    *,
    calibration_model: CalibrationModel | None = None,
    created_at: datetime = FIXED_TIME,
) -> RecoveryResult:
    if created_at.tzinfo is None:
        raise RecoveryExecutionError("created_at must be timezone-aware")
    source = request.source
    candidate = request.certificate
    report = request.verification_report
    raw = request.raw_result
    if candidate is None and raw.status in {
        CompressionStatus.COMPRESSED,
        CompressionStatus.UNCHANGED,
    }:
        try:
            candidate = generate_certificate(request.request, source, request.extraction, raw)
        except ValueError as exc:
            raise RecoveryExecutionError(type(exc).__name__) from exc
    if report is None and candidate is not None:
        report = verify_certificate(
            candidate,
            VerificationEvidence(
                source=source,
                raw_result=raw,
                registry=registry,
                request=request.request,
                extraction=request.extraction,
                normalized_source=normalize_source(source),
                source_map=raw.source_map,
                compressed_text=raw.compressed_text,
            ),
        )
    if report is None:
        features = StructuralRiskFeatures(
            run_id=request.request.run_id,
            verification_status="failed",
            failed_invariant_count=1,
            failed_by_severity={"hard": 1},
            failed_by_class={"parser": 1},
            failed_compression=raw.status == CompressionStatus.FAILED,
        )
        assessment = assess_structural_risk(features, calibration_model=calibration_model)
        failure = RecoveryFailure(
            code="MISSING_VERIFICATION_REPORT", message="primary verification report is required"
        )
        return _result(
            raw, None, None, None, assessment, [], FinalAction.FULL_FALLBACK, failure=failure
        )

    features = extract_structural_risk_features(raw, report)
    plan = _plan_action(
        raw,
        report,
        maximum_final_token_budget=request.maximum_final_token_budget,
        allowed_actions=request.allowed_actions,
        restore_span_limit=int(
            request.deterministic_options.get("restore_span_limit", DEFAULT_RESTORE_SPAN_LIMIT)
        ),
        original_achieved_reduction=raw.achieved_reduction,
        maximum_permitted_reduction_loss=request.maximum_permitted_reduction_loss,
    )
    assessment = assess_structural_risk(
        features,
        calibration_model=calibration_model,
        recommended_action=plan.selected_action,
    )
    if (
        candidate is not None
        and plan.selected_action == FinalAction.EMIT
        and report.status == VerificationReportStatus.VALID
    ):
        sealed = seal_certificate(candidate, report) if candidate is not None else None
        if sealed is not None:
            history = build_recovery_history([])
            final_certificate = _enrich_certificate(
                candidate,
                report,
                assessment,
                FinalAction.EMIT,
                history,
                [],
                raw,
                fallback_reason=None,
                created_at=created_at,
            )
            final_candidate = CertificateCandidate(
                candidate_version="1.0.0",
                source_id=source.source_id,
                normalized_source_hash=final_certificate.informational["extensions"].get(
                    "normalized_source_hash", candidate.normalized_source_hash
                ),
                certificate_hash=certificate_hash(final_certificate),
                certificate=final_certificate,
            )
            final_report = verify_certificate(
                final_candidate,
                VerificationEvidence(
                    source=source,
                    raw_result=raw,
                    registry=registry,
                    request=request.request,
                    extraction=request.extraction,
                    normalized_source=normalize_source(source),
                    source_map=raw.source_map,
                    compressed_text=raw.compressed_text,
                    prior_raw_result=None,
                ),
            )
            return _result(
                raw, raw, final_certificate, final_report, assessment, [], FinalAction.EMIT
            )

    drafts: list[_AttemptDraft] = []
    current_raw = raw
    current_report = report
    current_action = plan.selected_action
    for attempt_number in range(request.maximum_attempts):
        if attempt_number > 0:
            plan = _plan_action(
                current_raw,
                current_report,
                maximum_final_token_budget=request.maximum_final_token_budget,
                allowed_actions=request.allowed_actions,
                restore_span_limit=int(
                    request.deterministic_options.get(
                        "restore_span_limit", DEFAULT_RESTORE_SPAN_LIMIT
                    )
                ),
                original_achieved_reduction=request.raw_result.achieved_reduction,
                maximum_permitted_reduction_loss=request.maximum_permitted_reduction_loss,
            )
            current_action = plan.selected_action
        if (
            attempt_number == request.maximum_attempts - 1
            and current_report.status != VerificationReportStatus.VALID
        ):
            current_action = FinalAction.FULL_FALLBACK
        input_hash = current_raw.compressed_hash or current_raw.source_hash
        if input_hash is None:
            input_hash = sha256_domain(HashDomain.SOURCE_ARTIFACT, source.raw_bytes)
        restored_ids = plan.candidate_source_span_ids
        restored_budget_tokens = 0
        if current_action == FinalAction.RESTORE_SPANS:
            try:
                restored_budget_tokens = _required_span_tokens(
                    source,
                    current_raw.source_map,
                    restored_ids,
                    registry,
                    request.request.tokenizer_id,
                )
            except UnknownTokenizerError:
                current_action = FinalAction.FULL_FALLBACK
        current_budget = current_raw.requested_token_budget or max(
            current_raw.original_token_count, 1
        )
        if current_action == FinalAction.EXPAND_BUDGET:
            proposed = min(
                request.maximum_final_token_budget,
                max(
                    current_budget + max(restored_budget_tokens, DEFAULT_SAFETY_MARGIN),
                    current_raw.minimum_mandatory_token_count + DEFAULT_SAFETY_MARGIN,
                ),
            )
        elif current_action == FinalAction.RESTORE_SPANS:
            proposed = min(
                request.maximum_final_token_budget,
                max(
                    current_budget,
                    current_raw.minimum_mandatory_token_count + DEFAULT_SAFETY_MARGIN,
                ),
            )
        else:
            proposed = current_raw.original_token_count
        if (
            current_action in {FinalAction.RESTORE_SPANS, FinalAction.EXPAND_BUDGET}
            and proposed <= current_budget
        ):
            if current_action == FinalAction.EXPAND_BUDGET:
                current_action = FinalAction.FULL_FALLBACK
            else:
                proposed = current_budget
        attempt_request = _request_at_budget(
            request.request,
            max(1, proposed),
            attempt_number + 1,
            restore_span_ids=restored_ids if current_action == FinalAction.RESTORE_SPANS else (),
        )
        if current_action == FinalAction.FULL_FALLBACK:
            attempt_request = attempt_request.model_copy(
                update={
                    "deterministic_options": {
                        **attempt_request.deterministic_options,
                        "force_full": True,
                    }
                }
            )
        next_raw: RawCompressionResult | None = None
        next_candidate: CertificateCandidate | None = None
        next_report: VerificationReport | None = None
        try:
            next_raw, next_candidate, next_report = _compile_and_verify(
                attempt_request,
                source,
                request.extraction,
                registry,
                request.request.run_id,
            )
        except (ValueError, TypeError, SyntaxError, UnknownTokenizerError) as exc:
            next_report = None
            failure_code = type(exc).__name__
            next_raw = None
            next_candidate = None
            output_hash = input_hash
            drafts.append(
                _AttemptDraft(
                    number=attempt_number,
                    action=current_action,
                    input_artifact_hash=input_hash,
                    output_artifact_hash=output_hash,
                    effective_token_budget=max(1, proposed),
                    restored_spans=[],
                    verification_report_hash=sha256_domain(
                        HashDomain.CERTIFICATE, canonical_json_bytes({"failure": failure_code})
                    ),
                    result_status=VerificationStatus.FAILED,
                    failed_invariant_ids=[failure_code],
                    timestamp=created_at,
                )
            )
            break
        output_hash = next_raw.compressed_hash or input_hash
        restored = _restored_spans(next_raw.source_map, restored_ids, plan.failed_invariant_ids)
        if current_action == FinalAction.RESTORE_SPANS and not restored:
            current_action = FinalAction.FULL_FALLBACK
        next_status = _status(next_report)
        drafts.append(
            _AttemptDraft(
                number=attempt_number,
                action=current_action,
                input_artifact_hash=input_hash,
                output_artifact_hash=output_hash,
                effective_token_budget=max(1, proposed),
                restored_spans=restored,
                verification_report_hash=next_report.certificate_hash,
                result_status=next_status,
                failed_invariant_ids=[item.invariant_id for item in next_report.failed_checks],
                timestamp=created_at,
            )
        )
        if (
            next_report.status == VerificationReportStatus.VALID
            and next_candidate is not None
            and next_raw is not None
        ):
            if current_action in {FinalAction.RESTORE_SPANS, FinalAction.EXPAND_BUDGET}:
                drafts.append(
                    _AttemptDraft(
                        number=attempt_number + 1,
                        action=FinalAction.EMIT,
                        input_artifact_hash=output_hash,
                        output_artifact_hash=output_hash,
                        effective_token_budget=max(1, proposed),
                        restored_spans=[],
                        verification_report_hash=next_report.certificate_hash,
                        result_status=VerificationStatus.PASSED,
                        failed_invariant_ids=[],
                        timestamp=created_at,
                    )
                )
            history = build_recovery_history(_freeze_attempts(drafts))
            fallback_reason = None
            final_action = current_action
            if final_action == FinalAction.FULL_FALLBACK:
                fallback_reason = FallbackReason(
                    code="PHASE5_FALLBACK",
                    message="recovery selected exact full-context fallback",
                    trigger_invariant_ids=plan.failed_invariant_ids,
                    trigger_attempt_id=current_raw.attempt_id,
                    correctness_policy="byte-identical full-context artifact",
                )
            final_certificate = _enrich_certificate(
                next_candidate,
                next_report,
                assessment,
                final_action,
                history,
                restored,
                current_raw,
                fallback_reason=fallback_reason,
                created_at=created_at,
            )
            final_candidate = CertificateCandidate(
                candidate_version="1.0.0",
                source_id=source.source_id,
                normalized_source_hash=next_candidate.normalized_source_hash,
                certificate_hash=certificate_hash(final_certificate),
                certificate=final_certificate,
            )
            final_report = verify_certificate(
                final_candidate,
                VerificationEvidence(
                    source=source,
                    raw_result=next_raw,
                    registry=registry,
                    request=attempt_request,
                    extraction=request.extraction,
                    normalized_source=normalize_source(source),
                    source_map=next_raw.source_map,
                    compressed_text=next_raw.compressed_text,
                    prior_raw_result=current_raw,
                ),
            )
            attempts = _freeze_attempts(drafts)
            return _result(
                request.raw_result,
                next_raw,
                final_certificate,
                final_report,
                assessment,
                attempts,
                final_action,
                fallback_reason=fallback_reason,
            )
        if next_raw is None or next_report is None:
            break
        current_raw, current_report = next_raw, next_report

    attempts = _freeze_attempts(drafts)
    history = build_recovery_history(attempts)
    failure = RecoveryFailure(
        code="RECOVERY_ATTEMPTS_EXHAUSTED",
        message="maximum recovery attempts exhausted without independent verification",
    )
    final_assessment = assess_structural_risk(
        extract_structural_risk_features(current_raw, current_report),
        calibration_model=calibration_model,
        recommended_action=FinalAction.FULL_FALLBACK,
    )
    return _result(
        request.raw_result,
        current_raw,
        None,
        current_report,
        final_assessment,
        attempts,
        FinalAction.FULL_FALLBACK,
        failure=failure,
    )


__all__ = [
    "COMPONENT_VERSION",
    "FIXED_TIME",
    "RecoveryExecutionError",
    "build_recovery_history",
    "recover_and_verify",
    "verify_recovery_history",
]
