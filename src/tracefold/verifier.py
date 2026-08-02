from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal, cast

from tracefold.extractors import extract_obligations
from tracefold.hashing import hash_canonical, sha256_domain
from tracefold.schemas.api import QueryEnvelope
from tracefold.schemas.certificate import SourceMapCoverage
from tracefold.schemas.common import (
    ArtifactStage,
    Completeness,
    DiscoveryStatus,
    FailedInvariant,
    FinalAction,
    HashDomain,
    ParserWarning,
)
from tracefold.schemas.common import (
    TokenizerIdentity as CertificateTokenizerIdentity,
)
from tracefold.schemas.phase2 import (
    OBLIGATION_CLASSES,
    RELATION_CLASSES,
    ContentType,
    ExtractionResult,
    Obligation,
    Relation,
    SourceArtifact,
    SourceMapValidation,
)
from tracefold.schemas.phase3 import CompressionStatus, RawCompressionRequest, RawCompressionResult
from tracefold.schemas.phase4 import (
    CertificateCandidate,
    VerificationReport,
    VerificationReportStatus,
    VerifiedObligationResult,
    VerifiedRelationResult,
)
from tracefold.schemas.source import SourceManifest, SourceManifestEntry
from tracefold.schemas.source_map import SourceMap, SourceSpan
from tracefold.serialization import canonical_json_bytes
from tracefold.source_maps import validate_source_map
from tracefold.sources import SourceCoordinateError, normalize_source
from tracefold.tokenizers import Tokenizer, TokenizerRegistry, UnknownTokenizerError
from tracefold.tokenizers.base import TokenizerIdentity as RegistryTokenizerIdentity

COMPONENT_VERSION = "tracefold.independent-verifier/0.1.0"
DEFAULT_VERIFICATION_RUN_ID = "123e4567-e89b-42d3-a456-426614174001"


@dataclass(frozen=True)
class VerificationEvidence:
    source: SourceArtifact
    raw_result: RawCompressionResult
    registry: TokenizerRegistry
    request: RawCompressionRequest | None = None
    extraction: ExtractionResult | None = None
    normalized_source: Any | None = None
    source_map: SourceMap | None = None
    original_source_map: SourceMap | None = None
    prior_raw_result: RawCompressionResult | None = None
    query: str | None = None
    compressed_text: str | None = None
    verification_run_id: str = DEFAULT_VERIFICATION_RUN_ID


class VerificationExecutionError(ValueError):
    """Verifier could not complete its independent checks."""


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _certificate_hash(candidate: CertificateCandidate) -> str:
    return sha256_domain(
        HashDomain.CERTIFICATE,
        canonical_json_bytes(candidate.certificate.model_dump(mode="json")),
    )


def _source_manifest(source: SourceArtifact) -> SourceManifest:
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


def _request_hash(
    request: RawCompressionRequest,
    source_manifest_hash: str,
    query_hash: str,
    effective_budget: int | None,
) -> str:
    return hash_canonical(
        HashDomain.COMPRESSION_REQUEST,
        _request_envelope(request, source_manifest_hash, query_hash, effective_budget),
    )


def _source_map_hash(source_map: SourceMap) -> str:
    return sha256_domain(
        HashDomain.SOURCE_MAP,
        canonical_json_bytes(source_map.model_dump(mode="json")),
    )


def _ratio(value: float) -> str:
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise VerificationExecutionError("reduction is outside [0, 1]")
    return f"{value:.6f}"


def _verify_hash_observation(
    observation: Any,
    actual: str,
    failures: list[FailedInvariant],
    *,
    label: str,
) -> None:
    if observation.claimed_hash != actual:
        _failure(
            failures,
            kind="hash",
            code="HASH_MISMATCH",
            message=f"{label} claimed hash does not match supplied evidence",
        )
    if observation.verified_hash != actual:
        _failure(
            failures,
            kind="hash",
            code=f"{label.upper()}_VERIFIED_HASH_MISMATCH",
            message=f"{label} verified hash is not independently recomputed",
        )
    if observation.match != (observation.claimed_hash == actual):
        _failure(
            failures,
            kind="hash",
            code=f"{label.upper()}_MATCH_FLAG_MISMATCH",
            message=f"{label} match flag disagrees with independently recomputed hash",
        )


def _verify_count_observation(
    observation: Any,
    actual: int,
    failures: list[FailedInvariant],
    *,
    label: str,
) -> None:
    if observation.claimed != actual:
        _failure(
            failures,
            kind="policy",
            code="TOKEN_COUNT_MISMATCH",
            message=f"{label} claimed token count is incorrect",
            recovery_hint="expand_budget",
        )
    if observation.verified != actual:
        _failure(
            failures,
            kind="policy",
            code=f"{label.upper()}_VERIFIED_COUNT_MISMATCH",
            message=f"{label} verified token count is not independently recomputed",
            recovery_hint="expand_budget",
        )
    if observation.match != (observation.claimed == actual):
        _failure(
            failures,
            kind="policy",
            code=f"{label.upper()}_MATCH_FLAG_MISMATCH",
            message=f"{label} match flag disagrees with independently counted tokens",
            recovery_hint="expand_budget",
        )


def _verify_reduction_observation(
    observation: Any,
    actual: str,
    failures: list[FailedInvariant],
) -> None:
    if observation.claimed != actual:
        _failure(
            failures,
            kind="policy",
            code="REDUCTION_MISMATCH",
            message="claimed achieved reduction is incorrect",
            recovery_hint="expand_budget",
        )
    if observation.verified != actual:
        _failure(
            failures,
            kind="policy",
            code="VERIFIED_REDUCTION_MISMATCH",
            message="verified achieved reduction is not independently recomputed",
            recovery_hint="expand_budget",
        )
    if observation.match != (observation.claimed == actual):
        _failure(
            failures,
            kind="policy",
            code="REDUCTION_MATCH_FLAG_MISMATCH",
            message="reduction match flag disagrees with independently computed reduction",
            recovery_hint="expand_budget",
        )


def _failure(
    failures: list[FailedInvariant],
    *,
    kind: str,
    code: str,
    message: str,
    severity: str = "hard",
    source_span_ids: Iterable[str] = (),
    candidate_span_ids: Iterable[str] = (),
    recovery_hint: str = "full_fallback",
) -> None:
    source_ids = sorted(set(source_span_ids))
    candidate_ids = sorted(set(candidate_span_ids))
    invariant_kind = cast(
        Literal["obligation", "relation", "hash", "source_map", "parser", "policy"],
        kind
        if kind in {"obligation", "relation", "hash", "source_map", "parser", "policy"}
        else "policy",
    )
    evidence = {"code": code, "source": source_ids, "candidate": candidate_ids}
    invariant_id = f"inv:{kind}:{_digest(evidence)[:16]}"
    failures.append(
        FailedInvariant(
            invariant_id=invariant_id,
            class_name=kind,
            kind=invariant_kind,
            severity=("soft" if severity == "soft" else "hard"),
            code=code,
            message=message,
            source_span_ids=source_ids,
            candidate_span_ids=candidate_ids,
            recovery_hint=recovery_hint,
        )
    )


def _warning(source: str, code: str, message: str, source_ids: Iterable[str] = ()) -> ParserWarning:
    return ParserWarning(
        source=cast(Literal["compressor", "verifier"], source),
        component_id=COMPONENT_VERSION,
        code=code,
        severity="warning",
        source_ids=sorted(set(source_ids)),
        message=message,
    )


def _hard_obligation(obligation: Obligation) -> bool:
    """Verifier-owned invariant applicability; intentionally not imported from compressor."""
    if obligation.class_name == "structured.json_schema_path":
        return False
    if obligation.class_name == "structured.anomalous_row":
        return True
    if obligation.class_name == "log.severity_change":
        return "from" in obligation.metadata and "to" in obligation.metadata
    if obligation.class_name == "temporal.timestamp" and obligation.metadata.get("event_id"):
        return False
    if obligation.class_name == "entity.named" and obligation.confidence.value == "inferred":
        return False
    if obligation.class_name == "identifier.generic" and obligation.metadata.get("event_id"):
        return (
            obligation.metadata.get("field") in {"error_code", "code"}
            or obligation.metadata.get("kind") == "exception"
        )
    if obligation.class_name == "code.definition":
        return obligation.metadata.get("kind") not in {"module", "use", "import_binding"}
    return True


def _span_range(span: SourceSpan) -> tuple[int, int]:
    return span.byte_start, span.byte_end


def _contains(container: SourceSpan, target: SourceSpan) -> bool:
    return (
        container.artifact_id == target.artifact_id
        and container.byte_start <= target.byte_start
        and target.byte_end <= container.byte_end
    )


