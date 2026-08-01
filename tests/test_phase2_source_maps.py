from datetime import UTC, datetime

import pytest

from tracefold.extractors import extract_obligations
from tracefold.relations import validate_relations
from tracefold.schemas.phase2 import ExtractionResult
from tracefold.schemas.source import SourceInput
from tracefold.schemas.source_map import SourceMap
from tracefold.source_maps import build_source_map, validate_source_map
from tracefold.sources import ingest_source

RUN_ID = "123e4567-e89b-42d3-a456-426614174000"
CREATED_AT = datetime(2026, 8, 1, tzinfo=UTC)


def make_result(text: str) -> ExtractionResult:
    source = ingest_source(
        SourceInput(
            input_ordinal=0,
            kind="text",
            authority="user",
            media_type="text/plain",
            text=text,
        )
    )
    return extract_obligations(source)


def artifact_bytes(result: ExtractionResult, source_map: SourceMap) -> dict[str, bytes]:
    return {
        artifact.artifact_id: (
            result.sources[0].raw_bytes
            if artifact.stage.value == "original"
            else result.normalized_sources[0].normalized_bytes
        )
        for artifact in source_map.artifacts
    }


def test_source_map_is_deterministic_bidirectional_and_normalization_bound() -> None:
    result = make_result("Limit: 15 ms\r\n")
    first = build_source_map(result, run_id=RUN_ID, attempt_id="attempt-1", created_at=CREATED_AT)
    second = build_source_map(result, run_id=RUN_ID, attempt_id="attempt-1", created_at=CREATED_AT)
    assert first.map_id == second.map_id
    assert first.forward_index
    assert first.reverse_index
    assert any(mapping.transform == "normalize_line_ending" for mapping in first.mappings)
    assert any(mapping.exactness == "character_equivalent" for mapping in first.mappings)
    validation = validate_source_map(first, artifacts=artifact_bytes(result, first))
    assert validation.valid
    assert not validation.stale


def test_mutated_artifact_and_coordinates_are_stale() -> None:
    result = make_result("é: 15 ms\n")
    source_map = build_source_map(
        result, run_id=RUN_ID, attempt_id="attempt-1", created_at=CREATED_AT
    )
    artifacts = artifact_bytes(result, source_map)
    original_id = next(
        artifact.artifact_id
        for artifact in source_map.artifacts
        if artifact.stage.value == "original"
    )
    mutated = dict(artifacts)
    mutated[original_id] = b"changed"
    validation = validate_source_map(source_map, artifacts=mutated)
    assert not validation.valid
    assert validation.stale

    span = source_map.spans[0]
    changed_span = span.model_copy(update={"byte_end": span.byte_end + 1})
    changed_map = source_map.model_copy(update={"spans": [changed_span, *source_map.spans[1:]]})
    changed_validation = validate_source_map(changed_map, artifacts=artifacts)
    assert not changed_validation.valid
    assert changed_validation.stale


def test_invalid_run_id_and_map_id_fail_validation() -> None:
    result = make_result("plain")
    source_map = build_source_map(
        result, run_id=RUN_ID, attempt_id="attempt-1", created_at=CREATED_AT
    )
    changed = source_map.model_copy(
        update={"run_id": "not-a-uuid", "map_id": "map:source-map:wrong"}
    )
    validation = validate_source_map(changed, artifacts=artifact_bytes(result, source_map))
    assert not validation.valid
    assert "invalid run_id" in validation.errors
    assert "map_id" in " ".join(validation.errors)


def test_relation_validation_rejects_missing_endpoints() -> None:
    result = make_result("Limit: 15 ms")
    relation = result.relations[0].model_copy(
        update={"obligation_ids": ["obl:missing", result.relations[0].obligation_ids[1]]}
    )
    with pytest.raises(ValueError, match="missing obligation"):
        validate_relations(
            [relation],
            result.obligations,
            {span.span_id for span in result.spans},
        )
