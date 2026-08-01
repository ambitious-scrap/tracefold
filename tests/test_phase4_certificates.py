import base64
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from tracefold.certificates import (
    CertificateGenerationError,
    certificate_hash,
    generate_certificate,
    seal_certificate,
)
from tracefold.compression import compress_source
from tracefold.extractors import extract_obligations
from tracefold.schemas.certificate import HashObservation, PreservationCertificate
from tracefold.schemas.common import HashDomain
from tracefold.schemas.phase2 import ContentType, ExtractionResult, SourceArtifact
from tracefold.schemas.phase3 import (
    CompressionStatus,
    RawCompressionRequest,
    RawCompressionResult,
)
from tracefold.schemas.phase4 import CertificateCandidate, VerificationReportStatus
from tracefold.schemas.source import SourceInput
from tracefold.serialization import canonical_json_bytes
from tracefold.sources import ingest_source, normalize_source
from tracefold.tokenizers import TokenizerIdentity, TokenizerRegistry
from tracefold.verifier import VerificationEvidence, verify_certificate

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "phase4"
RUN_ID = "123e4567-e89b-42d3-a456-426614174000"
BAD_HASH = "sha256:" + "b" * 64


class Phase4FixtureTokenizer:
    """Deterministic, non-production tokenizer for offline certificate tests."""

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
def tokenizer() -> Phase4FixtureTokenizer:
    return Phase4FixtureTokenizer()


@pytest.fixture
def registry(tokenizer: Phase4FixtureTokenizer) -> TokenizerRegistry:
    result = TokenizerRegistry()
    result.register(tokenizer)
    return result


def make_source(name: str, kind: ContentType, ordinal: int = 0) -> SourceArtifact:
    payload = (FIXTURE_ROOT / name).read_bytes()
    return ingest_source(
        SourceInput(
            input_ordinal=ordinal,
            kind=kind.value,
            authority="phase4-fixture",
            media_type="application/json" if kind == ContentType.JSON else "text/plain",
            bytes_base64=base64.b64encode(payload).decode("ascii"),
        )
    )


def make_request(
    source: SourceArtifact,
    kind: ContentType,
    tokenizer: Phase4FixtureTokenizer,
    **options: Any,
) -> RawCompressionRequest:
    return RawCompressionRequest(
        run_id=RUN_ID,
        source_id=source.source_id,
        source_kind=kind,
        tokenizer_id=tokenizer.identity,
        **options,
    )


def build_case(
    name: str,
    kind: ContentType,
    tokenizer: Phase4FixtureTokenizer,
    registry: TokenizerRegistry,
    **options: Any,
) -> tuple[SourceArtifact, RawCompressionRequest, RawCompressionResult, ExtractionResult]:
    source = make_source(name, kind)
    request = make_request(source, kind, tokenizer, **options)
    raw = compress_source(request, source, registry)
    extraction = extract_obligations(source, kind)
    return source, request, raw, extraction


def make_candidate(
    source: SourceArtifact,
    request: RawCompressionRequest,
    raw: RawCompressionResult,
    extraction: ExtractionResult,
) -> CertificateCandidate:
    return generate_certificate(request, source, extraction, raw)


def make_evidence(
    source: SourceArtifact,
    request: RawCompressionRequest,
    raw: RawCompressionResult,
    extraction: ExtractionResult,
    *,
    registry: TokenizerRegistry,
    **updates: Any,
) -> VerificationEvidence:
    values: dict[str, Any] = {
        "source": source,
        "raw_result": raw,
        "registry": registry,
        "request": request,
        "extraction": extraction,
        "normalized_source": normalize_source(source),
        "source_map": raw.source_map,
        "compressed_text": raw.compressed_text,
    }
    values.update(updates)
    return VerificationEvidence(**values)


def rehash_candidate(
    candidate: CertificateCandidate, certificate: PreservationCertificate
) -> CertificateCandidate:
    return candidate.model_copy(
        update={
            "certificate": certificate,
            "certificate_hash": certificate_hash(certificate),
        }
    )


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("repeated_document.txt", ContentType.DOCUMENT),
        ("correction_dialogue.txt", ContentType.DIALOGUE),
        ("anomaly.json", ContentType.JSON),
        ("repetitive.log", ContentType.LOG),
        ("guarded.py", ContentType.PYTHON),
    ],
)
def test_positive_proof_carrying_fixtures(
    name: str,
    kind: ContentType,
    tokenizer: Phase4FixtureTokenizer,
    registry: TokenizerRegistry,
) -> None:
    source, request, raw, extraction = build_case(
        name, kind, tokenizer, registry, requested_reduction=0.0
    )
    assert raw.status == CompressionStatus.COMPRESSED
    candidate = make_candidate(source, request, raw, extraction)
    report = verify_certificate(
        candidate,
        make_evidence(source, request, raw, extraction, registry=registry),
    )
    assert report.status == VerificationReportStatus.VALID
    assert report.recommended_action.value == "emit"
    assert all(item.verified == item.discovered for item in report.relation_results)