def _overlaps(left: SourceSpan, right: SourceSpan) -> bool:
    return (
        left.artifact_id == right.artifact_id
        and left.byte_start < right.byte_end
        and right.byte_start < left.byte_end
    )


def _mapped_output_spans(
    target: SourceSpan,
    source_map: SourceMap,
    output_artifact_ids: set[str],
) -> list[tuple[Any, SourceSpan]]:
    spans = {span.span_id: span for span in source_map.spans}
    mapped: list[tuple[Any, SourceSpan]] = []
    for mapping in source_map.mappings:
        from_spans = [spans[item] for item in mapping.from_span_ids if item in spans]
        if not any(
            _overlaps(item, target) or item.span_id == target.span_id for item in from_spans
        ):
            continue
        for span_id in mapping.to_span_ids:
            if span_id in spans and spans[span_id].artifact_id in output_artifact_ids:
                mapped.append((mapping, spans[span_id]))
    return mapped


def _output_span_ids(
    target: SourceSpan,
    source_map: SourceMap,
    output_artifact_ids: set[str],
) -> set[str]:
    mapped = _mapped_output_spans(target, source_map, output_artifact_ids)
    return {span.span_id for _, span in mapped}


def _mapped_source_span_ids(
    target: SourceSpan,
    source_map: SourceMap,
) -> set[str]:
    spans = {span.span_id: span for span in source_map.spans}
    return {
        span.span_id
        for span in spans.values()
        if span.artifact_id == target.artifact_id
        and (_contains(span, target) or span.span_id == target.span_id)
    }


def _obligation_spans(obligation: Obligation, source_map: SourceMap) -> list[SourceSpan]:
    span_ids = [*obligation.source_span_ids, *obligation.owner_span_ids]
    by_id = {span.span_id: span for span in source_map.spans}
    return [by_id[item] for item in span_ids if item in by_id]


def _obligation_needle(obligation: Obligation, source: SourceArtifact, span: SourceSpan) -> bytes:
    if obligation.lexeme:
        return obligation.lexeme.encode("utf-8")
    raw = source.raw_bytes[span.byte_start : span.byte_end]
    if raw:
        return raw
    value = obligation.value
    if value is None:
        return b"null"
    if isinstance(value, bool):
        return str(value).lower().encode("ascii")
    if isinstance(value, (int, float, str)):
        return str(value).encode("utf-8")
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _obligation_needles(
    obligation: Obligation,
    source: SourceArtifact,
    span: SourceSpan,
) -> tuple[bytes, ...]:
    values: list[bytes] = []
    exact = _obligation_needle(obligation, source, span)
    if exact:
        values.append(exact)
    if isinstance(obligation.value, str):
        values.append(obligation.value.encode("utf-8"))
        if exact.startswith(b'"') and exact.endswith(b'"'):
            values.append(exact[1:-1])
    return tuple(dict.fromkeys(item for item in values if item))


def _covers_source_bytes(
    target: SourceSpan,
    mapped: list[tuple[Any, SourceSpan]],
    source_map: SourceMap,
    source: SourceArtifact,
) -> bool:
    spans = {span.span_id: span for span in source_map.spans}
    ranges: list[tuple[int, int]] = []
    for mapping, _ in mapped:
        for span_id in mapping.from_span_ids:
            span = spans.get(span_id)
            if span is None or span.artifact_id != target.artifact_id:
                continue
            ranges.append(
                (
                    max(target.byte_start, span.byte_start),
                    min(target.byte_end, span.byte_end),
                )
            )
    ranges.sort()
    cursor = target.byte_start
    for start, end in ranges:
        if start > cursor:
            gap = source.raw_bytes[cursor:start]
            if any(byte not in b" \t\r\n\v\f" for byte in gap):
                return False
        cursor = max(cursor, end)
    if cursor < target.byte_end:
        gap = source.raw_bytes[cursor : target.byte_end]
        if any(byte not in b" \t\r\n\v\f" for byte in gap):
            return False
    return True


def _obligation_represented(
    obligation: Obligation,
    source: SourceArtifact,
    source_map: SourceMap,
    output: bytes,
    output_artifact_ids: set[str],
) -> tuple[bool, set[str]]:
    mapped_ids: set[str] = set()
    mapped_spans: list[tuple[Any, SourceSpan]] = []
    for source_span in _obligation_spans(obligation, source_map):
        mapped = _mapped_output_spans(source_span, source_map, output_artifact_ids)
        mapped_spans.extend(mapped)
        mapped_ids.update(span.span_id for _, span in mapped)
    if not mapped_ids:
        return False, set()
    for source_span in _obligation_spans(obligation, source_map):
        needles = _obligation_needles(obligation, source, source_span)
        for mapping, output_span in mapped_spans:
            segment = output[output_span.byte_start : output_span.byte_end]
            if any(needle in segment for needle in needles):
                return True, mapped_ids
            metadata = obligation.metadata
            if metadata.get("kind") == "module" and _covers_source_bytes(
                source_span, mapped_spans, source_map, source
            ):
                return True, mapped_ids
            for label in (
                metadata.get("name"),
                metadata.get("qualified_name"),
                metadata.get("symbol_id"),
            ):
                if isinstance(label, str) and label and label.encode("utf-8") in segment:
                    return True, mapped_ids
            is_timestamp_aggregate = obligation.class_name == "temporal.timestamp" and (
                mapping.transform in {"aggregate", "synthesize_summary"}
            )
            if is_timestamp_aggregate:
                source_timestamp = str(obligation.value)
                represented_range = re.findall(
                    rb"\b(?:\d{4}-\d{2}-\d{2}T)?\d{2}:\d{2}:\d{2}"
                    rb"(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?\b",
                    segment,
                )
                if len(represented_range) >= 2:
                    start, end = (item.decode("ascii") for item in represented_range[:2])
                    source_value = source_timestamp[-9:]
                    if start[-9:] <= source_value <= end[-9:]:
                        return True, mapped_ids
            if (
                obligation.class_name == "identifier.generic"
                and isinstance(obligation.value, str)
                and obligation.value.startswith("log:")
                and mapping.transform in {"aggregate", "synthesize_summary"}
                and mapping.metadata.get("synthesized") is True
            ):
                source_text = source.raw_bytes[
                    source_span.byte_start : source_span.byte_end
                ].decode("utf-8", "strict")
                template = re.sub(
                    r"\b\d{4}-\d{2}-\d{2}[T ][0-9]{2}:[0-9]{2}:[0-9]{2}"
                    r"(?:\.\d+)?(?:Z|[+-][0-9]{2}:?[0-9]{2})?\b",
                    "<timestamp>",
                    source_text,
                )
                template = re.sub(
                    r"\b(?:trace|trace_id|request|request_id|event_id)=[^\s]+",
                    lambda match: match.group(0).split("=", 1)[0] + "=<id>",
                    template,
                )
                spans = {span.span_id: span for span in source_map.spans}
                event_count = sum(
                    spans[span_id].kind == "log_event"
                    for span_id in mapping.from_span_ids
                    if span_id in spans
                )
                is_log_marker = mapping.metadata.get("template") == template and (
                    b"[TraceFold logs x" in segment
                    or (
                        f"template={template}".encode() in segment
                        and f"count={event_count}".encode("ascii") in segment
                    )
                )
                if is_log_marker:
                    return True, mapped_ids
            if mapping.exactness in {"structurally_equivalent", "semantic_lineage_only"}:
                if obligation.class_name == "structured.json_schema_path":
                    path = None
                    if isinstance(obligation.value, dict):
                        path = obligation.value.get("path")
                    row_path = mapping.metadata.get("json_path")
                    if (
                        isinstance(path, str)
                        and isinstance(row_path, str)
                        and (path == row_path or path.startswith(f"{row_path}/"))
                        and segment.startswith(b"@row\t")
                    ):
                        return True, mapped_ids
                if obligation.class_name == "structured.anomalous_row":
                    if source_span.json_path and source_span.json_path.rsplit("/", 1)[-1].isdigit():
                        row_marker = b"@row\t"
                        if row_marker in segment:
                            return True, mapped_ids
                if isinstance(obligation.value, dict):
                    path = obligation.value.get("path")
                    if isinstance(path, str) and path in segment.decode("utf-8", "ignore"):
                        return True, mapped_ids
    return False, mapped_ids


