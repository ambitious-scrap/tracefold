import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from tracefold.compression import (
    build_candidates,
    calculate_mandatory_set,
    compress_source,
    select_candidates,
)
from tracefold.compression_report import build_report
from tracefold.extractors import extract_obligations
from tracefold.schemas.phase2 import ContentType, SourceArtifact
from tracefold.schemas.phase3 import CompressionStatus, RawCompressionRequest
from tracefold.schemas.source import SourceInput
from tracefold.serialization import canonical_json_bytes
from tracefold.source_maps import validate_source_map
from tracefold.sources import ingest_source
from tracefold.tokenizers import TokenizerIdentity, TokenizerRegistry, UnknownTokenizerError

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "phase3"
RUN_ID = "123e4567-e89b-42d3-a456-426614174000"


class FixtureTokenizer:
    """Deterministic non-production tokenizer used by Phase 3 tests."""

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
def tokenizer() -> FixtureTokenizer:
    return FixtureTokenizer()


@pytest.fixture
def registry(tokenizer: FixtureTokenizer) -> TokenizerRegistry:
    result = TokenizerRegistry()
    result.register(tokenizer)
    return result


def source_from_fixture(name: str, kind: ContentType, ordinal: int = 0) -> SourceArtifact:
    path = FIXTURE_ROOT / name
    return ingest_source(
        SourceInput(
            input_ordinal=ordinal,
            kind=kind.value,
            authority="fixture",
            media_type="application/json" if kind == ContentType.JSON else "text/plain",
            text=path.read_text(encoding="utf-8"),
        )
    )


def request(
    source: SourceArtifact,
    kind: ContentType,
    tokenizer: FixtureTokenizer,
    target_token_budget: int | None = None,
    requested_reduction: float | None = None,
) -> RawCompressionRequest:
    return RawCompressionRequest(
        run_id=RUN_ID,
        source_id=source.source_id,
        source_kind=kind,
        tokenizer_id=tokenizer.identity,
        target_token_budget=target_token_budget,
        requested_reduction=requested_reduction,
    )


def test_request_validation_and_budget_precedence(tokenizer: FixtureTokenizer) -> None:
    source = source_from_fixture("document.txt", ContentType.DOCUMENT)
    value = request(
        source,
        ContentType.DOCUMENT,
        tokenizer,
        target_token_budget=100,
        requested_reduction=0.5,
    )
    assert value.target_token_budget == 100
    assert value.requested_reduction == 0.5
    with pytest.raises(ValidationError):
        request(source, ContentType.DOCUMENT, tokenizer)
    with pytest.raises(ValidationError):
        request(source, ContentType.DOCUMENT, tokenizer, target_token_budget=0)
    with pytest.raises(ValidationError):
        request(source, ContentType.DOCUMENT, tokenizer, requested_reduction=1.0)
    with pytest.raises(ValidationError):
        RawCompressionRequest(
            run_id="123e4567-e89b-12d3-a456-426614174000",
            source_id=source.source_id,
            source_kind=ContentType.DOCUMENT,
            tokenizer_id=tokenizer.identity,
            target_token_budget=10,
        )


def test_selection_is_deterministic_and_mandatory_floor_is_enforced(
    tokenizer: FixtureTokenizer,
) -> None:
    source = source_from_fixture("document.txt", ContentType.DOCUMENT)
    extraction = extract_obligations(source, ContentType.DOCUMENT)
    first = build_candidates(source, extraction, tokenizer)
    second = build_candidates(source, extraction, tokenizer)
    assert [item.candidate_id for item in first] == [item.candidate_id for item in second]
    mandatory = calculate_mandatory_set(first, tokenizer)
    assert mandatory.minimum_token_count > 0
    selection = select_candidates(first, mandatory, mandatory.minimum_token_count - 1, tokenizer)
    assert not selection.fits_budget
    assert selection.minimum_token_count == mandatory.minimum_token_count


def test_document_and_dialogue_compilation_preserve_protected_content(
    tokenizer: FixtureTokenizer,
    registry: TokenizerRegistry,
) -> None:
    source = source_from_fixture("document.txt", ContentType.DOCUMENT)
    result = compress_source(
        request(source, ContentType.DOCUMENT, tokenizer, requested_reduction=0.0),
        source,
        registry,
    )
    assert result.status == CompressionStatus.COMPRESSED
    assert result.compressed_text is not None
    assert "[TraceFold repeated 3 times]" in result.compressed_text
    assert "must not" in result.compressed_text
    condition_coverage = result.relation_coverage["relation.condition_consequence"]
    assert condition_coverage.represented == condition_coverage.discovered
    assert condition_coverage.represented > 0
    assert result.source_map is not None

    dialogue = source_from_fixture("dialogue.txt", ContentType.DIALOGUE)
    dialogue_result = compress_source(
        request(dialogue, ContentType.DIALOGUE, tokenizer, requested_reduction=0.0),
        dialogue,
        registry,
    )
    assert dialogue_result.compressed_text is not None
    assert "system:" in dialogue_result.compressed_text
    assert "Actually" in dialogue_result.compressed_text
    assert "user:" in dialogue_result.compressed_text