def test_unchanged_and_incompressible_results_are_honest(
    tokenizer: Phase4FixtureTokenizer, registry: TokenizerRegistry
) -> None:
    source = ingest_source(
        SourceInput(
            input_ordinal=0,
            kind="document",
            authority="phase4-fixture",
            media_type="text/plain",
            text="One unique sentence.",
        )
    )
    request = make_request(source, ContentType.DOCUMENT, tokenizer, requested_reduction=0.0)
    raw = compress_source(request, source, registry)
    extraction = extract_obligations(source, ContentType.DOCUMENT)
    assert raw.status == CompressionStatus.UNCHANGED
    candidate = make_candidate(source, request, raw, extraction)
    report = verify_certificate(
        candidate,
        make_evidence(source, request, raw, extraction, registry=registry),
    )
    assert report.status == VerificationReportStatus.VALID

    dense_source, dense_request, dense_raw, dense_extraction = build_case(
        "incompressible.txt",
        ContentType.DOCUMENT,
        tokenizer,
        registry,
        target_token_budget=1,
    )
    assert dense_raw.status == CompressionStatus.INCOMPRESSIBLE
    with pytest.raises(CertificateGenerationError):
        make_candidate(dense_source, dense_request, dense_raw, dense_extraction)


def test_failed_raw_result_does_not_get_a_certificate(
    tokenizer: Phase4FixtureTokenizer, registry: TokenizerRegistry
) -> None:
    source = ingest_source(
        SourceInput(
            input_ordinal=0,
            kind="json",
            authority="phase4-fixture",
            media_type="application/json",
            text="{invalid",
        )
    )
    request = make_request(source, ContentType.JSON, tokenizer, target_token_budget=10)
    raw = compress_source(request, source, registry)
    assert raw.status == CompressionStatus.FAILED
    with pytest.raises(CertificateGenerationError):
        generate_certificate(request, source, extract_obligations(source, ContentType.JSON), raw)


def test_candidate_and_report_are_byte_deterministic(
    tokenizer: Phase4FixtureTokenizer, registry: TokenizerRegistry
) -> None:
    source, request, raw, extraction = build_case(
        "repeated_document.txt", ContentType.DOCUMENT, tokenizer, registry, requested_reduction=0.0
    )
    first = make_candidate(source, request, raw, extraction)
    second = make_candidate(source, request, raw, extraction)
    assert canonical_json_bytes(first.model_dump(mode="json")) == canonical_json_bytes(
        second.model_dump(mode="json")
    )
    evidence = make_evidence(source, request, raw, extraction, registry=registry)
    first_report = verify_certificate(first, evidence)
    second_report = verify_certificate(second, evidence)
    assert canonical_json_bytes(first_report.model_dump(mode="json")) == canonical_json_bytes(
        second_report.model_dump(mode="json")
    )


def test_sealing_requires_independent_valid_report(
    tokenizer: Phase4FixtureTokenizer, registry: TokenizerRegistry
) -> None:
    source, request, raw, extraction = build_case(
        "repeated_document.txt", ContentType.DOCUMENT, tokenizer, registry, requested_reduction=0.0
    )
    candidate = make_candidate(source, request, raw, extraction)
    evidence = make_evidence(source, request, raw, extraction, registry=registry)
    report = verify_certificate(candidate, evidence)
    sealed = seal_certificate(candidate, report)
    assert sealed.verification_status.value == "passed"
    with pytest.raises(CertificateGenerationError):
        seal_certificate(candidate, report.model_copy(update={"status": "invalid"}))


def test_hash_observation_and_certificate_hash_tampering_is_rejected(
    tokenizer: Phase4FixtureTokenizer, registry: TokenizerRegistry
) -> None:
    source, request, raw, extraction = build_case(
        "repeated_document.txt", ContentType.DOCUMENT, tokenizer, registry, requested_reduction=0.0
    )
    candidate = make_candidate(source, request, raw, extraction)
    evidence = make_evidence(source, request, raw, extraction, registry=registry)

    changed_source = candidate.certificate.artifacts.source.model_copy(
        update={"claimed_hash": BAD_HASH, "match": False}
    )
    changed_artifacts = candidate.certificate.artifacts.model_copy(
        update={"source": changed_source}
    )
    changed = rehash_candidate(
        candidate, candidate.certificate.model_copy(update={"artifacts": changed_artifacts})
    )
    report = verify_certificate(changed, evidence)
    assert report.status == VerificationReportStatus.INVALID
    assert "HASH_MISMATCH" in {item.code for item in report.failed_checks}

    stale_candidate = candidate.model_copy(update={"certificate_hash": BAD_HASH})
    stale_report = verify_certificate(stale_candidate, evidence)
    assert stale_report.status == VerificationReportStatus.INVALID
    assert "CERTIFICATE_HASH_MISMATCH" in {item.code for item in stale_report.failed_checks}