def _relation_represented(
    relation: Relation,
    obligations: dict[str, Obligation],
    source: SourceArtifact,
    source_map: SourceMap,
    output: bytes,
    output_artifact_ids: set[str],
) -> tuple[bool, set[str]]:
    all_output_ids: set[str] = set()
    for obligation_id in relation.obligation_ids:
        obligation = obligations.get(obligation_id)
        if obligation is None:
            return False, all_output_ids
        represented, mapped_ids = _obligation_represented(
            obligation, source, source_map, output, output_artifact_ids
        )
        if not represented:
            return False, all_output_ids | mapped_ids
        all_output_ids.update(mapped_ids)

    span_by_id = {span.span_id: span for span in source_map.spans}
    evidence = [span_by_id[item] for item in relation.evidence_span_ids if item in span_by_id]
    if len(evidence) != len(relation.evidence_span_ids):
        return False, all_output_ids
    for span in evidence:
        all_output_ids.update(_output_span_ids(span, source_map, output_artifact_ids))
    if not all_output_ids:
        return False, set()

    # Common output lineage proves one association. Otherwise require every
    # evidence span in one output fragment in source order.
    output_sets = [_output_span_ids(span, source_map, output_artifact_ids) for span in evidence]
    if output_sets and set.intersection(*output_sets):
        return True, all_output_ids
    for span in evidence:
        mapped = _mapped_output_spans(span, source_map, output_artifact_ids)
        needle = source.raw_bytes[span.byte_start : span.byte_end]
        if not mapped or not any(
            needle in output[item.byte_start : item.byte_end] for _, item in mapped
        ):
            return False, all_output_ids
    return True, all_output_ids


def _output_artifacts(source_map: SourceMap) -> set[str]:
    return {
        artifact.artifact_id
        for artifact in source_map.artifacts
        if artifact.stage.value in {"raw_compressed", "final_compressed"}
    }


def _artifact_bytes(
    source: SourceArtifact,
    normalized: Any,
    compressed: bytes,
    source_map: SourceMap,
) -> dict[str, bytes]:
    values: dict[str, bytes] = {}
    for artifact in source_map.artifacts:
        if artifact.stage.value == "original":
            values[artifact.artifact_id] = source.raw_bytes
        elif artifact.stage.value == "normalized":
            values[artifact.artifact_id] = normalized.normalized_bytes
        elif artifact.stage.value in {"raw_compressed", "final_compressed", "restored"}:
            values[artifact.artifact_id] = compressed
    return values


def _compare_extraction(
    supplied: ExtractionResult | None,
    independent: ExtractionResult,
    failures: list[FailedInvariant],
) -> None:
    if supplied is None:
        return
    if supplied.model_dump(mode="json") != independent.model_dump(mode="json"):
        _failure(
            failures,
            kind="parser",
            code="EXTRACTION_DISAGREEMENT",
            message="supplied extraction fields disagree with independent extraction",
            recovery_hint="full_fallback",
        )


def _verify_source_span_lineage(
    extraction: ExtractionResult,
    source_map: SourceMap,
    failures: list[FailedInvariant],
) -> None:
    mapped = {span.span_id: span for span in source_map.spans}
    for expected in extraction.spans:
        actual = mapped.get(expected.span_id)
        if actual is None:
            _failure(
                failures,
                kind="source_map",
                code="MISSING_EXTRACTION_SPAN",
                message="source map omits an independently extracted span",
                source_span_ids=[expected.span_id],
                recovery_hint="full_fallback",
            )
            continue
        if actual.model_dump(mode="json") != expected.model_dump(mode="json"):
            _failure(
                failures,
                kind="source_map",
                code="SOURCE_SPAN_DISAGREEMENT",
                message="source-map source span differs from independent extraction",
                source_span_ids=[expected.span_id],
                recovery_hint="full_fallback",
            )


def _verify_synthesized_markers(
    source_map: SourceMap,
    output: bytes,
    failures: list[FailedInvariant],
) -> None:
    spans = {span.span_id: span for span in source_map.spans}
    synthesized_ids = {span.span_id for span in source_map.spans if span.kind == "synthesized"}
    mapped_ids: set[str] = set()
    allowed_prefixes = (
        b"[TraceFold repeated ",
        b"[TraceFold logs x",
        b"@schema=",
        b"@omitted_rows=",
        b"# TraceFold omitted ",
        b"    # TraceFold omitted ",
        b"[role=",
        b"[TRACEFOLD ",
        b"[SOURCE ",
        b"[INSTRUCTIONS]",
        b"[FACTS]",
        b"[RELATIONS]",
        b"[STRUCTURE]",
        b"[SELECTED EVIDENCE]",
        b"[PYTHON]",
        b"[OMISSIONS]",
        b"[/TRACEFOLD]",
        b"- ",
        b"@json ",
        b"@row ",
        b"@group ",
        b"def ",
        b"from ",
        b"import ",
        b"# ",
    )
    for mapping in source_map.mappings:
        for target_id in mapping.to_span_ids:
            if target_id not in synthesized_ids:
                continue
            mapped_ids.add(target_id)
            target = spans[target_id]
            segment = output[target.byte_start : target.byte_end]
            if mapping.metadata.get("synthesized") is not True:
                _failure(
                    failures,
                    kind="source_map",
                    code="SYNTHESIZED_MARKER_UNLABELLED",
                    message="synthesized output span lacks synthesized lineage label",
                    candidate_span_ids=[target_id],
                    recovery_hint="full_fallback",
                )
            if not mapping.from_span_ids or not segment.startswith(allowed_prefixes):
                _failure(
                    failures,
                    kind="source_map",
                    code="SYNTHESIZED_MARKER_INVALID",
                    message="synthesized marker is not an approved deterministic marker",
                    candidate_span_ids=[target_id],
                    recovery_hint="full_fallback",
                )
    for target_id in sorted(synthesized_ids - mapped_ids):
        _failure(
            failures,
            kind="source_map",
            code="SYNTHESIZED_MARKER_UNMAPPED",
            message="synthesized output span has no source lineage mapping",
            candidate_span_ids=[target_id],
            recovery_hint="full_fallback",
        )


def _map_validation(
    source: SourceArtifact,
    normalized: Any,
    output: bytes,
    source_map: SourceMap,
    manifest: SourceManifest,
    failures: list[FailedInvariant],
) -> SourceMapValidation:
    try:
        validation = validate_source_map(
            source_map,
            artifacts=_artifact_bytes(source, normalized, output, source_map),
            source_manifest=manifest,
        )
    except (ValueError, SourceCoordinateError) as exc:
        _failure(
            failures,
            kind="source_map",
            code="SOURCE_MAP_VALIDATION_FAILED",
            message=type(exc).__name__,
            recovery_hint="full_fallback",
        )
        return SourceMapValidation(valid=False, stale=True, errors=[type(exc).__name__])
    if not validation.valid or validation.stale:
        _failure(
            failures,
            kind="source_map",
            code="STALE_SOURCE_MAP" if validation.stale else "INVALID_SOURCE_MAP",
            message="source map is stale or invalid",
            recovery_hint="full_fallback",
        )
    return validation


def _verify_omissions(
    raw_result: RawCompressionResult,
    extraction: ExtractionResult,
    source_map: SourceMap,
    failures: list[FailedInvariant],
) -> None:
    spans = {span.span_id: span for span in source_map.spans}
    if len({item.original_span_id for item in raw_result.omitted_spans}) != len(
        raw_result.omitted_spans
    ):
        _failure(
            failures,
            kind="source_map",
            code="DUPLICATE_OMITTED_SPAN",
            message="omitted source spans must be unique",
            recovery_hint="full_fallback",
        )
    obligation_by_id = {item.obligation_id: item for item in extraction.obligations}
    hard_obligations = [item for item in extraction.obligations if _hard_obligation(item)]
    protected_ranges = [
        span
        for item in hard_obligations
        for span_id in [*item.source_span_ids, *item.owner_span_ids]
        if (span := spans.get(span_id)) is not None
    ]
    protected_ranges.extend(
        span
        for relation in extraction.relations
        for span_id in relation.evidence_span_ids
        if (span := spans.get(span_id)) is not None
    )
    delete_mappings = {
        span_id
        for mapping in source_map.mappings
        if mapping.transform == "delete"
        for span_id in mapping.from_span_ids
    }
    claimed_ids = {item.original_span_id for item in raw_result.omitted_spans}
    if claimed_ids != delete_mappings:
        _failure(
            failures,
            kind="source_map",
            code="OMISSION_MAP_DISAGREEMENT",
            message="omitted spans disagree with source-map delete mappings",
            recovery_hint="restore_spans",
        )
    for item in raw_result.omitted_spans:
        span = spans.get(item.original_span_id)
        if item.source_id != raw_result.source_id:
            _failure(
                failures,
                kind="source_map",
                code="OMISSION_SOURCE_ID_MISMATCH",
                message="omitted span source_id is not bound to the requested source",
                recovery_hint="full_fallback",
            )
        if span is None or span.artifact_id != f"artifact:original:{raw_result.source_id}":
            _failure(
                failures,
                kind="source_map",
                code="OMISSION_SOURCE_MISMATCH",
                message="omitted span is not bound to requested source",
                recovery_hint="full_fallback",
            )
            continue
        if item.normalized_span_id is not None:
            normalized = spans.get(item.normalized_span_id)
            if normalized is None or normalized.artifact_id != (
                f"artifact:normalized:{raw_result.source_id}"
            ):
                _failure(
                    failures,
                    kind="source_map",
                    code="OMISSION_NORMALIZED_SPAN_MISMATCH",
                    message="omitted normalized span is not bound to the source normalization",
                    source_span_ids=[item.original_span_id],
                    recovery_hint="full_fallback",
                )
        if not item.reversible_from_source_map:
            _failure(
                failures,
                kind="source_map",
                code="OMISSION_NOT_REVERSIBLE",
                message="omitted span is not marked reversible",
                source_span_ids=[item.original_span_id],
                recovery_hint="restore_spans",
            )
        if any(
            span.byte_start < protected.byte_end and protected.byte_start < span.byte_end
            for protected in protected_ranges
        ):
            _failure(
                failures,
                kind="obligation",
                code="MANDATORY_EVIDENCE_OMITTED",
                message="omitted span intersects mandatory evidence",
                source_span_ids=[item.original_span_id],
                recovery_hint="restore_spans",
            )
    # Ensure IDs claimed by omission metadata are not the only source of truth.
    for item in raw_result.omitted_spans:
        for obligation_id in item.obligation_ids:
            if obligation_id not in obligation_by_id:
                _failure(
                    failures,
                    kind="obligation",
                    code="UNKNOWN_OMITTED_OBLIGATION",
                    message="omission references unknown obligation",
                    source_span_ids=[item.original_span_id],
                    recovery_hint="full_fallback",
                )


