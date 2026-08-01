import hashlib
from collections.abc import Mapping
from typing import Any, Literal

from tracefold.hashing import sha256_domain
from tracefold.schemas.common import DiscoveryStatus, HashDomain
from tracefold.schemas.phase2 import (
    ExtractionConfidence,
    Obligation,
    SourceArtifact,
)
from tracefold.schemas.source_map import SourceSpan
from tracefold.serialization import canonical_json_bytes
from tracefold.sources import SourceCoordinateIndex

SpanKind = Literal[
    "text",
    "boundary",
    "json_value",
    "json_key",
    "json_container",
    "log_event",
    "code_node",
    "dialogue_turn",
    "tombstone",
    "synthesized",
]


def _stable_digest(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def obligation_id(
    class_name: str,
    value: object,
    source_span_ids: list[str],
) -> str:
    digest = _stable_digest(
        {"class_name": class_name, "value": value, "source_span_ids": source_span_ids}
    )
    return f"obl:{class_name}:{digest[:16]}"


def make_source_span(
    source: SourceArtifact,
    start_char: int,
    end_char: int,
    *,
    kind: SpanKind = "text",
    json_path: str | None = None,
    code_symbol_id: str | None = None,
    log_event_id: str | None = None,
    conversation_message_id: str | None = None,
    role: str | None = None,
    structured_identity: Mapping[str, Any] | None = None,
) -> SourceSpan:
    index = SourceCoordinateIndex(source.raw_bytes)
    byte_start, byte_end, line_start, column_start, line_end, column_end = index.character_range(
        start_char, end_char
    )
    raw_span = source.raw_bytes[byte_start:byte_end]
    artifact_id = f"artifact:original:{source.source_id}"
    span_digest = hashlib.sha256(raw_span).hexdigest()[:16]
    span_id = f"span:{artifact_id}:{byte_start}:{byte_end}:{kind}:{span_digest}"
    return SourceSpan(
        span_id=span_id,
        artifact_id=artifact_id,
        kind=kind,
        byte_start=byte_start,
        byte_end=byte_end,
        char_start=start_char,
        char_end=end_char,
        line_start=line_start,
        column_start=column_start,
        line_end=line_end,
        column_end=column_end,
        span_hash=sha256_domain(HashDomain.SPAN, raw_span),
        json_path=json_path,
        file_path=source.file_path,
        code_symbol_id=code_symbol_id,
        log_event_id=log_event_id,
        conversation_message_id=conversation_message_id or source.message_id,
        role=role or source.role,
        structured_identity=dict(structured_identity) if structured_identity is not None else None,
    )


class SpanCollector:
    def __init__(self, source: SourceArtifact) -> None:
        self.source = source
        self._spans: dict[str, SourceSpan] = {}

    def add(self, start_char: int, end_char: int, **kwargs: Any) -> SourceSpan:
        span = make_source_span(self.source, start_char, end_char, **kwargs)
        self._spans[span.span_id] = span
        return span

    def values(self) -> list[SourceSpan]:
        return list(self._spans.values())


def make_obligation(
    *,
    class_name: str,
    value: object,
    source: SourceArtifact,
    spans: list[SourceSpan],
    extraction_method: str,
    confidence: ExtractionConfidence,
    discovery_status: DiscoveryStatus,
    lexeme: str | None = None,
    owner_spans: list[SourceSpan] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> Obligation:
    span_ids = [span.span_id for span in spans]
    return Obligation(
        obligation_id=obligation_id(class_name, value, span_ids),
        class_name=class_name,
        value=value,
        lexeme=lexeme,
        source_id=source.source_id,
        source_span_ids=span_ids,
        owner_span_ids=[span.span_id for span in owner_spans or []],
        extraction_method=extraction_method,
        confidence=confidence,
        discovery_status=discovery_status,
        metadata=dict(metadata or {}),
    )


__all__ = ["SpanCollector", "make_obligation", "make_source_span", "obligation_id"]
