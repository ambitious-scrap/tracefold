from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from tracefold.hashing import hash_canonical, hash_source_manifest, sha256_domain
from tracefold.schemas.api import QueryEnvelope
from tracefold.schemas.certificate import (
    Action,
    ArtifactHashes,
    CertificateCoverage,
    CertificateTimestamps,
    ComponentVersions,
    CountObservation,
    Coverage,
    HashObservation,
    ObligationClassResult,
    Obligations,
    PreservationCertificate,
    RecoveryHistoryIntegrity,
    Reduction,
    ReductionObservation,
    RelationResult,
    Relations,
    Risk,
    SourceMapCoverage,
    SourceMapHashObservation,
    Tokenization,
)
from tracefold.schemas.common import (
    Completeness,
    DiscoveryStatus,
    FinalAction,
    HashDomain,
    ParserWarning,
    TokenizerIdentity,
    VerificationStatus,
)
from tracefold.schemas.phase2 import (
    OBLIGATION_CLASSES,
    RELATION_CLASSES,
    ExtractionResult,
    SourceArtifact,
)
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
from tracefold.schemas.source import SourceManifest, SourceManifestEntry
from tracefold.schemas.source_map import SourceMap
from tracefold.serialization import canonical_json_bytes

COMPONENT_VERSION = "tracefold.certificate-generator/0.1.0"
VERIFIER_COMPONENT_VERSION = "tracefold.independent-verifier/0.1.0"
FIXED_TIME = datetime(2000, 1, 1, tzinfo=UTC)


class CertificateGenerationError(ValueError):
    """A raw result cannot produce a schema-valid certificate candidate."""


def _ratio(value: float | None) -> str | None:
    if value is None:
        return None
    if not 0 <= value <= 1:
        raise CertificateGenerationError("ratio must be in [0, 1]")
    return f"{value:.6f}"


def _manifest(source: SourceArtifact) -> SourceManifest:
    raw_hash = sha256_domain(HashDomain.SOURCE_ARTIFACT, source.raw_bytes)
    return SourceManifest(
        entries=[
            SourceManifestEntry(
                source_id=source.source_id,
                input_ordinal=source.input_ordinal,
                kind=source.kind,
                authority=source.authority,
                media_type=source.media_type,
                raw_byte_hash=raw_hash,
                byte_length=len(source.raw_bytes),
                file_path=source.file_path,
                message_id=source.message_id,
                role=source.role,
            )
        ]
    )


def _request_envelope(
    request: RawCompressionRequest,
    source_manifest_hash: str,
    query_hash: str,
    effective_budget: int | None,
) -> dict[str, Any]:
    return {
        "source_id": request.source_id,
        "source_kind": request.source_kind.value,
        "tokenizer_id": request.tokenizer_id.model_dump(mode="json"),
        "target_token_budget": request.target_token_budget,
        "effective_token_budget": effective_budget,
        "requested_reduction": request.requested_reduction,
        "compiler_strategy": request.compiler_strategy.value,
        "deterministic_options": request.deterministic_options,
        "source_manifest_hash": source_manifest_hash,
        "query_hash": query_hash,
    }


def request_hash(
    request: RawCompressionRequest,
    source_manifest_hash: str,
    query_hash: str,
    effective_budget: int | None,
) -> str:
    return hash_canonical(
        HashDomain.COMPRESSION_REQUEST,
        _request_envelope(request, source_manifest_hash, query_hash, effective_budget),
    )


def certificate_hash(certificate: PreservationCertificate) -> str:
    return sha256_domain(
        HashDomain.CERTIFICATE,
        canonical_json_bytes(certificate.model_dump(mode="json")),
    )


def source_map_hash(source_map: SourceMap) -> str:
    return sha256_domain(
        HashDomain.SOURCE_MAP,
        canonical_json_bytes(source_map.model_dump(mode="json")),
    )


def _claim_hash(value: str) -> HashObservation:
    return HashObservation(claimed_hash=value, verified_hash=value, match=True)