def _coverage(
    extraction: ExtractionResult,
    source: SourceArtifact,
    source_map: SourceMap,
    output: bytes,
) -> tuple[dict[str, VerifiedObligationResult], list[VerifiedRelationResult], set[str], set[str]]:
    output_artifact_ids = _output_artifacts(source_map)
    obligations = {item.obligation_id: item for item in extraction.obligations}
    results: dict[str, VerifiedObligationResult] = {}
    represented_ids: set[str] = set()
    hard_ids = {item.obligation_id for item in extraction.obligations if _hard_obligation(item)}
    discovery = DiscoveryStatus(extraction.coverage.value)
    for class_name in OBLIGATION_CLASSES:
        items = [item for item in extraction.obligations if item.class_name == class_name]
        class_discovery = _class_discovery(
            discovery, (item.discovery_status.value for item in items)
        )
        verified_items: list[Obligation] = []
        for item in items:
            represented, _ = _obligation_represented(
                item, source, source_map, output, output_artifact_ids
            )
            if represented:
                verified_items.append(item)
                represented_ids.add(item.obligation_id)
        results[class_name] = VerifiedObligationResult(
            applicability=(
                "applicable"
                if items
                else "not_applicable"
                if class_discovery == DiscoveryStatus.KNOWN
                else "unknown"
            ),
            discovery_status=class_discovery,
            discovered=len(items),
            verified=len(verified_items),
            failed_obligation_ids=sorted(
                item.obligation_id for item in items if item.obligation_id not in represented_ids
            ),
        )
    relations: list[VerifiedRelationResult] = []
    relation_ids: set[str] = set()
    for class_name in RELATION_CLASSES:
        class_relations = [
            item for item in extraction.relations if item.relation_type == class_name
        ]
        class_discovery = _class_discovery(
            discovery, (item.discovery_status.value for item in class_relations)
        )
        verified = 0
        failed: list[str] = []
        for relation in class_relations:
            valid, _ = _relation_represented(
                relation, obligations, source, source_map, output, output_artifact_ids
            )
            if valid:
                verified += 1
                relation_ids.add(relation.relation_id)
            else:
                failed.append(relation.relation_id)
        relations.append(
            VerifiedRelationResult(
                class_name=class_name,
                discovery_status=discovery,
                discovered=len(class_relations),
                verified=verified,
                failed_relation_ids=sorted(failed),
                status=(
                    "not_applicable"
                    if not class_relations and class_discovery == DiscoveryStatus.KNOWN
                    else "passed"
                    if not failed and class_discovery == DiscoveryStatus.KNOWN
                    else "indeterminate"
                    if not failed
                    else "failed"
                ),
            )
        )
    return results, relations, hard_ids & represented_ids, relation_ids


def _verify_claimed_coverage(
    certificate: Any,
    raw_result: RawCompressionResult,
    obligation_results: dict[str, VerifiedObligationResult],
    relation_results: list[VerifiedRelationResult],
    failures: list[FailedInvariant],
) -> None:
    known_obligations = set(OBLIGATION_CLASSES)
    if set(raw_result.obligation_coverage) - known_obligations:
        _failure(
            failures,
            kind="obligation",
            code="RAW_OBLIGATION_CLASS_SET_MISMATCH",
            message="raw result contains an undocumented obligation class",
        )
    if set(certificate.obligations.by_class) != known_obligations:
        _failure(
            failures,
            kind="obligation",
            code="OBLIGATION_CLASS_SET_MISMATCH",
            message="certificate obligation classes do not match the frozen class set",
        )
    for class_name in OBLIGATION_CLASSES:
        obligation_claim = certificate.obligations.by_class.get(class_name)
        obligation_actual = obligation_results[class_name]
        raw = raw_result.obligation_coverage.get(class_name)
        raw_discovered = raw.discovered if raw is not None else 0
        raw_represented = raw.represented if raw is not None else 0
        if obligation_claim is None:
            continue
        if (
            obligation_claim.compressor_discovered != raw_discovered
            or obligation_claim.compressor_claimed_preserved != raw_represented
        ):
            _failure(
                failures,
                kind="obligation",
                code="COMPRESSOR_COVERAGE_CLAIM_MISMATCH",
                message="certificate compressor obligation claim disagrees with raw evidence",
            )
        if (
            certificate.verification_status == "indeterminate"
            and obligation_claim.failed_obligation_ids
        ):
            _failure(
                failures,
                kind="obligation",
                code="UNTRUSTED_FAILED_OBLIGATION_IDS",
                message="unsealed candidates cannot assert verifier failed-obligation IDs",
            )
        if (
            raw_discovered != obligation_actual.discovered
            or raw_represented > obligation_actual.verified
        ):
            _failure(
                failures,
                kind="obligation",
                code="RAW_COVERAGE_MISMATCH",
                message="raw obligation coverage disagrees with independent extraction",
            )
        if certificate.verification_status == "passed" and (
            obligation_claim.verifier_discovered != obligation_actual.discovered
            or obligation_claim.verifier_verified != obligation_actual.verified
            or sorted(obligation_claim.failed_obligation_ids)
            != sorted(obligation_actual.failed_obligation_ids)
        ):
            _failure(
                failures,
                kind="obligation",
                code="SEALED_COVERAGE_MISMATCH",
                message="sealed obligation coverage disagrees with independent verification",
            )

    known_relations = set(RELATION_CLASSES)
    if set(raw_result.relation_coverage) - known_relations:
        _failure(
            failures,
            kind="relation",
            code="RAW_RELATION_CLASS_SET_MISMATCH",
            message="raw result contains an undocumented relation class",
        )
    relation_claims = {item.class_name: item for item in certificate.relations.results}
    if set(relation_claims) != known_relations or len(relation_claims) != len(
        certificate.relations.results
    ):
        _failure(
            failures,
            kind="relation",
            code="RELATION_CLASS_SET_MISMATCH",
            message="certificate relation classes do not match the frozen class set",
        )
    actual_by_class = {item.class_name: item for item in relation_results}
    for class_name in RELATION_CLASSES:
        relation_claim = relation_claims.get(class_name)
        relation_actual = actual_by_class[class_name]
        raw = raw_result.relation_coverage.get(class_name)
        raw_discovered = raw.discovered if raw is not None else 0
        raw_represented = raw.represented if raw is not None else 0
        if relation_claim is None:
            continue
        if (
            relation_claim.compressor_discovered != raw_discovered
            or relation_claim.compressor_claimed_preserved != raw_represented
        ):
            _failure(
                failures,
                kind="relation",
                code="COMPRESSOR_RELATION_CLAIM_MISMATCH",
                message="certificate compressor relation claim disagrees with raw evidence",
            )
        if (
            certificate.verification_status == "indeterminate"
            and relation_claim.failed_relation_ids
        ):
            _failure(
                failures,
                kind="relation",
                code="UNTRUSTED_FAILED_RELATION_IDS",
                message="unsealed candidates cannot assert verifier failed-relation IDs",
            )
        if (
            raw_discovered != relation_actual.discovered
            or raw_represented > relation_actual.verified
        ):
            _failure(
                failures,
                kind="relation",
                code="RAW_RELATION_COVERAGE_MISMATCH",
                message="raw relation coverage disagrees with independent extraction",
            )
        if certificate.verification_status == "passed" and (
            relation_claim.verifier_discovered != relation_actual.discovered
            or relation_claim.verifier_verified != relation_actual.verified
            or sorted(relation_claim.failed_relation_ids)
            != sorted(relation_actual.failed_relation_ids)
            or relation_claim.status != relation_actual.status
        ):
            _failure(
                failures,
                kind="relation",
                code="SEALED_RELATION_COVERAGE_MISMATCH",
                message="sealed relation coverage disagrees with independent verification",
            )


