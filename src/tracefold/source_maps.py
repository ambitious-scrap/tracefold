import hashlib
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal, cast

from tracefold.hashing import hash_query, hash_source_manifest, sha256_domain
from tracefold.obligations import make_source_span
from tracefold.run_ids import validate_run_id
from tracefold.schemas.api import QueryEnvelope
from tracefold.schemas.common import ArtifactStage, HashDomain, HashValue
from tracefold.schemas.phase2 import ExtractionResult, NormalizedSource, SourceMapValidation
from tracefold.schemas.source import SourceManifest, SourceManifestEntry
from tracefold.schemas.source_map import (
    ArtifactRecord,
    MapCoverage,
    MappingRecord,
    NormalizationProfile,
    SourceMap,
    SourceSpan,
)
from tracefold.serialization import canonical_json_bytes
from tracefold.sources import (
    SourceCoordinateError,
    SourceCoordinateIndex,
    _validate_file_path,
    original_char_range_to_normalized,
)


class SourceMapValidationError(ValueError):
    """A source map is stale or violates its coordinate contract."""


def _artifact_id(stage: str, source_id: str) -> str:
    return f"artifact:{stage}:{source_id}"


def _artifact_hash(stage: str, raw: bytes) -> HashValue:
    domain = (
        HashDomain.SOURCE_ARTIFACT
        if stage == "original"
        else HashDomain.NORMALIZED_ARTIFACT
        if stage == "normalized"
        else HashDomain.CONTEXT_ARTIFACT
    )
    return sha256_domain(domain, raw)


def _artifact_record(
    source_id: str,
    stage: str,
    raw: bytes,
    source: Any,
) -> ArtifactRecord:
    index = SourceCoordinateIndex(raw)
    return ArtifactRecord(
        artifact_id=_artifact_id(stage, source_id),
        stage=ArtifactStage(stage),
        source_id=source_id,
        media_type=source.media_type,
        encoding="utf-8",
        byte_length=index.byte_length,
        char_length=index.char_length,
        line_count=index.line_count,
        hash=_artifact_hash(stage, raw),
        file_path=source.file_path,
        message_id=source.message_id,
        role=source.role,
    )


def _normalized_span(
    normalized: NormalizedSource,
    original_span: SourceSpan,
    start: int,
    end: int,
) -> SourceSpan:
    index = SourceCoordinateIndex(normalized.normalized_bytes)
    byte_start, byte_end, line_start, column_start, line_end, column_end = index.character_range(
        start, end
    )
    raw = normalized.normalized_bytes[byte_start:byte_end]
    artifact_id = _artifact_id("normalized", normalized.source.source_id)
    digest = hashlib.sha256(raw).hexdigest()[:16]
    span_id = f"span:{artifact_id}:{byte_start}:{byte_end}:{original_span.kind}:{digest}"
    return SourceSpan(
        span_id=span_id,
        artifact_id=artifact_id,
        kind=original_span.kind,
        byte_start=byte_start,
        byte_end=byte_end,
        char_start=start,
        char_end=end,
        line_start=line_start,
        column_start=column_start,
        line_end=line_end,
        column_end=column_end,
        span_hash=sha256_domain(HashDomain.SPAN, raw),
        json_path=original_span.json_path,
        file_path=original_span.file_path,
        code_symbol_id=original_span.code_symbol_id,
        log_event_id=original_span.log_event_id,
        conversation_message_id=original_span.conversation_message_id,
        role=original_span.role,
        structured_identity=original_span.structured_identity,
    )


def _mapping_id(transform: str, from_ids: list[str], to_ids: list[str]) -> str:
    digest = hashlib.sha256(
        canonical_json_bytes({"transform": transform, "from": from_ids, "to": to_ids})
    ).hexdigest()[:16]
    return f"map:{transform}:{digest}"


def _deduplicate_mappings(mappings: list[MappingRecord]) -> list[MappingRecord]:
    unique: dict[str, MappingRecord] = {}
    for mapping in mappings:
        previous = unique.get(mapping.mapping_id)
        if previous is None:
            unique[mapping.mapping_id] = mapping
            continue
        unique[mapping.mapping_id] = previous.model_copy(
            update={
                "obligation_ids": list(
                    dict.fromkeys([*previous.obligation_ids, *mapping.obligation_ids])
                ),
                "relation_ids": list(
                    dict.fromkeys([*previous.relation_ids, *mapping.relation_ids])
                ),
            }
        )
    return list(unique.values())