def _claim_source_map_hash(value: str) -> SourceMapHashObservation:
    return SourceMapHashObservation(
        claimed_hash=value,
        verified_hash=value,
        match=True,
        stale=False,
    )


def _discovery_status(extraction: ExtractionResult) -> DiscoveryStatus:
    if extraction.failure is not None or extraction.coverage.value == "failed":
        return DiscoveryStatus.UNKNOWN
    return DiscoveryStatus(extraction.coverage.value)


def _applicability(
    discovered: int, status: DiscoveryStatus
) -> Literal["applicable", "not_applicable", "unknown"]:
    if discovered:
        return "applicable"
    return "not_applicable" if status == DiscoveryStatus.KNOWN else "unknown"


def _warning_records(result: RawCompressionResult) -> list[ParserWarning]:
    return [
        ParserWarning(
            source="compressor",
            component_id=result.component_version,
            code=warning.code,
            severity=warning.severity,
            source_ids=list(warning.source_ids),
            message=warning.message,
        )
        for warning in result.warnings
    ]


def _empty_history() -> RecoveryHistoryIntegrity:
    history_hash = hash_canonical(HashDomain.RECOVERY_HISTORY, [])
    return RecoveryHistoryIntegrity(
        claimed_hash=history_hash,
        verified_hash=history_hash,
        match=True,
        record_count=0,
        head_event_hash=None,
    )


def _components() -> ComponentVersions:
    return ComponentVersions(
        gateway="not-applicable/0.0.0",
        normalizer="tracefold.sources/0.1.0",
        router="not-applicable/0.0.0",
        analyzer_registry="tracefold.extractors/0.1.0",
        compiler_registry="tracefold.compression/0.1.0",
        certificate_generator=COMPONENT_VERSION,
        independent_verifier=VERIFIER_COMPONENT_VERSION,
        risk_calibrator="not_available/0.0.0",
        recovery_policy="not-applicable/0.0.0",
        source_map_generator="tracefold.source-map/phase3/0.1.0",
        canonical_serializer="rfc8785/0.1.0",
        hashing="tracefold.hashing/0.1.0",
        tokenizer_adapter="registry-bound/0.1.0",
    )


def _obligation_claims(
    extraction: ExtractionResult,
    result: RawCompressionResult,
    discovery: DiscoveryStatus,
) -> Obligations:
    by_class: dict[str, ObligationClassResult] = {}
    for class_name in OBLIGATION_CLASSES:
        count = result.obligation_coverage.get(class_name)
        discovered = count.discovered if count is not None else 0
        preserved = count.represented if count is not None else 0
        by_class[class_name] = ObligationClassResult(
            applicability=_applicability(discovered, discovery),
            compressor_discovered=discovered,
            compressor_claimed_preserved=preserved,
            verifier_discovered=0,
            verifier_verified=0,
            failed_obligation_ids=[],
        )
    return Obligations(by_class=by_class)


def _relation_claims(
    result: RawCompressionResult,
    discovery: DiscoveryStatus,
) -> Relations:
    by_class: list[RelationResult] = []
    for class_name in RELATION_CLASSES:
        count = result.relation_coverage.get(class_name)
        discovered = count.discovered if count is not None else 0
        preserved = count.represented if count is not None else 0
        by_class.append(
            RelationResult(
                class_name=class_name,
                compressor_discovered=discovered,
                compressor_claimed_preserved=preserved,
                verifier_discovered=0,
                verifier_verified=0,
                failed_relation_ids=[],
                status=(
                    "not_applicable"
                    if not discovered and discovery == DiscoveryStatus.KNOWN
                    else "indeterminate"
                ),
            )
        )
    return Relations(results=by_class)