def _verify_recovery_state(certificate: Any, failures: list[FailedInvariant]) -> None:
    history = [item.model_dump(mode="json") for item in certificate.recovery_history]
    expected = hash_canonical(HashDomain.RECOVERY_HISTORY, history)
    integrity = certificate.recovery_history_integrity
    _verify_hash_observation(integrity, expected, failures, label="recovery_history")
    if integrity.record_count != len(certificate.recovery_history):
        _failure(
            failures,
            kind="policy",
            code="RECOVERY_HISTORY_COUNT_MISMATCH",
            message="recovery history record count is incorrect",
        )
    expected_head = None
    if certificate.recovery_history:
        expected_head = certificate.recovery_history[-1].event_hash
    if integrity.head_event_hash != expected_head:
        _failure(
            failures,
            kind="policy",
            code="RECOVERY_HISTORY_HEAD_MISMATCH",
            message="recovery history head is incorrect",
        )
    if certificate.artifact_role == "end_to_end":
        previous: str | None = None
        for index, record in enumerate(certificate.recovery_history):
            if record.sequence != index:
                _failure(
                    failures,
                    kind="policy",
                    code="RECOVERY_SEQUENCE_MISMATCH",
                    message="recovery history sequence is not contiguous",
                    recovery_hint="full_fallback",
                )
            if record.previous_event_hash != previous:
                _failure(
                    failures,
                    kind="policy",
                    code="RECOVERY_PARENT_MISMATCH",
                    message="recovery history parent hash is incorrect",
                    recovery_hint="full_fallback",
                )
            payload = record.model_dump(mode="json", exclude={"event_hash"})
            expected_event = sha256_domain(
                HashDomain.RECOVERY_EVENT,
                canonical_json_bytes(payload),
            )
            if record.event_hash != expected_event:
                _failure(
                    failures,
                    kind="hash",
                    code="RECOVERY_EVENT_HASH_MISMATCH",
                    message="recovery event hash is not independently recomputed",
                    recovery_hint="full_fallback",
                )
            previous = record.event_hash
        if (
            certificate.action.selected_action == FinalAction.RESTORE_SPANS
            and not certificate.restored_spans
        ):
            _failure(
                failures,
                kind="policy",
                code="RESTORATION_RECORD_MISSING",
                message="restore_spans action requires restored span records",
                recovery_hint="full_fallback",
            )
        if (
            certificate.action.selected_action == FinalAction.FULL_FALLBACK
            and certificate.fallback_reason is None
        ):
            _failure(
                failures,
                kind="policy",
                code="FALLBACK_REASON_MISSING",
                message="full_fallback action requires fallback reason",
                recovery_hint="full_fallback",
            )
        return
    if certificate.recovery_history:
        _failure(
            failures,
            kind="policy",
            code="RECOVERY_HISTORY_NOT_EMPTY",
            message="Phase 4 certificates cannot execute or carry recovery history",
        )
    if certificate.restored_spans:
        _failure(
            failures,
            kind="policy",
            code="RESTORED_SPANS_NOT_ALLOWED",
            message="Phase 4 certificates cannot carry restored spans",
        )
    if certificate.fallback_reason is not None:
        _failure(
            failures,
            kind="policy",
            code="FALLBACK_NOT_EXECUTED",
            message="Phase 4 certificates cannot execute fallback",
        )


def _verify_certificate_shape(certificate: Any, failures: list[FailedInvariant]) -> None:
    if certificate.artifact_role not in {"raw", "certified", "end_to_end"}:
        _failure(
            failures,
            kind="policy",
            code="UNSUPPORTED_ARTIFACT_ROLE",
            message="certificate artifact role is unsupported",
        )
    if certificate.verification_status not in {"indeterminate", "passed"}:
        _failure(
            failures,
            kind="policy",
            code="UNSUPPORTED_VERIFICATION_STATUS",
            message="certificate status is not a Phase 4 candidate or sealed status",
        )
    if certificate.verification_status == "indeterminate" and certificate.artifact_role not in {
        "raw"
    }:
        _failure(
            failures,
            kind="policy",
            code="CANDIDATE_ROLE_STATUS_MISMATCH",
            message="indeterminate candidates must carry raw artifact role",
        )
    if certificate.verification_status == "passed" and certificate.artifact_role not in {
        "certified",
        "end_to_end",
    }:
        _failure(
            failures,
            kind="policy",
            code="SEALED_ROLE_STATUS_MISMATCH",
            message="passed certificates must carry certified artifact role",
        )
    if certificate.artifact_role == "end_to_end":
        if certificate.risk.match != (certificate.risk.score == certificate.risk.recomputed_score):
            _failure(
                failures,
                kind="policy",
                code="RISK_MATCH_FLAG_MISMATCH",
                message="end-to-end risk match flag is inconsistent",
            )
        return
    if certificate.risk.calibration_status != "not_available":
        _failure(
            failures,
            kind="policy",
            code="CALIBRATION_NOT_AVAILABLE_CLAIM_MISMATCH",
            message="Phase 4 cannot claim calibrated risk",
        )
    if any(
        value is not None
        for value in (
            certificate.risk.score,
            certificate.risk.recomputed_score,
            certificate.risk.calibrator_id,
            certificate.risk.calibrator_version,
            certificate.risk.feature_manifest_hash,
            certificate.risk.threshold,
        )
    ):
        _failure(
            failures,
            kind="policy",
            code="RISK_DATA_NOT_ALLOWED",
            message="Phase 4 certificates cannot carry risk values",
        )


def _verify_restored_spans(
    certificate: Any,
    source_map: SourceMap,
    failures: list[FailedInvariant],
) -> None:
    if certificate.artifact_role != "end_to_end":
        return
    spans = {item.span_id: item for item in source_map.spans}
    output_artifacts = {
        item.artifact_id
        for item in source_map.artifacts
        if item.stage in {ArtifactStage.RAW_COMPRESSED, ArtifactStage.FINAL_COMPRESSED}
    }
    for restored in certificate.restored_spans:
        original = spans.get(restored.source_span_id)
        output = spans.get(restored.compressed_span_id)
        if original is None or output is None or output.artifact_id not in output_artifacts:
            _failure(
                failures,
                kind="source_map",
                code="RESTORED_SPAN_NOT_MAPPED",
                message="restored span does not resolve in supplied source map",
                recovery_hint="full_fallback",
            )
            continue
        if (
            original.span_hash != restored.original_hash
            or output.span_hash != restored.inserted_hash
        ):
            _failure(
                failures,
                kind="hash",
                code="RESTORED_SPAN_HASH_MISMATCH",
                message="restored span hash is not bound to source-map spans",
                recovery_hint="full_fallback",
            )
        if not any(
            restored.source_span_id in mapping.from_span_ids
            and restored.compressed_span_id in mapping.to_span_ids
            and mapping.exactness == "byte_exact"
            for mapping in source_map.mappings
        ):
            _failure(
                failures,
                kind="source_map",
                code="RESTORED_SPAN_NOT_EXACT",
                message="restored span lacks byte-exact source-map lineage",
                recovery_hint="full_fallback",
            )


def _source_map_coverage(
    source_map: SourceMap,
    protected_count: int,
    represented_count: int,
) -> SourceMapCoverage:
    value = None if protected_count == 0 else _ratio(represented_count / protected_count)
    return SourceMapCoverage(
        protected_items_with_valid_map=represented_count,
        protected_items=protected_count,
        value=value,
        exact_copy_value=source_map.coverage.exact_copy_coverage,
        lineage_value=source_map.coverage.lineage_coverage,
    )


def _class_discovery(global_status: DiscoveryStatus, values: Iterable[str]) -> DiscoveryStatus:
    statuses = {DiscoveryStatus(value) for value in values}
    if global_status == DiscoveryStatus.UNKNOWN or DiscoveryStatus.UNKNOWN in statuses:
        return DiscoveryStatus.UNKNOWN
    if global_status == DiscoveryStatus.PARTIAL or DiscoveryStatus.PARTIAL in statuses:
        return DiscoveryStatus.PARTIAL
    return DiscoveryStatus.KNOWN


