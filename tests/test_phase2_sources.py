from base64 import b64encode

import pytest

from tracefold.extractors import extract_obligations
from tracefold.schemas.phase2 import SourceArtifact
from tracefold.schemas.source import SourceInput
from tracefold.sources import (
    SourceCoordinateError,
    SourceCoordinateIndex,
    SourceNormalizationError,
    ingest_source,
    normalize_source,
    normalized_char_range_to_original,
    original_char_range_to_normalized,
)


def make_source(text: str | None = None, *, raw: bytes | None = None) -> SourceArtifact:
    return ingest_source(
        SourceInput(
            input_ordinal=0,
            kind="text",
            authority="user",
            media_type="text/plain",
            text=text,
            bytes_base64=None if raw is None else b64encode(raw).decode("ascii"),
        )
    )


def test_utf8_coordinates_count_scalars_not_bytes() -> None:
    source = make_source("Aé e\u0301 😀\r\nrepeat repeat\n")
    index = SourceCoordinateIndex(source.raw_bytes)
    start = index.text.index("😀")
    end = start + 1
    byte_start, byte_end, line_start, column_start, line_end, column_end = index.character_range(
        start, end
    )
    assert source.raw_bytes[byte_start:byte_end] == "😀".encode()
    assert (line_start, column_start, line_end, column_end) == (1, 7, 1, 8)
    assert index.line_count == 3
    with pytest.raises(SourceCoordinateError):
        index.byte_to_char(byte_start + 1)


def test_normalization_is_reversible_and_hash_bound() -> None:
    source = make_source(raw=b"\xef\xbb\xbfA\r\nB\rC\n")
    normalized = normalize_source(source)
    assert normalized.normalized_text == "A\nB\nC\n"
    assert {operation.rule_id for operation in normalized.operations} == {
        "remove_utf8_bom",
        "normalize_line_ending",
    }
    assert normalized.original_hash != normalized.normalized_hash
    assert normalized.original_to_normalized

    assert original_char_range_to_normalized(normalized, 1, 2) == (0, 1)
    assert normalized_char_range_to_original(normalized, 0, 1) == (1, 2)
    with pytest.raises(SourceCoordinateError):
        original_char_range_to_normalized(normalized, -1, 1)
    with pytest.raises(SourceCoordinateError):
        normalized_char_range_to_original(normalized, 0, 99)


def test_invalid_base64_and_invalid_utf8_fail_typed() -> None:
    with pytest.raises(SourceNormalizationError):
        ingest_source(
            SourceInput(
                input_ordinal=0,
                kind="text",
                authority="user",
                media_type="text/plain",
                text=None,
                bytes_base64="not-base64",
            )
        )
    source = make_source(raw=b"\xff")
    with pytest.raises(SourceNormalizationError):
        normalize_source(source)


def test_portable_paths_reject_absolute_and_parent_segments() -> None:
    with pytest.raises(ValueError):
        ingest_source(
            SourceInput(
                input_ordinal=0,
                kind="code",
                authority="user",
                media_type="text/x-python",
                text="x = 1",
                file_path="/tmp/x.py",
            )
        )
    with pytest.raises(ValueError):
        ingest_source(
            SourceInput(
                input_ordinal=0,
                kind="code",
                authority="user",
                media_type="text/x-python",
                text="x = 1",
                file_path="../x.py",
            )
        )


def test_unknown_content_has_unknown_coverage_not_false_completeness() -> None:
    source = ingest_source(
        SourceInput(
            input_ordinal=0,
            kind="opaque",
            authority="tool",
            media_type="application/octet-stream",
            bytes_base64=b64encode(b"opaque").decode("ascii"),
        )
    )
    result = extract_obligations(source)
    assert result.coverage.value == "unknown"
    assert result.failure is None
    assert result.warnings[0].code == "UNKNOWN_CONTENT_TYPE"