def test_source_normalization_query_and_compressed_hash_tampering(
    tokenizer: Phase4FixtureTokenizer, registry: TokenizerRegistry
) -> None:
    source, request, raw, extraction = build_case(
        "repeated_document.txt", ContentType.DOCUMENT, tokenizer, registry, requested_reduction=0.0
    )
    candidate = make_candidate(source, request, raw, extraction)
    evidence = make_evidence(source, request, raw, extraction, registry=registry)

    normalized = normalize_source(source).model_copy(
        update={"normalized_text": "tampered", "normalized_bytes": b"tampered"}
    )
    report = verify_certificate(
        candidate, evidence.__class__(**{**evidence.__dict__, "normalized_source": normalized})
    )
    assert report.status == VerificationReportStatus.INVALID
    assert "NORMALIZATION_DISAGREEMENT" in {item.code for item in report.failed_checks}

    query_report = verify_certificate(
        candidate,
        make_evidence(source, request, raw, extraction, registry=registry, query="stale query"),
    )
    assert query_report.status == VerificationReportStatus.INVALID
    assert "QUERY_HASH_MISMATCH" in {item.code for item in query_report.failed_checks}

    altered_report = verify_certificate(
        candidate,
        make_evidence(
            source,
            request,
            raw,
            extraction,
            registry=registry,
            compressed_text=f"{raw.compressed_text} altered",
        ),
    )
    assert altered_report.status == VerificationReportStatus.INVALID
    assert "COMPRESSED_HASH_MISMATCH" in {item.code for item in altered_report.failed_checks}


def test_token_and_reduction_claim_tampering(
    tokenizer: Phase4FixtureTokenizer, registry: TokenizerRegistry
) -> None:
    source, request, raw, extraction = build_case(
        "repeated_document.txt", ContentType.DOCUMENT, tokenizer, registry, requested_reduction=0.0
    )
    candidate = make_candidate(source, request, raw, extraction)
    observation = candidate.certificate.tokenization.original_token_count.model_copy(
        update={"claimed": candidate.certificate.tokenization.original_token_count.claimed + 1}
    )
    tokenization = candidate.certificate.tokenization.model_copy(
        update={"original_token_count": observation}
    )
    changed = rehash_candidate(
        candidate, candidate.certificate.model_copy(update={"tokenization": tokenization})
    )
    report = verify_certificate(
        changed, make_evidence(source, request, raw, extraction, registry=registry)
    )
    assert report.status == VerificationReportStatus.INVALID
    assert "TOKEN_COUNT_MISMATCH" in {item.code for item in report.failed_checks}

    reduction = candidate.certificate.reduction.achieved_reduction.model_copy(
        update={"verified": "0.999999", "match": False}
    )
    reduction_value = candidate.certificate.reduction.model_copy(
        update={"achieved_reduction": reduction}
    )
    changed_reduction = rehash_candidate(
        candidate,
        candidate.certificate.model_copy(update={"reduction": reduction_value}),
    )
    reduction_report = verify_certificate(
        changed_reduction,
        make_evidence(source, request, raw, extraction, registry=registry),
    )
    assert reduction_report.status == VerificationReportStatus.INVALID
    assert "VERIFIED_REDUCTION_MISMATCH" in {item.code for item in reduction_report.failed_checks}


def test_generator_claims_and_extraction_disagreement_are_not_proof(
    tokenizer: Phase4FixtureTokenizer, registry: TokenizerRegistry
) -> None:
    source, request, raw, extraction = build_case(
        "repeated_document.txt", ContentType.DOCUMENT, tokenizer, registry, requested_reduction=0.0
    )
    candidate = make_candidate(source, request, raw, extraction)
    first_class = "instruction.system_developer"
    claim = candidate.certificate.obligations.by_class[first_class].model_copy(
        update={"compressor_discovered": 999}
    )
    claims = dict(candidate.certificate.obligations.by_class)
    claims[first_class] = claim
    obligations = candidate.certificate.obligations.model_copy(update={"by_class": claims})
    changed = rehash_candidate(
        candidate, candidate.certificate.model_copy(update={"obligations": obligations})
    )
    report = verify_certificate(
        changed, make_evidence(source, request, raw, extraction, registry=registry)
    )
    assert report.status == VerificationReportStatus.INVALID
    assert "COMPRESSOR_COVERAGE_CLAIM_MISMATCH" in {item.code for item in report.failed_checks}

    disagreement = extraction.model_copy(update={"obligations": []})
    disagreement_report = verify_certificate(
        candidate,
        make_evidence(source, request, raw, disagreement, registry=registry),
    )
    assert disagreement_report.status == VerificationReportStatus.INVALID
    assert "EXTRACTION_DISAGREEMENT" in {item.code for item in disagreement_report.failed_checks}


