from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tracefold.certificates import certificate_hash, generate_certificate
from tracefold.compression import compress_source
from tracefold.hashing import hash_canonical
from tracefold.recovery import (
    build_recovery_history,
    recover_and_verify,
    verify_recovery_history,
)
from tracefold.risk import (
    assess_structural_risk,
    extract_structural_risk_features,
    feature_vector_hash,
    fit_isotonic_calibrator,
    synthetic_calibration_records,
    verify_calibration_model,
)
from tracefold.schemas.common import FailedInvariant, FinalAction, HashDomain
from tracefold.schemas.phase2 import ContentType, ExtractionResult, SourceArtifact
from tracefold.schemas.phase3 import RawCompressionRequest, RawCompressionResult
from tracefold.schemas.phase4 import (
    CertificateCandidate,
    VerificationReport,
    VerificationReportStatus,
)
from tracefold.schemas.phase5 import (
    CalibrationStatus,
    DataSplit,
    RecoveryRequest,
)
from tracefold.schemas.source import SourceInput
from tracefold.serialization import canonical_json_bytes
from tracefold.sources import ingest_source, normalize_source
from tracefold.tokenizers import TokenizerIdentity, TokenizerRegistry
from tracefold.verifier import VerificationEvidence, verify_certificate

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "phase5"
RUN_ID = "123e4567-e89b-42d3-a456-426614174000"


class Phase5FixtureTokenizer:
    identity = TokenizerIdentity(
        implementation="fixture",
        identifier="fixture",
        revision="1",
        configuration_hash="sha256:" + "a" * 64,
    )

    def encode(self, text: str) -> list[int]:
        return list(text.encode("utf-8"))

    def count(self, text: str) -> int:
        return len(self.encode(text))


@pytest.fixture
def tokenizer() -> Phase5FixtureTokenizer:
    return Phase5FixtureTokenizer()


@pytest.fixture
def registry(tokenizer: Phase5FixtureTokenizer) -> TokenizerRegistry:
    result = TokenizerRegistry()
    result.register(tokenizer)
    return result


def _case(
    tokenizer: Phase5FixtureTokenizer,
    registry: TokenizerRegistry,
    *,
    reduction: float | None = 0.0,
    budget: int | None = None,
    fixture_name: str | None = None,
    kind: ContentType = ContentType.DOCUMENT,
    media_type: str = "text/plain",
) -> tuple[
    SourceArtifact,
    RawCompressionRequest,
    ExtractionResult,
    RawCompressionResult,
    CertificateCandidate,
    VerificationReport,
]:
    fixture_path = (
        FIXTURE_ROOT.parent / "phase4" / "repeated_document.txt"
        if fixture_name is None
        else (
            FIXTURE_ROOT.parent / fixture_name
            if fixture_name.startswith("phase4/")
            else FIXTURE_ROOT / fixture_name
        )
    )
    source = ingest_source(
        SourceInput(
            input_ordinal=0,
            kind=kind.value,
            authority="phase5-fixture",
            media_type=media_type,
            text=fixture_path.read_text(encoding="utf-8"),
        )
    )
    from tracefold.extractors import extract_obligations

    extraction = extract_obligations(source, kind)
    request = RawCompressionRequest(
        run_id=RUN_ID,
        source_id=source.source_id,
        source_kind=kind,
        tokenizer_id=tokenizer.identity,
        target_token_budget=budget,
        requested_reduction=reduction,
    )
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
        ),
    )
    return source, request, extraction, raw, candidate, report


def _invalid_report(
    report: VerificationReport,
    source_span_id: str,
    code: str,
    action: FinalAction,
) -> VerificationReport:
    failure = FailedInvariant(
        invariant_id=f"inv:phase5:{code.lower()}",
        class_name="logic.negation",
        kind="obligation",
        severity="hard",
        code=code,
        message="synthetic Phase 5 recovery trigger",
        source_span_ids=[source_span_id],
        candidate_span_ids=[],
        recovery_hint=action.value,
    )
    return report.model_copy(
        update={
            "status": VerificationReportStatus.INVALID,
            "failed_checks": [failure],
            "recommended_action": action,
        }
    )


def _recovery_request(
    source: SourceArtifact,
    request: RawCompressionRequest,
    extraction: ExtractionResult,
    raw: RawCompressionResult,
    candidate: CertificateCandidate,
    report: VerificationReport,
    *,
    maximum_final_token_budget: int,
) -> RecoveryRequest:
    return RecoveryRequest(
        source=source,
        request=request,
        extraction=extraction,
        raw_result=raw,
        certificate=candidate,
        verification_report=report,
        maximum_attempts=3,
        maximum_final_token_budget=maximum_final_token_budget,
    )


