import base64
import binascii
import hashlib
from bisect import bisect_right

from tracefold.hashing import sha256_domain
from tracefold.schemas.common import HashDomain
from tracefold.schemas.phase2 import (
    NormalizationOperation,
    NormalizedSource,
    OffsetMapping,
    SourceArtifact,
)
from tracefold.schemas.source import SourceInput


class SourceNormalizationError(ValueError):
    """Source bytes cannot be safely decoded or normalized."""


class SourceCoordinateError(ValueError):
    """A coordinate does not land on a valid UTF-8 or source boundary."""


def _validate_file_path(file_path: str | None) -> None:
    if file_path is None:
        return
    if not file_path or file_path.startswith("/") or "\\" in file_path:
        raise ValueError("file_path must be a non-empty relative POSIX path")
    parts = file_path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("file_path cannot contain empty, '.' or '..' segments")


def source_identity(raw: bytes, input_ordinal: int) -> str:
    if input_ordinal < 0:
        raise ValueError("input_ordinal must be non-negative")
    return f"src:{input_ordinal}:{hashlib.sha256(raw).hexdigest()[:16]}"


def ingest_source(source: SourceInput) -> SourceArtifact:
    _validate_file_path(source.file_path)
    if source.text is not None:
        try:
            raw = source.text.encode("utf-8", "strict")
        except UnicodeEncodeError as exc:
            raise SourceNormalizationError("source text contains invalid Unicode") from exc
    else:
        assert source.bytes_base64 is not None
        try:
            raw = base64.b64decode(source.bytes_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise SourceNormalizationError("bytes_base64 is not valid base64") from exc
    return SourceArtifact(
        source_id=source_identity(raw, source.input_ordinal),
        input_ordinal=source.input_ordinal,
        kind=source.kind,
        authority=source.authority,
        media_type=source.media_type,
        raw_bytes=raw,
        file_path=source.file_path,
        message_id=source.message_id,
        role=source.role,
    )


class SourceCoordinateIndex:
    """UTF-8 byte, Unicode scalar, and human line/column coordinate index."""

    def __init__(self, raw: bytes) -> None:
        try:
            self.text = raw.decode("utf-8", "strict")
        except UnicodeDecodeError as exc:
            raise SourceCoordinateError("source is not valid UTF-8") from exc
        self.raw = raw
        self._byte_offsets = [0]
        for char in self.text:
            self._byte_offsets.append(self._byte_offsets[-1] + len(char.encode("utf-8")))
        self._line_starts = [0]
        index = 0
        while index < len(self.text):
            char = self.text[index]
            if char == "\r":
                index += 2 if index + 1 < len(self.text) and self.text[index + 1] == "\n" else 1
                self._line_starts.append(index)
            elif char == "\n":
                index += 1
                self._line_starts.append(index)
            else:
                index += 1

    @property
    def char_length(self) -> int:
        return len(self.text)

    @property
    def byte_length(self) -> int:
        return len(self.raw)

    @property
    def line_count(self) -> int:
        return 0 if not self.text else len(self._line_starts)

    def char_to_byte(self, offset: int) -> int:
        if not 0 <= offset <= self.char_length:
            raise SourceCoordinateError("character offset out of bounds")
        return self._byte_offsets[offset]

    def byte_to_char(self, offset: int) -> int:
        if not 0 <= offset <= self.byte_length:
            raise SourceCoordinateError("byte offset out of bounds")
        index = bisect_right(self._byte_offsets, offset) - 1
        if self._byte_offsets[index] != offset:
            raise SourceCoordinateError("byte offset splits a UTF-8 scalar")
        return index

    def line_column(self, char_offset: int) -> tuple[int, int]:
        if not 0 <= char_offset <= self.char_length:
            raise SourceCoordinateError("character offset out of bounds")
        line_index = bisect_right(self._line_starts, char_offset) - 1
        return line_index + 1, char_offset - self._line_starts[line_index] + 1

    def character_range(self, start: int, end: int) -> tuple[int, int, int, int, int, int]:
        if start > end:
            raise SourceCoordinateError("reversed character range")
        byte_start = self.char_to_byte(start)
        byte_end = self.char_to_byte(end)
        line_start, column_start = self.line_column(start)
        line_end, column_end = self.line_column(end)
        return byte_start, byte_end, line_start, column_start, line_end, column_end

    def byte_range(self, start: int, end: int) -> tuple[int, int, int, int, int, int, int, int]:
        if start > end:
            raise SourceCoordinateError("reversed byte range")
        char_start = self.byte_to_char(start)
        char_end = self.byte_to_char(end)
        return (*self.character_range(char_start, char_end), char_start, char_end)


def _normalization_mapping(
    source: SourceArtifact,
) -> tuple[str, list[NormalizationOperation], list[OffsetMapping]]:
    try:
        original = source.raw_bytes.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise SourceNormalizationError("source is not valid UTF-8") from exc

    output: list[str] = []
    operations: list[NormalizationOperation] = []
    mappings: list[OffsetMapping] = []
    original_index = 0
    normalized_index = 0
    if original.startswith("\ufeff"):
        operations.append(
            NormalizationOperation(
                rule_id="remove_utf8_bom",
                original_char_start=0,
                original_char_end=1,
                normalized_char_start=0,
                normalized_char_end=0,
                exactness="none_deleted",
            )
        )
        mappings.append(
            OffsetMapping(
                original_char_start=0,
                original_char_end=1,
                normalized_char_start=0,
                normalized_char_end=0,
                transform="delete_normalization_marker",
            )
        )
        original_index = 1

    while original_index < len(original):
        char = original[original_index]
        if char == "\r":
            original_end = original_index + (
                2
                if original_index + 1 < len(original) and original[original_index + 1] == "\n"
                else 1
            )
            output.append("\n")
            operations.append(
                NormalizationOperation(
                    rule_id="normalize_line_ending",
                    original_char_start=original_index,
                    original_char_end=original_end,
                    normalized_char_start=normalized_index,
                    normalized_char_end=normalized_index + 1,
                    exactness="character_equivalent",
                )
            )
            mappings.append(
                OffsetMapping(
                    original_char_start=original_index,
                    original_char_end=original_end,
                    normalized_char_start=normalized_index,
                    normalized_char_end=normalized_index + 1,
                    transform="normalize_line_ending",
                )
            )
            original_index = original_end
            normalized_index += 1
            continue

        output.append(char)
        mappings.append(
            OffsetMapping(
                original_char_start=original_index,
                original_char_end=original_index + 1,
                normalized_char_start=normalized_index,
                normalized_char_end=normalized_index + 1,
                transform="exact_copy",
            )
        )
        original_index += 1
        normalized_index += 1

    return "".join(output), operations, mappings


def normalize_source(source: SourceArtifact) -> NormalizedSource:
    normalized_text, operations, mappings = _normalization_mapping(source)
    normalized_bytes = normalized_text.encode("utf-8", "strict")
    original_hash = sha256_domain(HashDomain.SOURCE_ARTIFACT, source.raw_bytes)
    normalized_hash = sha256_domain(HashDomain.NORMALIZED_ARTIFACT, normalized_bytes)
    return NormalizedSource(
        source=source,
        normalized_text=normalized_text,
        normalized_bytes=normalized_bytes,
        original_hash=original_hash,
        normalized_hash=normalized_hash,
        operations=operations,
        original_to_normalized=mappings,
        normalized_to_original=[
            OffsetMapping(
                original_char_start=item.original_char_start,
                original_char_end=item.original_char_end,
                normalized_char_start=item.normalized_char_start,
                normalized_char_end=item.normalized_char_end,
                transform=item.transform,
            )
            for item in mappings
        ],
    )


def original_char_range_to_normalized(
    normalized: NormalizedSource, start: int, end: int
) -> tuple[int, int]:
    original_length = len(normalized.source.raw_bytes.decode("utf-8", "strict"))
    if not 0 <= start <= end <= original_length:
        raise SourceCoordinateError("original range out of bounds")
    selected = [
        item
        for item in normalized.original_to_normalized
        if item.original_char_end > start and item.original_char_start < end
    ]
    if selected:
        return min(item.normalized_char_start for item in selected), max(
            item.normalized_char_end for item in selected
        )
    if start == end:
        candidates = [
            item.normalized_char_start
            for item in normalized.original_to_normalized
            if item.original_char_start >= start
        ]
        point = min(candidates, default=len(normalized.normalized_text))
        return point, point
    raise SourceCoordinateError("original range has no normalized mapping")


def normalized_char_range_to_original(
    normalized: NormalizedSource, start: int, end: int
) -> tuple[int, int]:
    if not 0 <= start <= end <= len(normalized.normalized_text):
        raise SourceCoordinateError("normalized range out of bounds")
    selected = [
        item
        for item in normalized.normalized_to_original
        if item.normalized_char_end > start and item.normalized_char_start < end
    ]
    if selected:
        return min(item.original_char_start for item in selected), max(
            item.original_char_end for item in selected
        )
    if start == end:
        original_text = normalized.source.raw_bytes.decode("utf-8", "strict")
        candidates = [
            item.original_char_start
            for item in normalized.normalized_to_original
            if item.normalized_char_start >= start
        ]
        point = min(candidates, default=len(original_text))
        return point, point
    raise SourceCoordinateError("normalized range has no original mapping")


__all__ = [
    "SourceCoordinateError",
    "SourceCoordinateIndex",
    "SourceNormalizationError",
    "ingest_source",
    "normalize_source",
    "normalized_char_range_to_original",
    "original_char_range_to_normalized",
    "source_identity",
]