def _overall_discovery(
    extraction: ExtractionResult,
    obligation_results: dict[str, VerifiedObligationResult],
    relation_results: list[VerifiedRelationResult],
) -> DiscoveryStatus:
    statuses = [
        DiscoveryStatus(extraction.coverage.value),
        *(item.discovery_status for item in obligation_results.values()),
        *(item.discovery_status for item in relation_results),
    ]
    if DiscoveryStatus.UNKNOWN in statuses:
        return DiscoveryStatus.UNKNOWN
    if DiscoveryStatus.PARTIAL in statuses:
        return DiscoveryStatus.PARTIAL
    return DiscoveryStatus.KNOWN


def _recommended_action(
    raw_result: RawCompressionResult,
    failures: list[FailedInvariant],
    discovery: DiscoveryStatus,
) -> FinalAction:
    codes = {item.code for item in failures}
    if raw_result.status == CompressionStatus.INCOMPRESSIBLE:
        return FinalAction.EXPAND_BUDGET
    if {
        "BUDGET_MISMATCH",
        "CERTIFICATE_BUDGET_MISMATCH",
        "TOKEN_BUDGET_EXCEEDED",
    } & codes:
        return FinalAction.EXPAND_BUDGET
    if {
        "MANDATORY_EVIDENCE_OMITTED",
        "OBLIGATION_NOT_REPRESENTED",
        "RELATION_NOT_REPRESENTED",
    } & codes:
        return FinalAction.RESTORE_SPANS
    if (
        discovery == DiscoveryStatus.UNKNOWN
        or {
            "STALE_SOURCE_MAP",
            "INVALID_SOURCE_MAP",
            "HASH_MISMATCH",
            "UNKNOWN_TOKENIZER",
            "EXTRACTION_FAILURE",
        }
        & codes
    ):
        return FinalAction.FULL_FALLBACK
    return FinalAction.FULL_FALLBACK if failures else FinalAction.EMIT


def _end_to_end_action_valid(
    certificate: Any,
    recommended: FinalAction,
) -> bool:
    if certificate.action.recomputed_action != certificate.action.selected_action:
        return False
    if not certificate.action.match:
        return False
    history = certificate.recovery_history
    if not history:
        return (
            certificate.action.selected_action == FinalAction.EMIT
            and recommended == FinalAction.EMIT
        )
    last_action = history[-1].action_taken
    selected = certificate.action.selected_action
    if selected == FinalAction.FULL_FALLBACK:
        return last_action == FinalAction.FULL_FALLBACK and certificate.fallback_reason is not None
    if selected == FinalAction.RESTORE_SPANS:
        return (
            any(item.action_taken == FinalAction.RESTORE_SPANS for item in history)
            and last_action == FinalAction.EMIT
            and bool(certificate.restored_spans)
            and recommended == FinalAction.EMIT
        )
    if selected == FinalAction.EXPAND_BUDGET:
        return (
            any(item.action_taken == FinalAction.EXPAND_BUDGET for item in history)
            and last_action == FinalAction.EMIT
            and recommended == FinalAction.EMIT
        )
    return bool(selected == FinalAction.EMIT and last_action == FinalAction.EMIT)