def test_calibration_is_deterministic_and_calibrated() -> None:
    records = synthetic_calibration_records()
    first = fit_isotonic_calibrator(records)
    second = fit_isotonic_calibrator(records)
    assert len(records) == 32
    assert first.status == CalibrationStatus.CALIBRATED
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.brier_score is not None
    assert first.calibration_error is not None
    assert canonical_json_bytes(first.model_dump(mode="json")) == canonical_json_bytes(
        second.model_dump(mode="json")
    )


def test_calibration_requires_minimum_sample_count() -> None:
    records = synthetic_calibration_records()[:29]
    model = fit_isotonic_calibrator(records)
    assert model.status == CalibrationStatus.INSUFFICIENT_DATA
    assert model.brier_score is None
    assert model.calibration_error is None


def test_calibration_hashes_and_threshold_metrics_reject_mutation() -> None:
    from tracefold.risk import coverage_at_threshold, selective_verification_success

    records = synthetic_calibration_records()
    model = fit_isotonic_calibrator(records)
    assert verify_calibration_model(model, records)
    assert coverage_at_threshold(model, records, 0.5) is not None
    assert selective_verification_success(model, records, 0.5) is not None
    tampered = model.model_copy(update={"model_hash": "sha256:" + "f" * 64})
    assert not verify_calibration_model(tampered, records)


def test_features_and_assessment_are_structural_only(
    tokenizer: Phase5FixtureTokenizer, registry: TokenizerRegistry
) -> None:
    source, request, extraction, raw, _, report = _case(tokenizer, registry)
    features = extract_structural_risk_features(raw, report)
    assessment = assess_structural_risk(features)
    assert features.verification_status == "valid"
    assert assessment.structural_failure_probability is None
    assert assessment.calibration_status == CalibrationStatus.NOT_AVAILABLE
    assert feature_vector_hash(features) == assessment.feature_vector_hash
    assert source.source_id == request.source_id


@pytest.mark.parametrize(
    ("fixture_name", "kind", "media_type"),
    [
        ("phase4/repeated_document.txt", ContentType.DOCUMENT, "text/plain"),
        ("phase4/correction_dialogue.txt", ContentType.DIALOGUE, "text/plain"),
        ("phase4/anomaly.json", ContentType.JSON, "application/json"),
        ("phase4/repetitive.log", ContentType.LOG, "text/plain"),
        ("phase4/guarded.py", ContentType.PYTHON, "text/x-python"),
    ],
)
def test_recovery_fixtures_compile_and_verify(
    tokenizer: Phase5FixtureTokenizer,
    registry: TokenizerRegistry,
    fixture_name: str,
    kind: ContentType,
    media_type: str,
) -> None:
    _, _, _, raw, _, report = _case(
        tokenizer,
        registry,
        fixture_name=fixture_name,
        kind=kind,
        media_type=media_type,
    )
    assert raw.status.value in {"compressed", "unchanged"}
    assert report.status == VerificationReportStatus.VALID


def test_valid_certificate_emits_without_recovery(
    tokenizer: Phase5FixtureTokenizer, registry: TokenizerRegistry
) -> None:
    source, request, extraction, raw, candidate, report = _case(tokenizer, registry)
    result = recover_and_verify(
        _recovery_request(
            source,
            request,
            extraction,
            raw,
            candidate,
            report,
            maximum_final_token_budget=raw.original_token_count + 50,
        ),
        registry,
    )
    assert result.final_action == FinalAction.EMIT
    assert result.final_status == "valid"
    assert result.attempts == []
    assert result.final_certificate is not None


def test_missing_obligation_restores_exact_span(
    tokenizer: Phase5FixtureTokenizer, registry: TokenizerRegistry
) -> None:
    source, request, extraction, raw, candidate, report = _case(tokenizer, registry)
    assert raw.source_map is not None
    original_artifact_ids = {
        artifact.artifact_id
        for artifact in raw.source_map.artifacts
        if artifact.stage.value == "original"
    }
    spans_by_id = {span.span_id: span for span in raw.source_map.spans}
    source_span_id = next(
        mapping.from_span_ids[0]
        for mapping in raw.source_map.mappings
        if mapping.from_span_ids
        and mapping.to_span_ids
        and mapping.exactness == "byte_exact"
        and spans_by_id[mapping.from_span_ids[0]].artifact_id in original_artifact_ids
    )
    invalid = _invalid_report(
        report, source_span_id, "OBLIGATION_NOT_REPRESENTED", FinalAction.RESTORE_SPANS
    )
    result = recover_and_verify(
        _recovery_request(
            source,
            request,
            extraction,
            raw,
            candidate,
            invalid,
            maximum_final_token_budget=raw.original_token_count + 50,
        ),
        registry,
    )
    assert result.final_action == FinalAction.RESTORE_SPANS
    assert result.final_status == "valid"
    assert result.restored_span_count >= 1
    assert result.final_certificate is not None