def test_unknown_tokenizer_and_missing_primary_evidence_do_not_pass(
    tokenizer: Phase4FixtureTokenizer, registry: TokenizerRegistry
) -> None:
    source, request, raw, extraction = build_case(
        "repeated_document.txt", ContentType.DOCUMENT, tokenizer, registry, requested_reduction=0.0
    )
    candidate = make_candidate(source, request, raw, extraction)
    unknown = candidate.certificate.tokenization.target_tokenizer.model_copy(
        update={"identifier": "not-registered"}
    )
    tokenization_value = candidate.certificate.tokenization.model_copy(
        update={"target_tokenizer": unknown}
    )
    changed = rehash_candidate(
        candidate,
        candidate.certificate.model_copy(update={"tokenization": tokenization_value}),
    )
    report = verify_certificate(
        changed, make_evidence(source, request, raw, extraction, registry=registry)
    )
    assert report.status == VerificationReportStatus.FAILED
    assert "UNKNOWN_TOKENIZER" in {item.code for item in report.failed_checks}

    incomplete_raw = raw.model_copy(
        update={"compressed_text": None, "source_map": None, "compressed_token_count": None}
    )
    no_output_report = verify_certificate(
        candidate,
        make_evidence(
            source,
            request,
            incomplete_raw,
            extraction,
            registry=registry,
            compressed_text=None,
            source_map=None,
        ),
    )
    assert no_output_report.status != VerificationReportStatus.VALID


def test_omitted_mandatory_evidence_recommends_restore(
    tokenizer: Phase4FixtureTokenizer, registry: TokenizerRegistry
) -> None:
    source, request, raw, extraction = build_case(
        "anomaly.json", ContentType.JSON, tokenizer, registry, target_token_budget=200
    )
    assert raw.status == CompressionStatus.COMPRESSED
    assert raw.omitted_spans
    candidate = make_candidate(source, request, raw, extraction)
    report = verify_certificate(
        candidate,
        make_evidence(source, request, raw, extraction, registry=registry),
    )
    assert report.status == VerificationReportStatus.INVALID
    assert "MANDATORY_EVIDENCE_OMITTED" in {item.code for item in report.failed_checks}
    assert report.recommended_action.value == "restore_spans"


def test_source_map_and_synthesized_marker_tampering_is_rejected(
    tokenizer: Phase4FixtureTokenizer, registry: TokenizerRegistry
) -> None:
    source, request, raw, extraction = build_case(
        "repeated_document.txt", ContentType.DOCUMENT, tokenizer, registry, requested_reduction=0.0
    )
    candidate = make_candidate(source, request, raw, extraction)
    assert raw.source_map is not None
    first_span = raw.source_map.spans[0]
    span = raw.source_map.spans[0].model_copy(update={"byte_end": first_span.byte_end + 1})
    changed_map = raw.source_map.model_copy(update={"spans": [span, *raw.source_map.spans[1:]]})
    report = verify_certificate(
        candidate,
        make_evidence(source, request, raw, extraction, registry=registry, source_map=changed_map),
    )
    assert report.status == VerificationReportStatus.INVALID
    source_map_codes = {
        "SOURCE_MAP_DISAGREEMENT",
        "SOURCE_MAP_VALIDATION_FAILED",
        "STALE_SOURCE_MAP",
    }
    assert any(item.code in source_map_codes for item in report.failed_checks)


def test_schema_rejects_invalid_observation_and_report_is_independent(
    tokenizer: Phase4FixtureTokenizer, registry: TokenizerRegistry
) -> None:
    with pytest.raises(ValidationError):
        HashObservation(claimed_hash=BAD_HASH, verified_hash=BAD_HASH, match=False)
    source, request, raw, extraction = build_case(
        "repetitive.log", ContentType.LOG, tokenizer, registry, requested_reduction=0.0
    )
    candidate = make_candidate(source, request, raw, extraction)
    report = verify_certificate(
        candidate, make_evidence(source, request, raw, extraction, registry=registry)
    )
    assert report.verified_source_hash == candidate.certificate.artifacts.source.claimed_hash
    assert report.verified_compressed_artifact_hash == raw.compressed_hash
    assert report.failed_checks == []


def test_phase4_schema_exports_are_importable() -> None:
    from tracefold.schemas import CertificateCandidate as ExportedCandidate

    assert ExportedCandidate is CertificateCandidate
    assert HashDomain.CONTEXT_ARTIFACT.value == "tracefold:context-artifact:1"