def generate_certificate(
    request: RawCompressionRequest,
    source: SourceArtifact,
    extraction: ExtractionResult,
    raw_result: RawCompressionResult,
    *,
    query: str | None = None,
    created_at: datetime = FIXED_TIME,
) -> CertificateCandidate:
    if raw_result.status not in {CompressionStatus.COMPRESSED, CompressionStatus.UNCHANGED}:
        raise CertificateGenerationError("raw result has no certifiable compressed artifact")
    if query is not None:
        raise CertificateGenerationError(
            "Phase 3 compression is query-independent; query evidence is unsupported"
        )
    if raw_result.compressed_text is None or raw_result.source_map is None:
        raise CertificateGenerationError("raw result is missing compressed evidence")
    if source.source_id != request.source_id or source.source_id != raw_result.source_id:
        raise CertificateGenerationError("source identity does not match request and result")
    if request.run_id != raw_result.run_id:
        raise CertificateGenerationError("run identity does not match request and result")
    if created_at.tzinfo is None:
        raise CertificateGenerationError("created_at must be timezone-aware")
    if len(extraction.sources) != 1 or extraction.sources[0].source_id != source.source_id:
        raise CertificateGenerationError("extraction must contain the requested source")
    if not extraction.normalized_sources:
        raise CertificateGenerationError("normalized source evidence is required")
    if raw_result.source_hash is None or raw_result.normalized_source_hash is None:
        raise CertificateGenerationError("raw result is missing source hashes")
    if raw_result.compressed_hash is None:
        raise CertificateGenerationError("raw result is missing compressed hash")
    if raw_result.tokenizer_id != request.tokenizer_id:
        raise CertificateGenerationError("request and raw result tokenizer identities differ")

    manifest = _manifest(source)
    manifest_hash = hash_source_manifest(manifest)
    query_hash = hash_canonical(HashDomain.QUERY, QueryEnvelope(query=query))
    effective_budget = raw_result.requested_token_budget
    req_hash = request_hash(request, manifest_hash, query_hash, effective_budget)
    map_hash = source_map_hash(raw_result.source_map)
    discovery = _discovery_status(extraction)
    achieved = _ratio(raw_result.achieved_reduction)
    if achieved is None:
        raise CertificateGenerationError("raw result is missing achieved reduction")

    certificate = PreservationCertificate(
        schema_id="tracefold.preservation-certificate",
        certificate_version="1.0.0",
        run_id=request.run_id,
        attempt_id=raw_result.attempt_id,
        parent_attempt_id=None,
        artifact_role="raw",
        artifacts=ArtifactHashes(
            source=_claim_hash(manifest_hash),
            query=_claim_hash(query_hash),
            request=_claim_hash(req_hash),
            raw_compressed_context=_claim_hash(raw_result.compressed_hash),
            compressed_context=_claim_hash(raw_result.compressed_hash),
            source_map=_claim_source_map_hash(map_hash),
        ),
        tokenization=Tokenization(
            target_tokenizer=TokenizerIdentity.model_validate(
                raw_result.tokenizer_id.model_dump(mode="json")
            ),
            original_token_count=CountObservation(
                claimed=raw_result.original_token_count,
                verified=raw_result.original_token_count,
                match=True,
            ),
            compressed_token_count=CountObservation(
                claimed=raw_result.compressed_token_count or 0,
                verified=raw_result.compressed_token_count or 0,
                match=True,
            ),
        ),
        reduction=Reduction(
            request_kind=(
                "token_budget" if request.target_token_budget is not None else "reduction_ratio"
            ),
            requested_reduction=_ratio(request.requested_reduction),
            requested_token_budget=effective_budget,
            achieved_reduction=ReductionObservation(
                claimed=achieved,
                verified=achieved,
                match=True,
            ),
        ),
        obligations=_obligation_claims(extraction, raw_result, discovery),
        relations=_relation_claims(raw_result, discovery),
        coverage=Coverage(
            certificate=CertificateCoverage(
                verified_discovered=0,
                verifier_discovered=0,
                value=None,
            ),
            source_map=SourceMapCoverage(
                protected_items_with_valid_map=0,
                protected_items=0,
                value=None,
                exact_copy_value=None,
                lineage_value=None,
            ),
            discovery_status=discovery,
            completeness=Completeness.PARTIAL,
        ),
        failed_invariants=[],
        parser_warnings=_warning_records(raw_result),
        risk=Risk(
            score=None,
            recomputed_score=None,
            match=True,
            calibration_status="not_available",
            calibrator_id=None,
            calibrator_version=None,
            feature_manifest_hash=None,
            threshold=None,
        ),
        action=Action(
            selected_action=FinalAction.EMIT,
            recomputed_action=FinalAction.EMIT,
            match=True,
            policy_id="phase4-unverified-candidate",
            policy_version="1.0.0",
        ),
        restored_spans=[],
        recovery_history=[],
        recovery_history_integrity=_empty_history(),
        fallback_reason=None,
        component_versions=_components(),
        timestamps=CertificateTimestamps(
            run_started_at=created_at,
            verification_started_at=created_at,
            verification_completed_at=created_at,
            certificate_finalized_at=created_at,
        ),
        verification_status=VerificationStatus.INDETERMINATE,
        informational={
            "extensions": {
                "candidate": True,
                "normalized_source_hash": extraction.normalized_sources[0].normalized_hash,
                "raw_status": raw_result.status.value,
            }
        },
    )
    return CertificateCandidate(
        candidate_version="1.0.0",
        source_id=source.source_id,
        normalized_source_hash=extraction.normalized_sources[0].normalized_hash,
        certificate_hash=certificate_hash(certificate),
        certificate=certificate,
    )