def test_budget_expansion_is_strictly_larger(
    tokenizer: Phase5FixtureTokenizer, registry: TokenizerRegistry
) -> None:
    source, request, extraction, raw, candidate, report = _case(tokenizer, registry)
    source_span_id = extraction.spans[0].span_id
    invalid = _invalid_report(report, source_span_id, "BUDGET_MISMATCH", FinalAction.EXPAND_BUDGET)
    result = recover_and_verify(
        _recovery_request(
            source,
            request,
            extraction,
            raw,
            candidate,
            invalid,
            maximum_final_token_budget=raw.original_token_count + 50,
        ),
        registry,
    )
    assert result.final_action == FinalAction.EXPAND_BUDGET
    assert result.final_status == "valid"
    assert len(result.attempts) >= 1
    assert raw.requested_token_budget is not None
    assert result.attempts[0].effective_token_budget > raw.requested_token_budget


def test_full_fallback_has_zero_reduction(
    tokenizer: Phase5FixtureTokenizer, registry: TokenizerRegistry
) -> None:
    source, request, extraction, raw, candidate, report = _case(tokenizer, registry)
    invalid = _invalid_report(
        report,
        extraction.spans[0].span_id,
        "EXTRACTION_FAILURE",
        FinalAction.FULL_FALLBACK,
    )
    result = recover_and_verify(
        _recovery_request(
            source,
            request,
            extraction,
            raw,
            candidate,
            invalid,
            maximum_final_token_budget=raw.original_token_count,
        ),
        registry,
    )
    assert result.final_action == FinalAction.FULL_FALLBACK
    assert result.final_status == "valid"
    assert result.final_reduction == "0.000000"
    assert result.fallback_reason is not None


def test_history_hash_chain_detects_tampering(
    tokenizer: Phase5FixtureTokenizer, registry: TokenizerRegistry
) -> None:
    source, request, extraction, raw, candidate, report = _case(tokenizer, registry)
    invalid = _invalid_report(
        report, extraction.spans[0].span_id, "OBLIGATION_NOT_REPRESENTED", FinalAction.RESTORE_SPANS
    )
    result = recover_and_verify(
        _recovery_request(
            source,
            request,
            extraction,
            raw,
            candidate,
            invalid,
            maximum_final_token_budget=raw.original_token_count + 50,
        ),
        registry,
    )
    assert result.final_certificate is not None
    assert result.final_verification_report is not None
    assert result.final_raw_result is not None
    tampered = result.final_certificate.model_copy(
        update={
            "recovery_history": [
                result.final_certificate.recovery_history[0].model_copy(
                    update={"event_hash": "sha256:" + "f" * 64}
                )
            ]
        }
    )
    tampered_candidate = CertificateCandidate(
        candidate_version="1.0.0",
        source_id=source.source_id,
        normalized_source_hash=candidate.normalized_source_hash,
        certificate_hash=certificate_hash(tampered),
        certificate=tampered,
    )
    report = verify_certificate(
        tampered_candidate,
        VerificationEvidence(
            source=source,
            raw_result=result.final_raw_result,
            prior_raw_result=raw,
            registry=registry,
            request=request,
            extraction=extraction,
            normalized_source=normalize_source(source),
            source_map=result.final_raw_result.source_map,
            compressed_text=result.final_raw_result.compressed_text,
        ),
    )
    assert report.status == VerificationReportStatus.INVALID
    assert any(item.code == "RECOVERY_EVENT_HASH_MISMATCH" for item in report.failed_checks)


def test_attempt_hash_chain_detects_primary_field_mutation(
    tokenizer: Phase5FixtureTokenizer, registry: TokenizerRegistry
) -> None:
    source, request, extraction, raw, candidate, report = _case(tokenizer, registry)
    invalid = _invalid_report(
        report,
        extraction.spans[0].span_id,
        "BUDGET_MISMATCH",
        FinalAction.EXPAND_BUDGET,
    )
    result = recover_and_verify(
        _recovery_request(
            source,
            request,
            extraction,
            raw,
            candidate,
            invalid,
            maximum_final_token_budget=raw.original_token_count + 50,
        ),
        registry,
    )
    history = build_recovery_history(result.attempts)
    assert verify_recovery_history(history)
    mutated_attempt = history.records[0].model_copy(
        update={"effective_token_budget": history.records[0].effective_token_budget + 1}
    )
    mutated = history.model_copy(update={"records": [mutated_attempt, *history.records[1:]]})
    assert not verify_recovery_history(mutated)