def _manifest(result: ExtractionResult) -> SourceManifest:
    entries = []
    for source in sorted(result.sources, key=lambda item: item.input_ordinal):
        entries.append(
            SourceManifestEntry(
                source_id=source.source_id,
                input_ordinal=source.input_ordinal,
                kind=source.kind,
                authority=source.authority,
                media_type=source.media_type,
                raw_byte_hash=sha256_domain(HashDomain.SOURCE_ARTIFACT, source.raw_bytes),
                byte_length=len(source.raw_bytes),
                file_path=source.file_path,
                message_id=source.message_id,
                role=source.role,
            )
        )
    return SourceManifest(entries=entries)


def _coverage_ratio(numerator: int, denominator: int) -> str | None:
    if denominator == 0:
        return None
    return f"{numerator / denominator:.6f}"


def _exact_normalized_byte_count(normalized: NormalizedSource) -> int:
    index = SourceCoordinateIndex(normalized.normalized_bytes)
    changed = 0
    for operation in normalized.operations:
        if operation.rule_id == "normalize_line_ending":
            start = index.char_to_byte(operation.normalized_char_start)
            end = index.char_to_byte(operation.normalized_char_end)
            changed += end - start
    return len(normalized.normalized_bytes) - changed


def build_source_map(
    result: ExtractionResult,
    *,
    run_id: str,
    attempt_id: str,
    created_at: datetime,
) -> SourceMap:
    validate_run_id(run_id)
    if not attempt_id:
        raise ValueError("attempt_id must be non-empty")
    if created_at.tzinfo is None:
        raise ValueError("created_at must be timezone-aware UTC")
    created_at = created_at.astimezone(UTC)
    if result.failure is not None:
        raise SourceMapValidationError("cannot build source map from failed extraction")

    normalized_by_source = {item.source.source_id: item for item in result.normalized_sources}
    spans = list(result.spans)
    span_by_id = {span.span_id: span for span in spans}
    if len(span_by_id) != len(spans):
        raise SourceMapValidationError("duplicate extraction span IDs")
    obligations_by_span: dict[str, list[str]] = {}
    relations_by_span: dict[str, list[str]] = {}
    for obligation in result.obligations:
        for span_id in obligation.source_span_ids:
            obligations_by_span.setdefault(span_id, []).append(obligation.obligation_id)
    for relation in result.relations:
        for span_id in relation.evidence_span_ids:
            relations_by_span.setdefault(span_id, []).append(relation.relation_id)

    ordered_sources = sorted(result.sources, key=lambda item: item.input_ordinal)
    artifacts: list[ArtifactRecord] = []
    for source in ordered_sources:
        normalized = normalized_by_source.get(source.source_id)
        if normalized is None:
            raise SourceMapValidationError("missing normalized source")
        artifacts.append(_artifact_record(source.source_id, "original", source.raw_bytes, source))
    for source in ordered_sources:
        normalized = normalized_by_source[source.source_id]
        artifacts.append(
            _artifact_record(source.source_id, "normalized", normalized.normalized_bytes, source)
        )
    map_spans: list[SourceSpan] = []
    mappings: list[MappingRecord] = []
    for source in ordered_sources:
        normalized = normalized_by_source[source.source_id]
        full = make_source_span(source, 0, len(source.raw_bytes.decode("utf-8")), kind="text")
        if full.span_id not in span_by_id:
            span_by_id[full.span_id] = full
            map_spans.append(full)
        normalized_full = _normalized_span(normalized, full, 0, len(normalized.normalized_text))
        if normalized_full.span_id not in span_by_id:
            span_by_id[normalized_full.span_id] = normalized_full
            map_spans.append(normalized_full)
        full_changed = source.raw_bytes != normalized.normalized_bytes
        mappings.append(
            MappingRecord(
                mapping_id=_mapping_id(
                    "normalize_line_ending" if full_changed else "exact_copy",
                    [full.span_id],
                    [normalized_full.span_id],
                ),
                transform="normalize_line_ending" if full_changed else "exact_copy",
                from_span_ids=[full.span_id],
                to_span_ids=[normalized_full.span_id],
                exactness="character_equivalent" if full_changed else "byte_exact",
                ordering="preserved",
                reason_code="phase2-normalization",
                transform_component="tracefold.normalizer",
                transform_version="0.1.0",
            )
        )
        for span in [
            item for item in spans if item.artifact_id == _artifact_id("original", source.source_id)
        ]:
            if span.span_id not in span_by_id:
                span_by_id[span.span_id] = span
            if span not in map_spans:
                map_spans.append(span)
            normalized_start, normalized_end = original_char_range_to_normalized(
                normalized, span.char_start, span.char_end
            )
            normalized_span = _normalized_span(normalized, span, normalized_start, normalized_end)
            if normalized_span.span_id not in span_by_id:
                span_by_id[normalized_span.span_id] = normalized_span
                map_spans.append(normalized_span)
            original_bytes = source.raw_bytes[span.byte_start : span.byte_end]
            normalized_bytes = normalized.normalized_bytes[
                normalized_span.byte_start : normalized_span.byte_end
            ]
            changed = original_bytes != normalized_bytes
            transform = "normalize_line_ending" if changed else "exact_copy"
            exactness = "character_equivalent" if changed else "byte_exact"
            mapping = MappingRecord(
                mapping_id=_mapping_id(transform, [span.span_id], [normalized_span.span_id]),
                transform=cast(
                    Literal[
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
                    ],
                    transform,
                ),
                from_span_ids=[span.span_id],
                to_span_ids=[normalized_span.span_id],
                exactness=cast(
                    Literal[
                        "byte_exact",
                        "character_equivalent",
                        "structurally_equivalent",
                        "semantic_lineage_only",
                        "none_deleted",
                    ],
                    exactness,
                ),
                ordering="preserved",
                reason_code="phase2-normalization",
                obligation_ids=obligations_by_span.get(span.span_id, []),
                relation_ids=relations_by_span.get(span.span_id, []),
                transform_component="tracefold.normalizer",
                transform_version="0.1.0",
            )
            mappings.append(mapping)

        for operation in normalized.operations:
            if operation.rule_id != "remove_utf8_bom":
                continue
            tombstone = make_source_span(
                source,
                operation.original_char_start,
                operation.original_char_end,
                kind="tombstone",
            )
            if tombstone.span_id not in span_by_id:
                span_by_id[tombstone.span_id] = tombstone
                map_spans.append(tombstone)
            mappings.append(
                MappingRecord(
                    mapping_id=_mapping_id("delete_normalization_marker", [tombstone.span_id], []),
                    transform="delete_normalization_marker",
                    from_span_ids=[tombstone.span_id],
                    to_span_ids=[],
                    exactness="none_deleted",
                    ordering="not_applicable",
                    reason_code="utf8-bom",
                    transform_component="tracefold.normalizer",
                    transform_version="0.1.0",
                )
            )

    mappings = _deduplicate_mappings(mappings)
    protected_count = len(result.obligations)
    valid_mapped_count = sum(
        1
        for obligation in result.obligations
        if all(span_id in span_by_id for span_id in obligation.source_span_ids)
    )
    total_original_bytes = sum(len(source.raw_bytes) for source in ordered_sources)
    total_normalized_bytes = sum(
        len(normalized_by_source[source.source_id].normalized_bytes) for source in ordered_sources
    )
    exact_normalized_bytes = sum(
        _exact_normalized_byte_count(normalized_by_source[source.source_id])
        for source in ordered_sources
    )
    coverage = MapCoverage(
        lineage_coverage=_coverage_ratio(total_normalized_bytes, total_normalized_bytes),
        exact_copy_coverage=_coverage_ratio(exact_normalized_bytes, total_normalized_bytes),
        protected_item_map_coverage=_coverage_ratio(valid_mapped_count, protected_count),
        original_deletion_coverage=_coverage_ratio(total_original_bytes, total_original_bytes),
        synthesized_span_count=0,
        restored_span_count=0,
    )
    profile = NormalizationProfile(
        profile_id="tracefold.phase2.normalization",
        version="0.1.0",
        rules=sorted(
            {
                operation.rule_id
                for item in result.normalized_sources
                for operation in item.operations
            }
        ),
    )
    source_manifest = _manifest(result)
    forward, reverse = _indexes(mappings)
    source_map = SourceMap(
        schema_id="tracefold.source-map",
        source_map_version="1.0.0",
        map_id="pending",
        run_id=run_id,
        attempt_id=attempt_id,
        source_manifest_hash=hash_source_manifest(source_manifest),
        query_hash=hash_query(QueryEnvelope(query=None)),
        artifacts=artifacts,
        spans=map_spans,
        mappings=mappings,
        forward_index=forward,
        reverse_index=reverse,
        coverage=coverage,
        normalization_profile=profile,
        component_version="tracefold.source-map/0.1.0",
        created_at=created_at,
    )
    identity_payload = source_map.model_dump(mode="json", exclude={"map_id", "created_at"})
    map_digest = sha256_domain(HashDomain.SOURCE_MAP, canonical_json_bytes(identity_payload))
    source_map = source_map.model_copy(update={"map_id": f"map:source-map:{map_digest[7:23]}"})
    validation = validate_source_map(
        source_map,
        artifacts={
            artifact.artifact_id: (
                next(
                    source.raw_bytes
                    for source in result.sources
                    if source.source_id == artifact.source_id
                )
                if artifact.stage == "original"
                else next(
                    item.normalized_bytes
                    for item in result.normalized_sources
                    if item.source.source_id == artifact.source_id
                )
            )
            for artifact in artifacts
        },
        source_manifest=source_manifest,
    )
    if not validation.valid:
        raise SourceMapValidationError("; ".join(validation.errors))
    return source_map