def test_json_compilers_support_compact_schema_and_omitted_rows(
    tokenizer: FixtureTokenizer,
    registry: TokenizerRegistry,
) -> None:
    records = source_from_fixture("records.json", ContentType.JSON)
    compact = compress_source(
        request(records, ContentType.JSON, tokenizer, requested_reduction=0.0),
        records,
        registry,
    )
    assert compact.status == CompressionStatus.COMPRESSED
    assert compact.compressed_text is not None
    assert "@schema=" in compact.compressed_text
    assert "@rows=5" in compact.compressed_text

    simple = source_from_fixture("simple_records.json", ContentType.JSON)
    selective = compress_source(
        request(simple, ContentType.JSON, tokenizer, target_token_budget=250),
        simple,
        registry,
    )
    assert selective.status == CompressionStatus.COMPRESSED
    assert selective.compressed_text is not None
    assert "incident" in selective.compressed_text
    assert "@omitted_rows=" in selective.compressed_text
    assert selective.omitted_spans
    assert selective.source_map is not None
    assert any(mapping.transform == "delete" for mapping in selective.source_map.mappings)

    invalid = ingest_source(
        SourceInput(
            input_ordinal=99,
            kind="json",
            authority="fixture",
            media_type="application/json",
            text="{invalid",
        )
    )
    failed = compress_source(
        request(invalid, ContentType.JSON, tokenizer, target_token_budget=10),
        invalid,
        registry,
    )
    assert failed.status == CompressionStatus.FAILED
    assert failed.failure is not None
    assert failed.failure.code == "INVALID_JSON"


def test_log_compiler_groups_only_safe_normal_events(
    tokenizer: FixtureTokenizer,
    registry: TokenizerRegistry,
) -> None:
    source = source_from_fixture("events.log", ContentType.LOG)
    result = compress_source(
        request(source, ContentType.LOG, tokenizer, requested_reduction=0.0),
        source,
        registry,
    )
    assert result.status == CompressionStatus.COMPRESSED
    assert result.compressed_text is not None
    assert "[TraceFold logs x3" in result.compressed_text
    assert "error_code=E42" in result.compressed_text
    assert "trace=t-2" in result.compressed_text
    assert all(value.represented == value.discovered for value in result.relation_coverage.values())


def test_python_compiler_keeps_ast_obligations_and_emits_parseable_skeleton(
    tokenizer: FixtureTokenizer,
    registry: TokenizerRegistry,
) -> None:
    source = source_from_fixture("phase3_example.py", ContentType.PYTHON)
    result = compress_source(
        request(source, ContentType.PYTHON, tokenizer, requested_reduction=0.0),
        source,
        registry,
    )
    assert result.status == CompressionStatus.COMPRESSED
    assert result.compressed_text is not None
    ast.parse(result.compressed_text)
    assert "import math as m" in result.compressed_text
    assert "if value > LIMIT_MS" in result.compressed_text
    assert "raise ValueError" in result.compressed_text
    assert result.relation_coverage["relation.caller_callee"].represented > 0

    skeleton = source_from_fixture("skeleton.py", ContentType.PYTHON, ordinal=1)
    skeleton_result = compress_source(
        request(skeleton, ContentType.PYTHON, tokenizer, requested_reduction=0.0),
        skeleton,
        registry,
    )
    assert skeleton_result.compressed_text is not None
    ast.parse(skeleton_result.compressed_text)
    assert "TraceFold omitted" in skeleton_result.compressed_text

    invalid = ingest_source(
        SourceInput(
            input_ordinal=98,
            kind="python",
            authority="fixture",
            media_type="text/x-python",
            text="def broken(:\n    pass\n",
        )
    )
    failed = compress_source(
        request(invalid, ContentType.PYTHON, tokenizer, target_token_budget=10),
        invalid,
        registry,
    )
    assert failed.status == CompressionStatus.FAILED
    assert failed.failure is not None
    assert failed.failure.code == "PYTHON_SYNTAX_ERROR"

    dense = source_from_fixture("dense.py", ContentType.PYTHON, ordinal=2)
    dense_result = compress_source(
        request(dense, ContentType.PYTHON, tokenizer, target_token_budget=10),
        dense,
        registry,
    )
    assert dense_result.status == CompressionStatus.INCOMPRESSIBLE
    assert dense_result.compressed_text is None
    assert dense_result.minimum_mandatory_token_count > 10