def test_attempt_exhaustion_falls_back(
    tokenizer: Phase5FixtureTokenizer, registry: TokenizerRegistry
) -> None:
    source, request, extraction, raw, candidate, report = _case(tokenizer, registry)
    invalid = _invalid_report(
        report,
        extraction.spans[0].span_id,
        "BUDGET_MISMATCH",
        FinalAction.EXPAND_BUDGET,
    )
    result = recover_and_verify(
        _recovery_request(
            source,
            request,
            extraction,
            raw,
            candidate,
            invalid,
            maximum_final_token_budget=raw.original_token_count + 50,
        ).model_copy(update={"maximum_attempts": 1}),
        registry,
    )
    assert result.final_action == FinalAction.FULL_FALLBACK
    assert result.final_status == "valid"
    assert result.final_reduction == "0.000000"


def test_unknown_tokenizer_is_typed_failure(
    tokenizer: Phase5FixtureTokenizer, registry: TokenizerRegistry
) -> None:
    source, request, extraction, raw, candidate, report = _case(tokenizer, registry)
    unknown_request = request.model_copy(
        update={
            "tokenizer_id": TokenizerIdentity(
                implementation="unknown",
                identifier="unknown",
                revision="1",
                configuration_hash="sha256:" + "b" * 64,
            )
        }
    )
    invalid = _invalid_report(
        report,
        extraction.spans[0].span_id,
        "UNKNOWN_TOKENIZER",
        FinalAction.FULL_FALLBACK,
    )
    recovery = RecoveryRequest(
        source=source,
        request=unknown_request,
        extraction=extraction,
        raw_result=raw,
        certificate=candidate,
        verification_report=invalid,
        maximum_attempts=1,
        maximum_final_token_budget=raw.original_token_count,
    )
    result = recover_and_verify(recovery, registry)
    assert result.final_action == FinalAction.FULL_FALLBACK
    assert result.failure is not None


def test_report_input_hashes_are_stable() -> None:
    records = synthetic_calibration_records()
    model = fit_isotonic_calibrator(records)
    assert model.training_data_hash == hash_canonical(
        HashDomain.RECOVERY_HISTORY,
        {"phase5_calibration_records": [item.model_dump(mode="json") for item in records]},
    )
    assert model.model_hash.startswith("sha256:")
    assert DataSplit.TRAIN.value in {item.data_split.value for item in records}


def test_phase5_report_command_is_byte_deterministic() -> None:
    first = subprocess.check_output([sys.executable, "-m", "tracefold.phase5_report"], text=True)
    second = subprocess.check_output([sys.executable, "-m", "tracefold.phase5_report"], text=True)
    assert first == second
    assert json.loads(first)["calibration_status"] == "calibrated"


def test_restore_spans_keeps_compressed_artifact_when_budget_allows(
    tokenizer: Phase5FixtureTokenizer, registry: TokenizerRegistry
) -> None:
    source, request, extraction, raw, candidate, report = _case(
        tokenizer, registry, budget=400, reduction=None
    )
    invalid = _invalid_report(
        report,
        extraction.spans[0].span_id,
        "OBLIGATION_NOT_REPRESENTED",
        FinalAction.RESTORE_SPANS,
    )
    result = recover_and_verify(
        _recovery_request(
            source,
            request,
            extraction,
            raw,
            candidate,
            invalid,
            maximum_final_token_budget=raw.original_token_count + 10,
        ),
        registry,
    )
    assert result.final_action == FinalAction.RESTORE_SPANS
    assert result.final_raw_result is not None
    assert result.final_raw_result.compressed_token_count is not None
    assert (
        result.final_raw_result.compressed_token_count
        < result.final_raw_result.original_token_count
    )


def test_reduction_loss_limit_does_not_hide_full_fallback(
    tokenizer: Phase5FixtureTokenizer, registry: TokenizerRegistry
) -> None:
    source, request, extraction, raw, candidate, report = _case(
        tokenizer, registry, budget=400, reduction=None
    )
    invalid = _invalid_report(
        report,
        extraction.spans[0].span_id,
        "EXTRACTION_FAILURE",
        FinalAction.FULL_FALLBACK,
    )
    recovery_request = _recovery_request(
        source,
        request,
        extraction,
        raw,
        candidate,
        invalid,
        maximum_final_token_budget=raw.original_token_count,
    ).model_copy(update={"maximum_permitted_reduction_loss": "0.000000"})
    result = recover_and_verify(recovery_request, registry)
    assert result.final_action == FinalAction.FULL_FALLBACK
    assert result.final_reduction == "0.000000"