def _indexes(mappings: list[MappingRecord]) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    forward: dict[str, list[str]] = {}
    reverse: dict[str, list[str]] = {}
    for mapping in mappings:
        for span_id in mapping.from_span_ids:
            forward.setdefault(span_id, []).append(mapping.mapping_id)
        for span_id in mapping.to_span_ids:
            reverse.setdefault(span_id, []).append(mapping.mapping_id)
    return forward, reverse


def _valid_pointer(pointer: str) -> bool:
    if pointer == "":
        return True
    if not pointer.startswith("/"):
        return False
    for token in pointer.split("/")[1:]:
        if "~" in token and re.search(r"~(?![01])", token):
            return False
    return True


def _valid_path(path: str | None) -> bool:
    if path is None:
        return True
    try:
        _validate_file_path(path)
    except ValueError:
        return False
    return True


def validate_source_map(
    source_map: SourceMap,
    *,
    artifacts: Mapping[str, bytes] | None = None,
    source_manifest: SourceManifest | None = None,
) -> SourceMapValidation:
    errors: list[str] = []
    stale = False
    try:
        validate_run_id(source_map.run_id)
    except ValueError:
        errors.append("invalid run_id")
    if source_map.created_at.tzinfo is None:
        errors.append("created_at must be timezone-aware UTC")
    try:
        SourceMap.model_validate(source_map)
    except ValueError as exc:
        errors.append(str(exc))
        return SourceMapValidation(valid=False, stale=False, errors=errors)

    artifact_by_id = {artifact.artifact_id: artifact for artifact in source_map.artifacts}
    span_by_id = {span.span_id: span for span in source_map.spans}
    if len(artifact_by_id) != len(source_map.artifacts):
        errors.append("duplicate artifact IDs")
    if len(span_by_id) != len(source_map.spans):
        errors.append("duplicate span IDs")

    if artifacts is not None:
        for artifact_id, artifact in artifact_by_id.items():
            raw = artifacts.get(artifact_id)
            if raw is None:
                errors.append(f"missing bytes for artifact {artifact_id}")
                continue
            expected = _artifact_hash(artifact.stage.value, raw)
            if expected != artifact.hash:
                errors.append(f"stale artifact hash: {artifact_id}")
                stale = True
            try:
                index = SourceCoordinateIndex(raw)
            except SourceCoordinateError:
                errors.append(f"invalid UTF-8 artifact: {artifact_id}")
                stale = True
                continue
            if (
                index.byte_length != artifact.byte_length
                or index.char_length != artifact.char_length
                or index.line_count != artifact.line_count
            ):
                errors.append(f"stale artifact dimensions: {artifact_id}")
                stale = True
            for span in source_map.spans:
                if span.artifact_id != artifact_id:
                    continue
                try:
                    expected_coordinates = index.character_range(span.char_start, span.char_end)
                    expected_hash = sha256_domain(
                        HashDomain.SPAN, raw[span.byte_start : span.byte_end]
                    )
                except (SourceCoordinateError, IndexError):
                    errors.append(f"out-of-bounds span: {span.span_id}")
                    stale = True
                    continue
                if expected_coordinates != (
                    span.byte_start,
                    span.byte_end,
                    span.line_start,
                    span.column_start,
                    span.line_end,
                    span.column_end,
                ):
                    errors.append(f"mismatched coordinates: {span.span_id}")
                    stale = True
                if expected_hash != span.span_hash:
                    errors.append(f"stale span hash: {span.span_id}")
                    stale = True

    for span in source_map.spans:
        span_artifact = artifact_by_id.get(span.artifact_id)
        if span_artifact is None:
            errors.append(f"span references missing artifact: {span.span_id}")
        elif (
            span.byte_end > span_artifact.byte_length
            or span.char_end > span_artifact.char_length
            or span.line_start > max(1, span_artifact.line_count)
            or span.line_end > max(1, span_artifact.line_count)
        ):
            errors.append(f"out-of-bounds span: {span.span_id}")
        if not _valid_pointer(span.json_path or ""):
            errors.append(f"invalid JSON pointer: {span.span_id}")
        if not _valid_path(span.file_path):
            errors.append(f"invalid portable file path: {span.span_id}")

    for mapping in source_map.mappings:
        if not set(mapping.from_span_ids).issubset(span_by_id):
            errors.append(f"mapping references missing source span: {mapping.mapping_id}")
        if not set(mapping.to_span_ids).issubset(span_by_id):
            errors.append(f"mapping references missing target span: {mapping.mapping_id}")
        if mapping.exactness == "byte_exact" and (
            not mapping.from_span_ids or not mapping.to_span_ids
        ):
            errors.append(f"byte-exact mapping needs endpoints: {mapping.mapping_id}")
        if mapping.transform == "synthesize_summary" and mapping.exactness == "byte_exact":
            errors.append(f"synthesized summary cannot be byte-exact: {mapping.mapping_id}")
        if (
            artifacts is not None
            and mapping.exactness == "byte_exact"
            and set(mapping.from_span_ids).issubset(span_by_id)
            and set(mapping.to_span_ids).issubset(span_by_id)
        ):
            if len(mapping.from_span_ids) != 1 or len(mapping.to_span_ids) != 1:
                errors.append(
                    f"byte-exact mapping must have one source and target: {mapping.mapping_id}"
                )
            else:
                from_span = span_by_id[mapping.from_span_ids[0]]
                to_span = span_by_id[mapping.to_span_ids[0]]
                from_bytes = artifacts.get(from_span.artifact_id)
                to_bytes = artifacts.get(to_span.artifact_id)
                if from_bytes is not None and to_bytes is not None:
                    if (
                        from_bytes[from_span.byte_start : from_span.byte_end]
                        != to_bytes[to_span.byte_start : to_span.byte_end]
                    ):
                        errors.append(f"byte-exact mapping bytes differ: {mapping.mapping_id}")
                        stale = True
        if (
            mapping.transform == "delete"
            and mapping.to_span_ids
            and mapping.exactness == "none_deleted"
        ):
            errors.append(f"deleted mapping has target spans: {mapping.mapping_id}")

    expected_forward, expected_reverse = _indexes(source_map.mappings)
    if expected_forward != source_map.forward_index:
        errors.append("forward index mismatch")
    if expected_reverse != source_map.reverse_index:
        errors.append("reverse index mismatch")
    if (
        source_manifest is not None
        and hash_source_manifest(source_manifest) != source_map.source_manifest_hash
    ):
        errors.append("stale source manifest hash")
        stale = True
    identity_payload = source_map.model_dump(mode="json", exclude={"map_id", "created_at"})
    expected_map_id = (
        "map:source-map:"
        + sha256_domain(HashDomain.SOURCE_MAP, canonical_json_bytes(identity_payload))[7:23]
    )
    if source_map.map_id != expected_map_id:
        errors.append("map_id does not match canonical map content")
    return SourceMapValidation(valid=not errors, stale=stale, errors=errors)


def assert_valid_source_map(
    source_map: SourceMap,
    *,
    artifacts: Mapping[str, bytes] | None = None,
    source_manifest: SourceManifest | None = None,
) -> None:
    validation = validate_source_map(
        source_map, artifacts=artifacts, source_manifest=source_manifest
    )
    if not validation.valid:
        raise SourceMapValidationError("; ".join(validation.errors))


__all__ = [
    "SourceMapValidationError",
    "assert_valid_source_map",
    "build_source_map",
    "validate_source_map",
]