def verify_certificate(
    candidate: CertificateCandidate,
    evidence: VerificationEvidence,
) -> VerificationReport:
    failures: list[FailedInvariant] = []
    warnings: list[ParserWarning] = []
    source = evidence.source
    raw_result = evidence.raw_result
    certificate = candidate.certificate
    normalized = None
    independent: ExtractionResult | None = None
    source_map = evidence.source_map if evidence.source_map is not None else raw_result.source_map
    output_text = (
        evidence.compressed_text
        if evidence.compressed_text is not None
        else raw_result.compressed_text
    )
    output = output_text.encode("utf-8") if output_text is not None else None
    verified_source_hash: str | None = None
    verified_normalized_hash: str | None = None
    verified_query_hash: str | None = None
    verified_request_hash: str | None = None
    verified_compressed_hash: str | None = None
    tokenizer: Tokenizer | None = None
    original_count: int | None = None
    compressed_count: int | None = None
    achieved: str | None = None
    obligation_results: dict[str, VerifiedObligationResult] = {}
    relation_results: list[VerifiedRelationResult] = []
    source_map_coverage: SourceMapCoverage | None = None
    internal_failure = False
    unverifiable = False

    try:
        _verify_certificate_shape(certificate, failures)
        _verify_recovery_state(certificate, failures)
        if raw_result.status == CompressionStatus.FAILED:
            _failure(
                failures,
                kind="parser",
                code="RAW_RESULT_FAILED",
                message="failed raw compression results cannot carry a preservation certificate",
                recovery_hint="full_fallback",
            )
        elif raw_result.status == CompressionStatus.INCOMPRESSIBLE:
            unverifiable = True
        if candidate.source_id != source.source_id or certificate.run_id != raw_result.run_id:
            _failure(
                failures,
                kind="hash",
                code="SOURCE_OR_RUN_MISMATCH",
                message="candidate is not bound to supplied source and run",
            )
        if raw_result.source_id != source.source_id:
            _failure(
                failures,
                kind="hash",
                code="RAW_SOURCE_ID_MISMATCH",
                message="raw result is not bound to supplied source",
            )
        if certificate.attempt_id != raw_result.attempt_id:
            _failure(
                failures,
                kind="hash",
                code="ATTEMPT_ID_MISMATCH",
                message="certificate is not bound to the raw compression attempt",
            )
        if candidate.certificate_hash != _certificate_hash(candidate):
            _failure(
                failures,
                kind="hash",
                code="CERTIFICATE_HASH_MISMATCH",
                message="certificate candidate hash does not match canonical certificate bytes",
            )

        manifest = _source_manifest(source)
        verified_source_hash = hash_canonical(HashDomain.SOURCE_MANIFEST, manifest)
        if certificate.artifacts.source.claimed_hash != verified_source_hash:
            _failure(
                failures,
                kind="hash",
                code="HASH_MISMATCH",
                message="source manifest hash claim does not match supplied source",
            )
        _verify_hash_observation(
            certificate.artifacts.source,
            verified_source_hash,
            failures,
            label="source",
        )
        if raw_result.source_hash != sha256_domain(HashDomain.SOURCE_ARTIFACT, source.raw_bytes):
            _failure(
                failures,
                kind="hash",
                code="RAW_SOURCE_HASH_MISMATCH",
                message="raw result source hash does not match supplied source bytes",
            )

        normalized = normalize_source(source)
        verified_normalized_hash = normalized.normalized_hash
        if candidate.normalized_source_hash != verified_normalized_hash:
            _failure(
                failures,
                kind="hash",
                code="NORMALIZED_HASH_MISMATCH",
                message="candidate normalized hash does not match normalized source",
            )
        if raw_result.normalized_source_hash != verified_normalized_hash:
            _failure(
                failures,
                kind="hash",
                code="RAW_NORMALIZED_HASH_MISMATCH",
                message="raw result normalized hash does not match normalized source",
            )
        if evidence.normalized_source is not None:
            if evidence.normalized_source.model_dump(mode="json") != normalized.model_dump(
                mode="json"
            ):
                _failure(
                    failures,
                    kind="source_map",
                    code="NORMALIZATION_DISAGREEMENT",
                    message="supplied normalization differs from independent normalization",
                )

        verified_query_hash = hash_canonical(HashDomain.QUERY, QueryEnvelope(query=evidence.query))
        if certificate.artifacts.query.claimed_hash != verified_query_hash:
            _failure(
                failures,
                kind="hash",
                code="QUERY_HASH_MISMATCH",
                message="query hash does not match supplied query envelope",
            )
        _verify_hash_observation(
            certificate.artifacts.query,
            verified_query_hash,
            failures,
            label="query",
        )

        if evidence.request is None:
            unverifiable = True
        else:
            verified_request_hash = _request_hash(
                evidence.request,
                verified_source_hash,
                verified_query_hash,
                raw_result.requested_token_budget,
            )
            if certificate.artifacts.request.claimed_hash != verified_request_hash:
                _failure(
                    failures,
                    kind="hash",
                    code="REQUEST_HASH_MISMATCH",
                    message="request hash does not match supplied request",
                )
            _verify_hash_observation(
                certificate.artifacts.request,
                verified_request_hash,
                failures,
                label="request",
            )
            if evidence.request.source_id != source.source_id:
                _failure(
                    failures,
                    kind="hash",
                    code="REQUEST_SOURCE_MISMATCH",
                    message="request is bound to another source",
                )
            if evidence.request.run_id != raw_result.run_id:
                _failure(
                    failures,
                    kind="hash",
                    code="REQUEST_RUN_MISMATCH",
                    message="request is bound to another run",
                )
            if evidence.request.tokenizer_id != raw_result.tokenizer_id:
                _failure(
                    failures,
                    kind="policy",
                    code="REQUEST_TOKENIZER_MISMATCH",
                    message="request tokenizer differs from raw result tokenizer",
                    recovery_hint="full_fallback",
                )
            if raw_result.requested_reduction != evidence.request.requested_reduction:
                _failure(
                    failures,
                    kind="policy",
                    code="RAW_REQUEST_REDUCTION_MISMATCH",
                    message="raw result requested reduction differs from request",
                    recovery_hint="expand_budget",
                )
            if (
                evidence.request.compiler_strategy.value != "auto"
                and raw_result.compiler_strategy != evidence.request.compiler_strategy
            ):
                _failure(
                    failures,
                    kind="policy",
                    code="RAW_COMPILER_STRATEGY_MISMATCH",
                    message="raw result compiler strategy differs from request",
                    recovery_hint="full_fallback",
                )
            if evidence.request.source_kind.value != source.kind:
                _failure(
                    failures,
                    kind="parser",
                    code="REQUEST_SOURCE_KIND_MISMATCH",
                    message="request source kind differs from supplied source metadata",
                    recovery_hint="full_fallback",
                )
            expected_request_kind = (
                "token_budget"
                if evidence.request.target_token_budget is not None
                else "reduction_ratio"
            )
            if certificate.reduction.request_kind != expected_request_kind:
                _failure(
                    failures,
                    kind="policy",
                    code="REQUEST_KIND_MISMATCH",
                    message="certificate reduction request kind disagrees with request",
                    recovery_hint="expand_budget",
                )
            expected_reduction = (
                _ratio(evidence.request.requested_reduction)
                if evidence.request.requested_reduction is not None
                else None
            )
            if certificate.reduction.requested_reduction != expected_reduction:
                _failure(
                    failures,
                    kind="policy",
                    code="REQUEST_REDUCTION_MISMATCH",
                    message="certificate requested reduction disagrees with request",
                    recovery_hint="expand_budget",
                )
        if certificate.reduction.requested_token_budget != raw_result.requested_token_budget:
            _failure(
                failures,
                kind="policy",
                code="CERTIFICATE_BUDGET_MISMATCH",
                message="certificate requested token budget disagrees with raw result",
                recovery_hint="expand_budget",
            )

        if evidence.source_map is not None and raw_result.source_map is not None:
            if evidence.source_map.model_dump(mode="json") != raw_result.source_map.model_dump(
                mode="json"
            ):
                _failure(
                    failures,
                    kind="source_map",
                    code="SOURCE_MAP_DISAGREEMENT",
                    message="explicit compressed source map disagrees with raw result map",
                    recovery_hint="full_fallback",
                )

        if source_map is None or output is None:
            unverifiable = True
        else:
            actual_map_hash = _source_map_hash(source_map)
            if certificate.artifacts.source_map.claimed_hash != actual_map_hash:
                _failure(
                    failures,
                    kind="hash",
                    code="SOURCE_MAP_HASH_MISMATCH",
                    message="source-map hash does not match supplied map",
                )
            if source_map.source_manifest_hash != verified_source_hash:
                _failure(
                    failures,
                    kind="source_map",
                    code="SOURCE_MAP_SOURCE_MISMATCH",
                    message="source map is bound to another source manifest",
                )
            if source_map.query_hash != verified_query_hash:
                _failure(
                    failures,
                    kind="source_map",
                    code="SOURCE_MAP_QUERY_MISMATCH",
                    message="source map is bound to another query",
                )
            if (
                source_map.run_id != certificate.run_id
                or source_map.attempt_id != raw_result.attempt_id
            ):
                _failure(
                    failures,
                    kind="source_map",
                    code="SOURCE_MAP_ATTEMPT_MISMATCH",
                    message="source map is bound to another attempt",
                )
            map_validation = _map_validation(
                source, normalized, output, source_map, manifest, failures
            )
            _verify_synthesized_markers(source_map, output, failures)
            _verify_restored_spans(certificate, source_map, failures)
            _verify_hash_observation(
                certificate.artifacts.source_map,
                actual_map_hash,
                failures,
                label="source_map",
            )
            if certificate.artifacts.source_map.stale != map_validation.stale:
                _failure(
                    failures,
                    kind="source_map",
                    code="SOURCE_MAP_STALE_FLAG_MISMATCH",
                    message="source-map stale flag disagrees with independent validation",
                    recovery_hint="full_fallback",
                )
            verified_compressed_hash = sha256_domain(HashDomain.CONTEXT_ARTIFACT, output)
            if raw_result.compressed_hash != verified_compressed_hash:
                _failure(
                    failures,
                    kind="hash",
                    code="COMPRESSED_HASH_MISMATCH",
                    message="raw compressed hash does not match compressed bytes",
                )
            if certificate.artifacts.compressed_context.claimed_hash != verified_compressed_hash:
                _failure(
                    failures,
                    kind="hash",
                    code="HASH_MISMATCH",
                    message="certificate compressed hash does not match compressed bytes",
                )
            raw_context_hash = verified_compressed_hash
            if (
                certificate.artifact_role == "end_to_end"
                and evidence.prior_raw_result is not None
                and evidence.prior_raw_result.compressed_hash is not None
            ):
                raw_context_hash = evidence.prior_raw_result.compressed_hash
            if certificate.artifacts.raw_compressed_context.claimed_hash != raw_context_hash:
                _failure(
                    failures,
                    kind="hash",
                    code="RAW_CONTEXT_HASH_MISMATCH",
                    message="certificate raw context hash does not match compressed bytes",
                )
            _verify_hash_observation(
                certificate.artifacts.compressed_context,
                verified_compressed_hash,
                failures,
                label="compressed_context",
            )
            _verify_hash_observation(
                certificate.artifacts.raw_compressed_context,
                raw_context_hash,
                failures,
                label="raw_compressed_context",
            )

        try:
            declared_tokenizer = certificate.tokenization.target_tokenizer.model_dump(mode="json")
            raw_tokenizer = raw_result.tokenizer_id.model_dump(mode="json")
            if declared_tokenizer != raw_tokenizer:
                _failure(
                    failures,
                    kind="policy",
                    code="CERTIFICATE_TOKENIZER_MISMATCH",
                    message="certificate tokenizer differs from raw result tokenizer",
                    recovery_hint="full_fallback",
                )
            tokenizer = evidence.registry.resolve(
                RegistryTokenizerIdentity.model_validate(
                    certificate.tokenization.target_tokenizer.model_dump(mode="json")
                )
            )
        except UnknownTokenizerError:
            _failure(
                failures,
                kind="parser",
                code="UNKNOWN_TOKENIZER",
                message="declared tokenizer is not registered",
                recovery_hint="full_fallback",
            )
            internal_failure = True
        if tokenizer is not None and output is not None:
            if tokenizer.identity != raw_result.tokenizer_id:
                _failure(
                    failures,
                    kind="policy",
                    code="RAW_TOKENIZER_MISMATCH",
                    message="raw result tokenizer differs from declared tokenizer",
                    recovery_hint="full_fallback",
                )
            source_text = source.raw_bytes.decode("utf-8", "strict")
            original_count = tokenizer.count(source_text)
            compressed_count = tokenizer.count(output_text or "")
            achieved = _ratio(0 if original_count == 0 else 1 - compressed_count / original_count)
            if original_count == 0:
                _failure(
                    failures,
                    kind="parser",
                    code="ZERO_ORIGINAL_TOKENS",
                    message="certificate token accounting cannot divide by zero",
                )
                internal_failure = True
            _verify_count_observation(
                certificate.tokenization.original_token_count,
                original_count,
                failures,
                label="original_token",
            )
            _verify_count_observation(
                certificate.tokenization.compressed_token_count,
                compressed_count,
                failures,
                label="compressed_token",
            )
            if (
                raw_result.original_token_count != original_count
                or raw_result.compressed_token_count != compressed_count
            ):
                _failure(
                    failures,
                    kind="policy",
                    code="RAW_TOKEN_COUNT_MISMATCH",
                    message="raw result token counts are incorrect",
                    recovery_hint="expand_budget",
                )
            _verify_reduction_observation(
                certificate.reduction.achieved_reduction,
                achieved,
                failures,
            )
            if (
                raw_result.achieved_reduction is None
                or _ratio(raw_result.achieved_reduction) != achieved
            ):
                _failure(
                    failures,
                    kind="policy",
                    code="RAW_REDUCTION_MISMATCH",
                    message="raw result achieved reduction is incorrect",
                    recovery_hint="expand_budget",
                )
            if (
                raw_result.status == CompressionStatus.COMPRESSED
                and compressed_count >= original_count
            ):
                _failure(
                    failures,
                    kind="policy",
                    code="COMPRESSED_STATUS_FALSE",
                    message="compressed status requires a strictly shorter artifact",
                    recovery_hint="expand_budget",
                )
            if raw_result.status == CompressionStatus.UNCHANGED and output != source.raw_bytes:
                _failure(
                    failures,
                    kind="policy",
                    code="UNCHANGED_STATUS_FALSE",
                    message="unchanged status requires exact original bytes",
                    recovery_hint="full_fallback",
                )
            if evidence.request is not None:
                expected_budget = evidence.request.target_token_budget
                if expected_budget is None and evidence.request.requested_reduction is not None:
                    expected_budget = max(
                        1,
                        math.floor(original_count * (1 - evidence.request.requested_reduction)),
                    )
                if raw_result.requested_token_budget != expected_budget:
                    _failure(
                        failures,
                        kind="policy",
                        code="BUDGET_MISMATCH",
                        message="raw result budget does not match request",
                        recovery_hint="expand_budget",
                    )
                if expected_budget is not None and compressed_count > expected_budget:
                    _failure(
                        failures,
                        kind="policy",
                        code="TOKEN_BUDGET_EXCEEDED",
                        message="final compressed token count exceeds requested budget",
                        recovery_hint="expand_budget",
                    )

        try:
            content_type = (
                evidence.request.source_kind
                if evidence.request is not None
                else ContentType(source.kind)
            )
            independent = extract_obligations(source, content_type)
            _compare_extraction(evidence.extraction, independent, failures)
            if independent.failure is not None or independent.coverage.value == "failed":
                _failure(
                    failures,
                    kind="parser",
                    code="EXTRACTION_FAILURE",
                    message="independent extraction failed",
                    recovery_hint="full_fallback",
                )
                internal_failure = True
            warnings.extend(
                _warning("verifier", item.code, item.message, item.source_ids)
                for item in independent.warnings
            )
        except (UnicodeDecodeError, SourceCoordinateError, ValueError, SyntaxError) as exc:
            _failure(
                failures,
                kind="parser",
                code="EXTRACTION_FAILURE",
                message=type(exc).__name__,
                recovery_hint="full_fallback",
            )
            internal_failure = True

        if independent is not None and source_map is not None and output is not None:
            _verify_source_span_lineage(independent, source_map, failures)
            if evidence.original_source_map is not None:
                _map_validation(
                    source,
                    normalized,
                    output,
                    evidence.original_source_map,
                    manifest,
                    failures,
                )
                _verify_source_span_lineage(independent, evidence.original_source_map, failures)
            _verify_omissions(raw_result, independent, source_map, failures)
            obligation_results, relation_results, hard_represented, relation_represented = (
                _coverage(independent, source, source_map, output)
            )
            _verify_claimed_coverage(
                certificate,
                raw_result,
                obligation_results,
                relation_results,
                failures,
            )
            hard_total = sum(1 for item in independent.obligations if _hard_obligation(item))
            relation_total = len(independent.relations)
            protected_total = hard_total + relation_total
            source_map_coverage = _source_map_coverage(
                source_map,
                protected_total,
                len(hard_represented) + len(relation_represented),
            )
            if certificate.verification_status == "passed":
                verified_count = sum(item.verified for item in obligation_results.values())
                discovered_count = sum(item.discovered for item in obligation_results.values())
                expected_value = (
                    _ratio(verified_count / discovered_count) if discovered_count else None
                )
                claimed_coverage = certificate.coverage
                independent_discovery = _overall_discovery(
                    independent, obligation_results, relation_results
                )
                if (
                    claimed_coverage.discovery_status != independent_discovery
                    or claimed_coverage.certificate.verifier_discovered != discovered_count
                    or claimed_coverage.certificate.verified_discovered != verified_count
                    or claimed_coverage.certificate.value != expected_value
                    or claimed_coverage.source_map != source_map_coverage
                ):
                    _failure(
                        failures,
                        kind="policy",
                        code="SEALED_COVERAGE_MISMATCH",
                        message="sealed aggregate coverage disagrees with independent evidence",
                    )
            for item in independent.obligations:
                if item.obligation_id not in hard_represented and _hard_obligation(item):
                    _failure(
                        failures,
                        kind="obligation",
                        code="OBLIGATION_NOT_REPRESENTED",
                        message="hard obligation lacks independently usable mapped evidence",
                        source_span_ids=item.source_span_ids,
                        recovery_hint="restore_spans",
                    )
            for relation in independent.relations:
                if relation.relation_id not in relation_represented:
                    _failure(
                        failures,
                        kind="relation",
                        code="RELATION_NOT_REPRESENTED",
                        message="relation endpoints or evidence are not independently connected",
                        source_span_ids=relation.evidence_span_ids,
                        recovery_hint="restore_spans",
                    )

        if (
            independent is not None
            and evidence.original_source_map is not None
            and (source_map is None or output is None)
        ):
            _map_validation(
                source,
                normalized,
                output or b"",
                evidence.original_source_map,
                manifest,
                failures,
            )
            _verify_source_span_lineage(independent, evidence.original_source_map, failures)

    except (
        UnicodeDecodeError,
        SourceCoordinateError,
        ValueError,
        TypeError,
        json.JSONDecodeError,
    ) as exc:
        _failure(
            failures,
            kind="parser",
            code="VERIFIER_EXECUTION_FAILURE",
            message=type(exc).__name__,
            recovery_hint="full_fallback",
        )
        internal_failure = True

    discovery = (
        _overall_discovery(independent, obligation_results, relation_results)
        if independent is not None
        else DiscoveryStatus.UNKNOWN
    )
    if discovery == DiscoveryStatus.UNKNOWN:
        unverifiable = True
    if discovery == DiscoveryStatus.PARTIAL:
        completeness = Completeness.PARTIAL
    elif discovery == DiscoveryStatus.KNOWN and not failures:
        completeness = Completeness.COMPLETE
    else:
        completeness = Completeness.UNKNOWN
    recommended = _recommended_action(raw_result, failures, discovery)
    if (unverifiable and not failures) or internal_failure:
        recommended = FinalAction.FULL_FALLBACK
    if certificate.artifact_role == "end_to_end":
        if not _end_to_end_action_valid(certificate, recommended):
            _failure(
                failures,
                kind="policy",
                code="END_TO_END_ACTION_MISMATCH",
                message="end-to-end action disagrees with recovery history or final verification",
                recovery_hint="full_fallback",
            )
    elif certificate.action.selected_action != recommended:
        _failure(
            failures,
            kind="policy",
            code="ACTION_MISMATCH",
            message="certificate selected action disagrees with independent policy",
            recovery_hint="full_fallback",
        )
    if (
        certificate.artifact_role != "end_to_end"
        and certificate.action.recomputed_action != recommended
    ):
        _failure(
            failures,
            kind="policy",
            code="RECOMPUTED_ACTION_MISMATCH",
            message="certificate recomputed action disagrees with independent policy",
            recovery_hint="full_fallback",
        )
    if certificate.action.match != (
        certificate.action.selected_action == certificate.action.recomputed_action
    ):
        _failure(
            failures,
            kind="policy",
            code="ACTION_MATCH_FLAG_MISMATCH",
            message="certificate action match flag is inconsistent",
            recovery_hint="full_fallback",
        )
    if internal_failure:
        status = VerificationReportStatus.FAILED
    elif failures:
        status = VerificationReportStatus.INVALID
    elif unverifiable:
        status = VerificationReportStatus.UNVERIFIABLE
    else:
        status = VerificationReportStatus.VALID
    return VerificationReport(
        report_version="1.0.0",
        certificate_hash=_certificate_hash(candidate),
        verification_run_id=evidence.verification_run_id,
        status=status,
        verified_source_hash=verified_source_hash,
        verified_normalized_hash=verified_normalized_hash,
        verified_query_hash=verified_query_hash,
        verified_request_hash=verified_request_hash,
        verified_compressed_artifact_hash=verified_compressed_hash,
        verified_tokenizer=(
            CertificateTokenizerIdentity.model_validate(tokenizer.identity.model_dump(mode="json"))
            if tokenizer is not None
            else None
        ),
        original_token_count=original_count,
        compressed_token_count=compressed_count,
        achieved_reduction=achieved,
        obligation_results=obligation_results,
        relation_results=relation_results,
        source_map_coverage=source_map_coverage,
        discovery_status=discovery,
        completeness=completeness,
        failed_checks=failures,
        warnings=warnings,
        recommended_action=recommended,
        verifier_component_version=COMPONENT_VERSION,
    )


def verify_compact_context(*args: Any, **kwargs: Any) -> Any:
    """Delegate compact-fact verification without sharing compressor logic."""

    from tracefold.compact_verifier import verify_compact_context as _verify_compact_context

    return _verify_compact_context(*args, **kwargs)


__all__ = [
    "COMPONENT_VERSION",
    "DEFAULT_VERIFICATION_RUN_ID",
    "VerificationEvidence",
    "VerificationExecutionError",
    "verify_compact_context",
    "verify_certificate",
]