def test_statuses_and_unknown_tokenizer(
    tokenizer: FixtureTokenizer,
    registry: TokenizerRegistry,
) -> None:
    source = ingest_source(
        SourceInput(
            input_ordinal=7,
            kind="document",
            authority="fixture",
            media_type="text/plain",
            text="unique text",
        )
    )
    unchanged = compress_source(
        request(source, ContentType.DOCUMENT, tokenizer, requested_reduction=0.0),
        source,
        registry,
    )
    assert unchanged.status == CompressionStatus.UNCHANGED
    assert unchanged.compressed_text == "unique text"
    empty = ingest_source(
        SourceInput(
            input_ordinal=8,
            kind="document",
            authority="fixture",
            media_type="text/plain",
            text="",
        )
    )
    empty_result = compress_source(
        request(empty, ContentType.DOCUMENT, tokenizer, requested_reduction=0.0),
        empty,
        registry,
    )
    assert empty_result.status == CompressionStatus.UNCHANGED
    assert empty_result.compressed_text == ""
    assert empty_result.source_map is not None
    incompressible = compress_source(
        request(
            source_from_fixture("document.txt", ContentType.DOCUMENT),
            ContentType.DOCUMENT,
            tokenizer,
            target_token_budget=1,
        ),
        source_from_fixture("document.txt", ContentType.DOCUMENT),
        registry,
    )
    assert incompressible.status == CompressionStatus.INCOMPRESSIBLE
    unknown_registry = TokenizerRegistry()
    with pytest.raises(UnknownTokenizerError):
        unknown_registry.resolve(tokenizer.identity)
    unknown = compress_source(
        request(source, ContentType.DOCUMENT, tokenizer, target_token_budget=10),
        source,
        unknown_registry,
    )
    assert unknown.status == CompressionStatus.FAILED
    assert unknown.failure is not None
    assert unknown.failure.code == "UNKNOWN_TOKENIZER"


def test_source_map_validation_and_report_are_deterministic(
    tokenizer: FixtureTokenizer,
    registry: TokenizerRegistry,
) -> None:
    source = source_from_fixture("simple_records.json", ContentType.JSON)
    result = compress_source(
        request(source, ContentType.JSON, tokenizer, target_token_budget=250),
        source,
        registry,
    )
    assert result.source_map is not None
    validation = validate_source_map(result.source_map)
    assert validation.valid
    assert any(
        mapping.exactness == "semantic_lineage_only" for mapping in result.source_map.mappings
    )
    assert result.compressed_text is not None
    extraction = extract_obligations(source, ContentType.JSON)
    artifact_bytes: dict[str, bytes] = {}
    for artifact in result.source_map.artifacts:
        if artifact.stage.value == "original":
            artifact_bytes[artifact.artifact_id] = source.raw_bytes
        elif artifact.stage.value == "normalized":
            artifact_bytes[artifact.artifact_id] = extraction.normalized_sources[0].normalized_bytes
        else:
            artifact_bytes[artifact.artifact_id] = result.compressed_text.encode("utf-8")
    assert validate_source_map(result.source_map, artifacts=artifact_bytes).valid

    stale_source = dict(artifact_bytes)
    original_id = next(
        artifact.artifact_id
        for artifact in result.source_map.artifacts
        if artifact.stage.value == "original"
    )
    stale_source[original_id] += b" "
    stale_source_validation = validate_source_map(result.source_map, artifacts=stale_source)
    assert not stale_source_validation.valid
    assert stale_source_validation.stale

    stale_compressed = dict(artifact_bytes)
    compressed_id = next(
        artifact.artifact_id
        for artifact in result.source_map.artifacts
        if artifact.stage.value == "raw_compressed"
    )
    stale_compressed[compressed_id] += b" "
    stale_compressed_validation = validate_source_map(result.source_map, artifacts=stale_compressed)
    assert not stale_compressed_validation.valid
    assert stale_compressed_validation.stale

    repeated = compress_source(
        request(source, ContentType.JSON, tokenizer, target_token_budget=250),
        source,
        registry,
    )
    assert canonical_json_bytes(result.model_dump(mode="json")) == canonical_json_bytes(
        repeated.model_dump(mode="json")
    )
    assert build_report() == build_report()