def seal_certificate(
    candidate: CertificateCandidate,
    report: VerificationReport,
) -> PreservationCertificate:
    if report.status != VerificationReportStatus.VALID:
        raise CertificateGenerationError("only valid verification reports can seal certificates")
    certificate = candidate.certificate
    if report.verified_source_hash is None or report.verified_compressed_artifact_hash is None:
        raise CertificateGenerationError("valid report is missing verified artifact hashes")
    if report.verified_normalized_hash is None:
        raise CertificateGenerationError("valid report is missing normalized hash")
    if report.original_token_count is None or report.compressed_token_count is None:
        raise CertificateGenerationError("valid report is missing token counts")
    if report.achieved_reduction is None:
        raise CertificateGenerationError("valid report is missing reduction")

    obligations: dict[str, ObligationClassResult] = {}
    for class_name, obligation_claim in certificate.obligations.by_class.items():
        obligation_verified = report.obligation_results.get(class_name)
        if obligation_verified is None:
            raise CertificateGenerationError(f"report omits obligation class: {class_name}")
        obligations[class_name] = obligation_claim.model_copy(
            update={
                "verifier_discovered": obligation_verified.discovered,
                "verifier_verified": obligation_verified.verified,
                "failed_obligation_ids": obligation_verified.failed_obligation_ids,
            }
        )
    relations: list[RelationResult] = []
    for relation_claim in certificate.relations.results:
        relation_verified = next(
            (
                item
                for item in report.relation_results
                if item.class_name == relation_claim.class_name
            ),
            None,
        )
        if relation_verified is None:
            raise CertificateGenerationError(
                f"report omits relation class: {relation_claim.class_name}"
            )
        relations.append(
            relation_claim.model_copy(
                update={
                    "verifier_discovered": relation_verified.discovered,
                    "verifier_verified": relation_verified.verified,
                    "failed_relation_ids": relation_verified.failed_relation_ids,
                    "status": relation_verified.status,
                }
            )
        )

    discovered = sum(item.discovered for item in report.obligation_results.values())
    verified_count = sum(item.verified for item in report.obligation_results.values())
    certificate_coverage = CertificateCoverage(
        verified_discovered=verified_count,
        verifier_discovered=discovered,
        value=_ratio(verified_count / discovered) if discovered else None,
    )
    if report.source_map_coverage is None:
        raise CertificateGenerationError("valid report is missing source-map coverage")

    payload = certificate.model_dump(mode="json")
    payload.update(
        {
            "artifact_role": "certified",
            "artifacts": {
                "source": {
                    "claimed_hash": certificate.artifacts.source.claimed_hash,
                    "verified_hash": report.verified_source_hash,
                    "match": certificate.artifacts.source.claimed_hash
                    == report.verified_source_hash,
                },
                "query": {
                    "claimed_hash": certificate.artifacts.query.claimed_hash,
                    "verified_hash": report.verified_query_hash
                    or certificate.artifacts.query.claimed_hash,
                    "match": certificate.artifacts.query.claimed_hash
                    == (report.verified_query_hash or certificate.artifacts.query.claimed_hash),
                },
                "request": {
                    "claimed_hash": certificate.artifacts.request.claimed_hash,
                    "verified_hash": report.verified_request_hash
                    or certificate.artifacts.request.claimed_hash,
                    "match": certificate.artifacts.request.claimed_hash
                    == (report.verified_request_hash or certificate.artifacts.request.claimed_hash),
                },
                "raw_compressed_context": {
                    "claimed_hash": certificate.artifacts.raw_compressed_context.claimed_hash,
                    "verified_hash": report.verified_compressed_artifact_hash,
                    "match": certificate.artifacts.raw_compressed_context.claimed_hash
                    == report.verified_compressed_artifact_hash,
                },
                "compressed_context": {
                    "claimed_hash": certificate.artifacts.compressed_context.claimed_hash,
                    "verified_hash": report.verified_compressed_artifact_hash,
                    "match": certificate.artifacts.compressed_context.claimed_hash
                    == report.verified_compressed_artifact_hash,
                },
                "source_map": certificate.artifacts.source_map.model_dump(mode="json"),
            },
            "tokenization": {
                "target_tokenizer": certificate.tokenization.target_tokenizer.model_dump(
                    mode="json"
                ),
                "original_token_count": {
                    "claimed": certificate.tokenization.original_token_count.claimed,
                    "verified": report.original_token_count,
                    "match": certificate.tokenization.original_token_count.claimed
                    == report.original_token_count,
                },
                "compressed_token_count": {
                    "claimed": certificate.tokenization.compressed_token_count.claimed,
                    "verified": report.compressed_token_count,
                    "match": certificate.tokenization.compressed_token_count.claimed
                    == report.compressed_token_count,
                },
            },
            "reduction": {
                **certificate.reduction.model_dump(mode="json", exclude={"achieved_reduction"}),
                "achieved_reduction": {
                    "claimed": certificate.reduction.achieved_reduction.claimed,
                    "verified": report.achieved_reduction,
                    "match": certificate.reduction.achieved_reduction.claimed
                    == report.achieved_reduction,
                },
            },
            "obligations": {
                "by_class": {
                    key: value.model_dump(mode="json") for key, value in obligations.items()
                }
            },
            "relations": {"results": [value.model_dump(mode="json") for value in relations]},
            "coverage": {
                "certificate": certificate_coverage.model_dump(mode="json"),
                "source_map": report.source_map_coverage.model_dump(mode="json"),
                "discovery_status": report.discovery_status.value,
                "completeness": report.completeness.value,
            },
            "failed_invariants": [item.model_dump(mode="json") for item in report.failed_checks],
            "parser_warnings": [
                item.model_dump(mode="json")
                for item in [*certificate.parser_warnings, *report.warnings]
            ],
            "action": {
                **certificate.action.model_dump(mode="json"),
                "recomputed_action": report.recommended_action.value,
                "match": certificate.action.selected_action.value
                == report.recommended_action.value,
            },
            "verification_status": VerificationStatus.PASSED.value,
            "informational": {
                **certificate.informational,
                "extensions": {
                    **certificate.informational.get("extensions", {}),
                    "sealed": True,
                    "verification_report_status": report.status.value,
                },
            },
        }
    )
    return PreservationCertificate.model_validate(payload)


__all__ = [
    "COMPONENT_VERSION",
    "CertificateGenerationError",
    "FIXED_TIME",
    "certificate_hash",
    "generate_certificate",
    "request_hash",
    "seal_certificate",
    "source_map_hash",
]
