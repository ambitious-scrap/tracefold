from __future__ import annotations

import ast
import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Literal, cast

from tracefold.extractors import extract_obligations
from tracefold.hashing import sha256_domain
from tracefold.obligations import make_source_span
from tracefold.schemas.common import ArtifactStage, HashDomain, HashValue
from tracefold.schemas.phase2 import (
    ContentType,
    ExtractionResult,
    Obligation,
    SourceArtifact,
)
from tracefold.schemas.phase3 import (
    CandidatePriority,
    CompilerStrategy,
    CompressionCandidate,
    CompressionFailure,
    CompressionStatus,
    CompressionWarning,
    CoverageCount,
    MandatorySet,
    OmittedSpan,
    RawCompressionRequest,
    RawCompressionResult,
    SelectionResult,
)
from tracefold.schemas.source_map import (
    ArtifactRecord,
    MapCoverage,
    MappingRecord,
    SourceMap,
    SourceSpan,
)
from tracefold.serialization import canonical_json_bytes, parse_json_strict
from tracefold.source_maps import SourceMapValidationError, build_source_map, validate_source_map
from tracefold.sources import (
    SourceCoordinateError,
    SourceCoordinateIndex,
    original_char_range_to_normalized,
)
from tracefold.tokenizers import Tokenizer, TokenizerRegistry, UnknownTokenizerError

COMPONENT_VERSION = "tracefold.compression/0.1.0"
SOURCE_MAP_COMPONENT_VERSION = "tracefold.source-map/phase3/0.1.0"
FIXED_CREATED_AT = datetime(2000, 1, 1, tzinfo=UTC)

_TIMESTAMP = re.compile(
    r"\b\d{4}-\d{2}-\d{2}[T ][0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.\d+)?(?:Z|[+-][0-9]{2}:?[0-9]{2})?\b"
)
_TRACE_FIELD = re.compile(r"\b(?:trace|trace_id|request|request_id|event_id)=[^\s]+")
_SEVERITY = re.compile(r"\b(?:TRACE|DEBUG|INFO|NOTICE|WARN|WARNING|ERROR|CRITICAL|FATAL)\b")


class CompressionInvariantError(ValueError):
    """Compressor-side raw artifact invariant failed."""


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _source_text(source: SourceArtifact) -> str:
    return source.raw_bytes.decode("utf-8", "strict")


def _line_ranges(text: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        end = offset + len(line)
        content_end = end
        while content_end > offset and text[content_end - 1] in "\r\n":
            content_end -= 1
        if content_end > offset:
            ranges.append((offset, content_end))
        offset = end
    if offset < len(text):
        ranges.append((offset, len(text)))
    return ranges


def _full_span(source: SourceArtifact, *, kind: Any = "text") -> SourceSpan:
    text = _source_text(source)
    return make_source_span(source, 0, len(text), kind=kind)


def _normalized_span(
    original: SourceSpan,
    normalized_source: Any,
    start: int,
    end: int,
) -> SourceSpan:
    index = SourceCoordinateIndex(normalized_source.normalized_bytes)
    byte_start, byte_end, line_start, column_start, line_end, column_end = index.character_range(
        start, end
    )
    raw = normalized_source.normalized_bytes[byte_start:byte_end]
    artifact_id = f"artifact:normalized:{normalized_source.source.source_id}"
    digest = hashlib.sha256(raw).hexdigest()[:16]
    return SourceSpan(
        span_id=f"span:{artifact_id}:{byte_start}:{byte_end}:{original.kind}:{digest}",
        artifact_id=artifact_id,
        kind=original.kind,
        byte_start=byte_start,
        byte_end=byte_end,
        char_start=start,
        char_end=end,
        line_start=line_start,
        column_start=column_start,
        line_end=line_end,
        column_end=column_end,
        span_hash=sha256_domain(HashDomain.SPAN, raw),
        json_path=original.json_path,
        file_path=original.file_path,
        code_symbol_id=original.code_symbol_id,
        log_event_id=original.log_event_id,
        conversation_message_id=original.conversation_message_id,
        role=original.role,
        structured_identity=original.structured_identity,
    )


def _source_ranges(spans: Iterable[SourceSpan]) -> list[tuple[int, int]]:
    return [(span.char_start, span.char_end) for span in spans]


def _overlaps(left: tuple[int, int], right: tuple[int, int]) -> bool:
    return left[0] < right[1] and right[0] < left[1]


def _obligation_hard(item: Obligation) -> bool:
    if item.class_name == "structured.json_schema_path":
        return False
    if item.class_name == "structured.anomalous_row":
        return False
    if item.class_name == "log.severity_change":
        return "from" in item.metadata and "to" in item.metadata
    if item.class_name == "temporal.timestamp" and item.metadata.get("event_id"):
        return False
    if item.class_name == "entity.named" and item.confidence.value == "inferred":
        return False
    if item.class_name == "identifier.generic" and item.metadata.get("event_id"):
        field = item.metadata.get("field")
        return field in {"error_code", "code"} or item.metadata.get("kind") == "exception"
    if item.class_name == "code.definition":
        return item.metadata.get("kind") not in {"module", "use", "import_binding"}
    return True


def _hard_obligation_ids(extraction: ExtractionResult) -> set[str]:
    return {item.obligation_id for item in extraction.obligations if _obligation_hard(item)}


def _mandatory_relation_ids(extraction: ExtractionResult) -> set[str]:
    return {item.relation_id for item in extraction.relations}


def _covered_ids(
    extraction: ExtractionResult,
    source_spans: Sequence[SourceSpan],
) -> tuple[list[str], list[str]]:
    ranges = _source_ranges(source_spans)
    obligation_ids: list[str] = []
    for item in extraction.obligations:
        item_spans = [
            span
            for span in extraction.spans
            if span.span_id in {*item.source_span_ids, *item.owner_span_ids}
        ]
        if any(
            _overlaps(candidate_range, span_range)
            for candidate_range in ranges
            for span_range in _source_ranges(item_spans)
        ):
            obligation_ids.append(item.obligation_id)
    relation_ids: list[str] = []
    for relation in extraction.relations:
        evidence = [span for span in extraction.spans if span.span_id in relation.evidence_span_ids]
        if any(
            _overlaps(candidate_range, span_range)
            for candidate_range in ranges
            for span_range in _source_ranges(evidence)
        ):
            relation_ids.append(relation.relation_id)
    return obligation_ids, relation_ids


def _candidate_id(
    source_id: str,
    kind: str,
    text: str,
    original_spans: Sequence[SourceSpan],
    compiler_rule: str,
) -> str:
    value = {
        "source_id": source_id,
        "kind": kind,
        "text": text,
        "original_span_ids": [span.span_id for span in original_spans],
        "compiler_rule": compiler_rule,
    }
    return f"cand:{kind}:{_digest(value)[:16]}"


def _make_candidate(
    source: SourceArtifact,
    extraction: ExtractionResult,
    tokenizer: Tokenizer,
    *,
    kind: str,
    text: str,
    original_spans: Sequence[SourceSpan],
    compiler_rule: str,
    mandatory: bool | None = None,
    structural: bool = False,
    obligation_ids: Sequence[str] | None = None,
    relation_ids: Sequence[str] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> CompressionCandidate:
    if not text:
        raise ValueError("candidate text cannot be empty")
    normalized_source = next(
        item for item in extraction.normalized_sources if item.source.source_id == source.source_id
    )
    original = list(original_spans)
    normalized: list[SourceSpan] = []
    for span in original:
        start, end = original_char_range_to_normalized(
            normalized_source, span.char_start, span.char_end
        )
        normalized.append(_normalized_span(span, normalized_source, start, end))
    covered_obligations, covered_relations = _covered_ids(extraction, original)
    if obligation_ids is not None:
        covered_obligations = list(dict.fromkeys(obligation_ids))
    if relation_ids is not None:
        covered_relations = list(dict.fromkeys(relation_ids))
    hard_ids = _hard_obligation_ids(extraction)
    is_mandatory = mandatory
    if is_mandatory is None:
        is_mandatory = bool(
            hard_ids.intersection(covered_obligations)
            or _mandatory_relation_ids(extraction).intersection(covered_relations)
        )
    candidate_id = _candidate_id(source.source_id, kind, text, original, compiler_rule)
    start = min((span.byte_start for span in original), default=0)
    end = max((span.byte_end for span in original), default=start)
    tie_break_key = f"{start:012d}:{end:012d}:{kind}:{candidate_id}"
    priority = (
        CandidatePriority.MANDATORY
        if is_mandatory
        else (CandidatePriority.STRUCTURAL if structural else CandidatePriority.OPTIONAL)
    )
    return CompressionCandidate(
        candidate_id=candidate_id,
        source_id=source.source_id,
        candidate_kind=kind,
        emitted_text=text,
        token_cost=tokenizer.count(text),
        priority_class=priority,
        original_source_spans=original,
        normalized_source_spans=normalized,
        obligation_ids=covered_obligations,
        relation_ids=covered_relations,
        mandatory=bool(is_mandatory),
        compiler_rule=compiler_rule,
        tie_break_key=tie_break_key,
        metadata=dict(metadata or {}),
    )


def _candidate_sort_key(candidate: CompressionCandidate) -> tuple[str, str]:
    return candidate.tie_break_key, candidate.candidate_id


def _render_candidates(candidates: Sequence[CompressionCandidate]) -> str:
    ordered = sorted(candidates, key=_candidate_sort_key)
    return "\n".join(candidate.emitted_text for candidate in ordered)


def _candidate_for_full_source(
    source: SourceArtifact,
    extraction: ExtractionResult,
    tokenizer: Tokenizer,
) -> CompressionCandidate:
    full = _full_span(source)
    return _make_candidate(
        source,
        extraction,
        tokenizer,
        kind="source_full",
        text=_source_text(source),
        original_spans=[full],
        compiler_rule="identity",
        mandatory=True,
        obligation_ids=[item.obligation_id for item in extraction.obligations],
        relation_ids=[item.relation_id for item in extraction.relations],
    )


def _group_marker_text(prefix: str, count: int) -> str:
    return f"[{prefix} repeated {count} times]"


def compile_document(
    source: SourceArtifact,
    extraction: ExtractionResult,
    tokenizer: Tokenizer,
) -> tuple[CompressionCandidate, ...]:
    text = _source_text(source)
    line_spans = [make_source_span(source, start, end) for start, end in _line_ranges(text)]
    candidates: list[CompressionCandidate] = []
    if source.role:
        candidates.append(
            _make_candidate(
                source,
                extraction,
                tokenizer,
                kind="dialogue_role_boundary",
                text=f"[role={source.role}]",
                original_spans=[_full_span(source, kind="boundary")],
                compiler_rule="dialogue-role-marker",
                mandatory=True,
                structural=True,
                obligation_ids=[],
                relation_ids=[],
                metadata={"synthesized": True, "role": source.role},
            )
        )
    by_text: dict[str, list[SourceSpan]] = defaultdict(list)
    for span in line_spans:
        by_text[text[span.char_start : span.char_end]].append(span)
    for group in sorted(by_text.values(), key=lambda items: items[0].char_start):
        if len(group) == 1:
            candidates.append(
                _make_candidate(
                    source,
                    extraction,
                    tokenizer,
                    kind="document_segment",
                    text=text[group[0].char_start : group[0].char_end],
                    original_spans=group,
                    compiler_rule="line-segment",
                    mandatory=True,
                )
            )
            continue
        candidates.append(
            _make_candidate(
                source,
                extraction,
                tokenizer,
                kind="document_segment",
                text=text[group[0].char_start : group[0].char_end],
                original_spans=[group[0]],
                compiler_rule="duplicate-first",
                mandatory=True,
                metadata={"occurrence": 1, "occurrences": len(group)},
            )
        )
        if len(group) > 2:
            middle = group[1:-1]
            candidates.append(
                _make_candidate(
                    source,
                    extraction,
                    tokenizer,
                    kind="repetition_marker",
                    text=_group_marker_text("TraceFold", len(group)),
                    original_spans=middle,
                    compiler_rule="exact-duplicate-marker",
                    mandatory=True,
                    structural=True,
                    obligation_ids=[],
                    relation_ids=[],
                    metadata={"synthesized": True, "occurrences": len(group)},
                )
            )
        candidates.append(
            _make_candidate(
                source,
                extraction,
                tokenizer,
                kind="document_segment",
                text=text[group[-1].char_start : group[-1].char_end],
                original_spans=[group[-1]],
                compiler_rule="duplicate-last",
                mandatory=True,
                metadata={"occurrence": len(group), "occurrences": len(group)},
            )
        )
    return tuple(sorted(candidates, key=_candidate_sort_key))


def _json_span_for_path(extraction: ExtractionResult, path: str) -> SourceSpan | None:
    choices = [
        span
        for span in extraction.spans
        if span.json_path == path and span.kind in {"json_container", "json_value"}
    ]
    return max(
        choices, key=lambda span: (span.char_end - span.char_start, -span.char_start), default=None
    )


def _json_scalar_type(value: object) -> type[object] | None:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return object
    return type(value)


def _json_compact(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _json_cell(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        return encoded[1:-1]
    return _json_compact(value)


def _json_type_name(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    return "json"


def compile_json(
    source: SourceArtifact,
    extraction: ExtractionResult,
    tokenizer: Tokenizer,
) -> tuple[CompressionCandidate, ...]:
    text = _source_text(source)
    value = parse_json_strict(text[1:] if text.startswith("\ufeff") else text)
    full = _full_span(source, kind="json_container")
    if (
        not isinstance(value, list)
        or len(value) < 2
        or not all(isinstance(row, dict) for row in value)
    ):
        return (
            _make_candidate(
                source,
                extraction,
                tokenizer,
                kind="json_compact",
                text=_json_compact(value),
                original_spans=[full],
                compiler_rule="json-compact",
                mandatory=True,
                structural=True,
                obligation_ids=[item.obligation_id for item in extraction.obligations],
                relation_ids=[item.relation_id for item in extraction.relations],
                metadata={"synthesized": True, "structurally_equivalent": True},
            ),
        )
    rows = [dict(row) for row in value]
    keys: list[str] = list(rows[0])
    for row in rows[1:]:
        for key in row:
            if key not in keys:
                keys.append(key)
    uniform = True
    field_types: dict[str, type[object] | None] = {}
    for row in rows:
        for key, cell in row.items():
            cell_type = _json_scalar_type(cell)
            if cell_type is object:
                uniform = False
            previous = field_types.get(key)
            if cell_type is not None and previous is not None and cell_type is not previous:
                uniform = False
            if cell_type is not None:
                field_types[key] = cell_type
    row_spans = [_json_span_for_path(extraction, f"/{index}") for index in range(len(rows))]
    if not uniform or any(span is None for span in row_spans):
        return (
            _make_candidate(
                source,
                extraction,
                tokenizer,
                kind="json_compact",
                text=_json_compact(value),
                original_spans=[full],
                compiler_rule="json-compact",
                mandatory=True,
                structural=True,
                obligation_ids=[item.obligation_id for item in extraction.obligations],
                relation_ids=[item.relation_id for item in extraction.relations],
                metadata={"synthesized": True, "structurally_equivalent": True},
            ),
        )
    type_names = []
    for key in keys:
        sample = next(
            (row[key] for row in rows if key in row and row[key] is not None),
            None,
        )
        type_names.append(_json_type_name(sample))
    header = _make_candidate(
        source,
        extraction,
        tokenizer,
        kind="json_schema",
        text=(
            f"@schema={_json_compact(keys)}\n@types={_json_compact(type_names)}\n@rows={len(rows)}"
        ),
        original_spans=[full],
        compiler_rule="json-schema-factored",
        mandatory=True,
        structural=True,
        obligation_ids=[],
        relation_ids=[],
        metadata={"synthesized": True, "row_count": len(rows), "keys": keys},
    )
    candidates: list[CompressionCandidate] = [header]
    for index, row in enumerate(rows):
        row_span = row_spans[index]
        assert row_span is not None
        present = {key: row[key] for key in keys if key in row}
        missing = [key for key in keys if key not in row]
        cells = [_json_cell(present[key]) if key in present else "~" for key in keys]
        encoded_cells = "\t".join(cells)
        row_text = f"@row\t{encoded_cells}\tmissing={_json_compact(missing)}"
        row_status = row.get("status")
        row_mandatory = isinstance(row_status, str) and row_status.lower() in {
            "error",
            "failed",
            "failure",
            "critical",
            "fatal",
        }
        candidates.append(
            _make_candidate(
                source,
                extraction,
                tokenizer,
                kind="json_row",
                text=row_text,
                original_spans=[row_span],
                compiler_rule="json-schema-row",
                mandatory=True if row_mandatory else None,
                metadata={"row_index": index, "json_path": f"/{index}"},
            )
        )
    return tuple(sorted(candidates, key=_candidate_sort_key))


def _log_template(text: str) -> str:
    result = _TIMESTAMP.sub("<timestamp>", text)
    return _TRACE_FIELD.sub(lambda match: match.group(0).split("=", 1)[0] + "=<id>", result)


def _event_spans(extraction: ExtractionResult) -> list[SourceSpan]:
    spans: dict[str, SourceSpan] = {}
    for span in extraction.spans:
        if span.kind == "log_event" and span.log_event_id is not None:
            spans.setdefault(span.log_event_id, span)
    return sorted(spans.values(), key=lambda span: (span.char_start, span.char_end, span.span_id))


def _with_mandatory(candidate: CompressionCandidate) -> CompressionCandidate:
    return candidate.model_copy(
        update={"mandatory": True, "priority_class": CandidatePriority.MANDATORY}
    )


def compile_logs(
    source: SourceArtifact,
    extraction: ExtractionResult,
    tokenizer: Tokenizer,
) -> tuple[CompressionCandidate, ...]:
    text = _source_text(source)
    events = _event_spans(extraction)
    hard_ids = _hard_obligation_ids(extraction)
    base: list[tuple[SourceSpan, CompressionCandidate, str]] = []
    for span in events:
        event_text = text[span.char_start : span.char_end]
        candidate = _make_candidate(
            source,
            extraction,
            tokenizer,
            kind="log_event",
            text=event_text,
            original_spans=[span],
            compiler_rule="log-event-line",
            mandatory=None,
            metadata={"event_id": span.log_event_id},
        )
        if not hard_ids.intersection(candidate.obligation_ids):
            candidate = candidate.model_copy(
                update={
                    "mandatory": False,
                    "priority_class": CandidatePriority.OPTIONAL,
                }
            )
        base.append((span, candidate, _log_template(event_text)))
    candidates: list[CompressionCandidate] = []
    index = 0
    while index < len(base):
        span, candidate, template = base[index]
        end = index + 1
        while (
            end < len(base)
            and base[end][2] == template
            and base[end][1].mandatory == candidate.mandatory
        ):
            end += 1
        run = base[index:end]
        if len(run) > 2 and all(not item[1].mandatory for item in run):
            first = _with_mandatory(run[0][1])
            last = _with_mandatory(run[-1][1])
            candidates.append(first)
            middle_spans = [item[0] for item in run[1:-1]]
            timestamps = [
                _TIMESTAMP.search(text[span.char_start : span.char_end]) for span in middle_spans
            ]
            first_timestamp = _TIMESTAMP.search(text[run[0][0].char_start : run[0][0].char_end])
            last_timestamp = _TIMESTAMP.search(text[run[-1][0].char_start : run[-1][0].char_end])
            first_label = first_timestamp.group(0).split("T", 1)[-1] if first_timestamp else "-"
            last_label = last_timestamp.group(0).split("T", 1)[-1] if last_timestamp else "-"
            marker_text = f"[TraceFold logs x{len(run)} {first_label}..{last_label}]"
            candidates.append(
                _make_candidate(
                    source,
                    extraction,
                    tokenizer,
                    kind="log_group_marker",
                    text=marker_text,
                    original_spans=middle_spans,
                    compiler_rule="log-template-group",
                    mandatory=True,
                    structural=True,
                    obligation_ids=[],
                    relation_ids=list(
                        dict.fromkeys(
                            relation_id
                            for _, grouped_candidate, _ in run[1:-1]
                            for relation_id in grouped_candidate.relation_ids
                        )
                    ),
                    metadata={
                        "synthesized": True,
                        "template": template,
                        "count": len(run),
                        "timestamp_count": len(timestamps),
                        "first_timestamp": first_timestamp.group(0) if first_timestamp else None,
                        "last_timestamp": last_timestamp.group(0) if last_timestamp else None,
                    },
                )
            )
            candidates.append(last)
        else:
            candidates.extend(_with_mandatory(item[1]) for item in run)
        index = end
    return tuple(sorted(candidates, key=_candidate_sort_key))


def _python_line_starts(text: str) -> list[int]:
    starts = [0]
    for match in re.finditer(r"\r\n|\r|\n", text):
        starts.append(match.end())
    return starts


def _python_node_range(
    node: ast.AST,
    text: str,
    index: SourceCoordinateIndex,
    line_starts: Sequence[int],
) -> tuple[int, int] | None:
    values = tuple(
        getattr(node, name, None)
        for name in ("lineno", "end_lineno", "col_offset", "end_col_offset")
    )
    if not all(isinstance(value, int) for value in values):
        return None
    lineno, end_lineno, col_offset, end_col_offset = values
    assert isinstance(lineno, int)
    assert isinstance(end_lineno, int)
    assert isinstance(col_offset, int)
    assert isinstance(end_col_offset, int)
    if lineno < 1 or end_lineno > len(line_starts):
        return None
    try:
        start = index.byte_to_char(index.char_to_byte(line_starts[lineno - 1]) + col_offset)
        end = index.byte_to_char(index.char_to_byte(line_starts[end_lineno - 1]) + end_col_offset)
    except SourceCoordinateError:
        return None
    if start > end or end > len(text):
        return None
    return start, end


def _python_header_range(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
    text: str,
    line_starts: Sequence[int],
) -> tuple[int, int] | None:
    decorator_lines = [getattr(item, "lineno", node.lineno) for item in node.decorator_list]
    start_line = min([node.lineno, *decorator_lines])
    if node.body and getattr(node.body[0], "lineno", node.lineno) > node.lineno:
        end = line_starts[node.body[0].lineno - 1]
    else:
        end_line = getattr(node, "end_lineno", node.lineno)
        end = line_starts[end_line - 1] + len(text[line_starts[end_line - 1] :].splitlines()[0])
    start = line_starts[start_line - 1]
    while end > start and text[end - 1] in "\r\n":
        end -= 1
    return (start, end) if start < end else None


def _python_body_range(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
    text: str,
    index: SourceCoordinateIndex,
    line_starts: Sequence[int],
) -> tuple[int, int] | None:
    if not node.body:
        return None
    first = _python_node_range(node.body[0], text, index, line_starts)
    last = _python_node_range(node.body[-1], text, index, line_starts)
    if first is None or last is None:
        return None
    return first[0], last[1]


def _python_definition_ids(
    extraction: ExtractionResult,
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
) -> list[str]:
    ids: list[str] = []
    for item in extraction.obligations:
        if item.class_name != "code.definition":
            continue
        if item.metadata.get("name") == node.name or item.metadata.get(
            "qualified_name", ""
        ).endswith(f".{node.name}"):
            ids.append(item.obligation_id)
    return ids


def _python_marker(
    source: SourceArtifact,
    extraction: ExtractionResult,
    tokenizer: Tokenizer,
    *,
    start: int,
    end: int,
) -> CompressionCandidate:
    span = make_source_span(source, start, end, kind="code_node")
    source_text = _source_text(source)
    line_start = source_text[:start].count("\n") + 1
    line_end = source_text[:end].count("\n") + 1
    line_prefix = source_text[source_text.rfind("\n", 0, start) + 1 : start]
    indent_match = re.match(r"[ \t]*", line_prefix)
    indent = indent_match.group(0) if indent_match is not None else ""
    marker = f"{indent}# TraceFold omitted {line_start}-{line_end}\n{indent}pass"
    return _make_candidate(
        source,
        extraction,
        tokenizer,
        kind="python_omission_marker",
        text=marker,
        original_spans=[span],
        compiler_rule="python-body-omission",
        mandatory=True,
        structural=True,
        obligation_ids=[],
        relation_ids=[],
        metadata={
            "synthesized": True,
            "line_start": line_start,
            "line_end": line_end,
        },
    )


def compile_python(
    source: SourceArtifact,
    extraction: ExtractionResult,
    tokenizer: Tokenizer,
) -> tuple[CompressionCandidate, ...]:
    text = _source_text(source)
    tree = ast.parse(text, filename=source.file_path or "<tracefold>")
    index = SourceCoordinateIndex(source.raw_bytes)
    line_starts = _python_line_starts(text)
    candidates: list[CompressionCandidate] = []
    occupied: list[tuple[int, int]] = []

    definitions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    for node in sorted(definitions, key=lambda item: (item.lineno, getattr(item, "col_offset", 0))):
        header_range = _python_header_range(node, text, line_starts)
        if header_range is not None:
            header_span = make_source_span(
                source, header_range[0], header_range[1], kind="code_node"
            )
            definition_ids = _python_definition_ids(extraction, node)
            header_obligation_ids, header_relation_ids = _covered_ids(extraction, [header_span])
            header_obligation_ids = list(dict.fromkeys([*definition_ids, *header_obligation_ids]))
            header_obligation_ids = [
                obligation_id
                for obligation_id in header_obligation_ids
                if next(
                    item for item in extraction.obligations if item.obligation_id == obligation_id
                ).metadata.get("kind")
                not in {"module", "use", "import_binding"}
            ]
            candidates.append(
                _make_candidate(
                    source,
                    extraction,
                    tokenizer,
                    kind="python_signature",
                    text=text[header_range[0] : header_range[1]],
                    original_spans=[header_span],
                    compiler_rule="python-signature",
                    mandatory=True,
                    obligation_ids=header_obligation_ids,
                    relation_ids=header_relation_ids,
                )
            )
            occupied.append(header_range)
        body_range = _python_body_range(node, text, index, line_starts)
        if body_range is not None:
            complex_body = any(
                isinstance(
                    statement,
                    (
                        ast.If,
                        ast.For,
                        ast.While,
                        ast.Try,
                        ast.With,
                        ast.Match,
                        ast.AsyncFor,
                        ast.AsyncWith,
                    ),
                )
                for statement in node.body
            )
            body_start = line_starts[node.body[0].lineno - 1]
            body_span = make_source_span(source, body_start, body_range[1], kind="code_node")
            if complex_body:
                body_obligations, body_relations = _covered_ids(extraction, [body_span])
                candidates.append(
                    _make_candidate(
                        source,
                        extraction,
                        tokenizer,
                        kind="python_body",
                        text=text[body_start : body_range[1]],
                        original_spans=[body_span],
                        compiler_rule="python-structured-body",
                        mandatory=True,
                        obligation_ids=body_obligations,
                        relation_ids=body_relations,
                    )
                )
            else:
                protected_lines: list[CompressionCandidate] = []
                has_optional_lines = False
                for start, end in _line_ranges(text):
                    if end <= body_range[0] or start >= body_range[1]:
                        continue
                    line_span = make_source_span(source, start, end, kind="code_node")
                    obligation_ids, relation_ids = _covered_ids(extraction, [line_span])
                    obligation_ids = [
                        obligation_id
                        for obligation_id in obligation_ids
                        if next(
                            item
                            for item in extraction.obligations
                            if item.obligation_id == obligation_id
                        ).metadata.get("kind")
                        not in {
                            "module",
                            "function",
                            "class",
                            "parameter",
                            "use",
                            "import_binding",
                        }
                    ]
                    if not obligation_ids and not relation_ids:
                        has_optional_lines = True
                        continue
                    protected_lines.append(
                        _make_candidate(
                            source,
                            extraction,
                            tokenizer,
                            kind="python_protected_line",
                            text=text[start:end],
                            original_spans=[line_span],
                            compiler_rule="python-protected-line",
                            mandatory=True,
                            obligation_ids=obligation_ids,
                            relation_ids=relation_ids,
                        )
                    )
                if has_optional_lines:
                    candidates.append(
                        _python_marker(
                            source,
                            extraction,
                            tokenizer,
                            start=body_range[0],
                            end=body_range[1],
                        )
                    )
                candidates.extend(protected_lines)
            occupied.append(body_range)
            if complex_body:
                continue

    for start, end in _line_ranges(text):
        if any(_overlaps((start, end), occupied) for occupied in occupied):
            continue
        line_span = make_source_span(source, start, end, kind="code_node")
        obligation_ids, relation_ids = _covered_ids(extraction, [line_span])
        if not obligation_ids and not relation_ids:
            continue
        candidates.append(
            _make_candidate(
                source,
                extraction,
                tokenizer,
                kind="python_protected_line",
                text=text[start:end],
                original_spans=[line_span],
                compiler_rule="python-protected-line",
                mandatory=True,
                obligation_ids=obligation_ids,
                relation_ids=relation_ids,
            )
        )
    return tuple(sorted(candidates, key=_candidate_sort_key))


def build_candidates(
    source: SourceArtifact,
    extraction: ExtractionResult,
    tokenizer: Tokenizer,
) -> tuple[CompressionCandidate, ...]:
    if extraction.content_type in {ContentType.DOCUMENT, ContentType.DIALOGUE}:
        return compile_document(source, extraction, tokenizer)
    if extraction.content_type == ContentType.JSON:
        return compile_json(source, extraction, tokenizer)
    if extraction.content_type == ContentType.LOG:
        return compile_logs(source, extraction, tokenizer)
    if extraction.content_type == ContentType.PYTHON:
        return compile_python(source, extraction, tokenizer)
    raise ValueError("unsupported Phase 3 content type")


def _token_count(candidates: Sequence[CompressionCandidate], tokenizer: Tokenizer) -> int:
    return tokenizer.count(_render_candidates(candidates))


def calculate_mandatory_set(
    candidates: Sequence[CompressionCandidate],
    tokenizer: Tokenizer,
) -> MandatorySet:
    ids = [candidate.candidate_id for candidate in candidates]
    if len(ids) != len(set(ids)):
        raise CompressionInvariantError("duplicate candidate IDs")
    mandatory = sorted(
        (candidate for candidate in candidates if candidate.mandatory), key=_candidate_sort_key
    )
    return MandatorySet(
        candidate_ids=[candidate.candidate_id for candidate in mandatory],
        obligation_ids=sorted(
            {item for candidate in mandatory for item in candidate.obligation_ids}
        ),
        relation_ids=sorted({item for candidate in mandatory for item in candidate.relation_ids}),
        minimum_token_count=_token_count(mandatory, tokenizer),
    )


def _selection_rank(candidate: CompressionCandidate) -> tuple[int, int, int, int, str, str]:
    priority = {
        CandidatePriority.MANDATORY: 0,
        CandidatePriority.STRUCTURAL: 1,
        CandidatePriority.OPTIONAL: 2,
    }[candidate.priority_class]
    anomaly = 0 if candidate.metadata.get("anomaly") else 1
    protected = 0 if candidate.obligation_ids or candidate.relation_ids else 1
    first = min((span.byte_start for span in candidate.original_source_spans), default=0)
    return priority, anomaly, protected, first, candidate.tie_break_key, candidate.candidate_id


def select_candidates(
    candidates: Sequence[CompressionCandidate],
    mandatory: MandatorySet,
    token_budget: int,
    tokenizer: Tokenizer,
) -> SelectionResult:
    if token_budget <= 0:
        raise ValueError("token budget must be positive")
    candidate_by_id = {candidate.candidate_id: candidate for candidate in candidates}
    if len(candidate_by_id) != len(candidates):
        raise CompressionInvariantError("duplicate candidate IDs")
    if not set(mandatory.candidate_ids).issubset(candidate_by_id):
        raise CompressionInvariantError("mandatory set references unknown candidate")
    selected = [candidate_by_id[item] for item in mandatory.candidate_ids]
    selected = sorted(selected, key=_candidate_sort_key)
    minimum = _token_count(selected, tokenizer)
    if minimum > token_budget:
        return SelectionResult(
            selected_candidate_ids=[candidate.candidate_id for candidate in selected],
            omitted_candidate_ids=[
                candidate.candidate_id for candidate in candidates if candidate not in selected
            ],
            token_count=minimum,
            minimum_token_count=minimum,
            fits_budget=False,
        )
    selected_ids = {candidate.candidate_id for candidate in selected}
    optional = sorted(
        (candidate for candidate in candidates if candidate.candidate_id not in selected_ids),
        key=_selection_rank,
    )
    for candidate in optional:
        proposed = [*selected, candidate]
        if _token_count(proposed, tokenizer) <= token_budget:
            selected.append(candidate)
            selected_ids.add(candidate.candidate_id)
    selected = sorted(selected, key=_candidate_sort_key)
    return SelectionResult(
        selected_candidate_ids=[candidate.candidate_id for candidate in selected],
        omitted_candidate_ids=[
            candidate.candidate_id
            for candidate in candidates
            if candidate.candidate_id not in selected_ids
        ],
        token_count=_token_count(selected, tokenizer),
        minimum_token_count=minimum,
        fits_budget=True,
    )


def _format_ranges(indices: Sequence[int]) -> str:
    if not indices:
        return ""
    ordered = sorted(set(indices))
    ranges: list[str] = []
    start = previous = ordered[0]
    for index in ordered[1:]:
        if index == previous + 1:
            previous = index
            continue
        ranges.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = index
    ranges.append(str(start) if start == previous else f"{start}-{previous}")
    return ",".join(ranges)


def _json_omission_marker(
    source: SourceArtifact,
    extraction: ExtractionResult,
    tokenizer: Tokenizer,
    omitted: Sequence[CompressionCandidate],
) -> CompressionCandidate | None:
    rows = [
        candidate
        for candidate in omitted
        if candidate.candidate_kind == "json_row" and "row_index" in candidate.metadata
    ]
    if not rows:
        return None
    indices = [int(candidate.metadata["row_index"]) for candidate in rows]
    spans = [span for candidate in rows for span in candidate.original_source_spans]
    return _make_candidate(
        source,
        extraction,
        tokenizer,
        kind="json_omission_marker",
        text=f"@omitted_rows={_format_ranges(indices)}",
        original_spans=spans,
        compiler_rule="json-omitted-row-ranges",
        mandatory=True,
        structural=True,
        obligation_ids=[],
        relation_ids=[],
        metadata={"synthesized": True, "omitted_row_indices": sorted(indices)},
    )


def _fit_selection(
    source: SourceArtifact,
    extraction: ExtractionResult,
    candidates: Sequence[CompressionCandidate],
    selection: SelectionResult,
    token_budget: int,
    tokenizer: Tokenizer,
) -> tuple[list[CompressionCandidate], list[CompressionCandidate], str, int, bool]:
    candidate_by_id = {candidate.candidate_id: candidate for candidate in candidates}
    selected = [candidate_by_id[item] for item in selection.selected_candidate_ids]
    selected_ids = {candidate.candidate_id for candidate in selected}
    while True:
        omitted = [
            candidate for candidate in candidates if candidate.candidate_id not in selected_ids
        ]
        marker = _json_omission_marker(source, extraction, tokenizer, omitted)
        rendered_candidates = [*selected, *([marker] if marker is not None else [])]
        rendered = _render_candidates(rendered_candidates)
        count = tokenizer.count(rendered)
        mandatory_candidates = [
            candidate for candidate in rendered_candidates if candidate.mandatory
        ]
        floor = _token_count(mandatory_candidates, tokenizer)
        if count <= token_budget:
            return rendered_candidates, omitted, rendered, floor, True
        optional = [candidate for candidate in selected if not candidate.mandatory]
        if not optional:
            return rendered_candidates, omitted, rendered, floor, False
        drop = sorted(optional, key=_selection_rank)[-1]
        selected.remove(drop)
        selected_ids.remove(drop.candidate_id)


def _omitted_spans(
    candidates: Sequence[CompressionCandidate],
    selected: Sequence[CompressionCandidate],
) -> list[OmittedSpan]:
    selected_ids = {candidate.candidate_id for candidate in selected}
    result: list[OmittedSpan] = []
    for candidate in sorted(candidates, key=_candidate_sort_key):
        if candidate.candidate_id in selected_ids:
            continue
        group_payload = {"candidate_id": candidate.candidate_id, "reason": candidate.compiler_rule}
        group = f"omit:{_digest(group_payload)[:16]}"
        for index, span in enumerate(candidate.original_source_spans):
            normalized_id = (
                candidate.normalized_source_spans[index].span_id
                if index < len(candidate.normalized_source_spans)
                else None
            )
            result.append(
                OmittedSpan(
                    source_id=candidate.source_id,
                    original_span_id=span.span_id,
                    normalized_span_id=normalized_id,
                    omission_reason=candidate.compiler_rule,
                    obligation_ids=candidate.obligation_ids,
                    relation_ids=candidate.relation_ids,
                    reversible_from_source_map=True,
                    omission_group_id=group,
                )
            )
    return result


def _coverage(
    extraction: ExtractionResult,
    selected: Sequence[CompressionCandidate],
) -> tuple[dict[str, CoverageCount], dict[str, CoverageCount]]:
    selected_obligations = {item for candidate in selected for item in candidate.obligation_ids}
    selected_relations = {item for candidate in selected for item in candidate.relation_ids}
    hard_ids = _hard_obligation_ids(extraction)
    obligation_counts: dict[str, CoverageCount] = {}
    for class_name in sorted({item.class_name for item in extraction.obligations}):
        obligation_items = [
            item for item in extraction.obligations if item.class_name == class_name
        ]
        obligation_counts[class_name] = CoverageCount(
            discovered=len(obligation_items),
            mandatory=sum(item.obligation_id in hard_ids for item in obligation_items),
            represented=sum(
                item.obligation_id in selected_obligations for item in obligation_items
            ),
        )
    relation_counts: dict[str, CoverageCount] = {}
    for relation_type in sorted({item.relation_type for item in extraction.relations}):
        relation_items = [
            item for item in extraction.relations if item.relation_type == relation_type
        ]
        relation_counts[relation_type] = CoverageCount(
            discovered=len(relation_items),
            mandatory=len(relation_items),
            represented=sum(item.relation_id in selected_relations for item in relation_items),
        )
    return obligation_counts, relation_counts


def _ratio(numerator: int, denominator: int) -> str | None:
    if denominator == 0:
        return None
    return f"{numerator / denominator:.6f}"


def _output_span(
    artifact_id: str,
    output: bytes,
    start: int,
    end: int,
    *,
    kind: Any,
    candidate: CompressionCandidate,
) -> SourceSpan:
    index = SourceCoordinateIndex(output)
    byte_start, byte_end, line_start, column_start, line_end, column_end = index.character_range(
        start, end
    )
    raw = output[byte_start:byte_end]
    digest = hashlib.sha256(raw).hexdigest()[:16]
    return SourceSpan(
        span_id=f"span:{artifact_id}:{byte_start}:{byte_end}:{kind}:{digest}",
        artifact_id=artifact_id,
        kind=kind,
        byte_start=byte_start,
        byte_end=byte_end,
        char_start=start,
        char_end=end,
        line_start=line_start,
        column_start=column_start,
        line_end=line_end,
        column_end=column_end,
        span_hash=sha256_domain(HashDomain.SPAN, raw),
        file_path=next(
            (
                span.file_path
                for span in candidate.original_source_spans
                if span.file_path is not None
            ),
            None,
        ),
        conversation_message_id=next(
            (
                span.conversation_message_id
                for span in candidate.original_source_spans
                if span.conversation_message_id is not None
            ),
            None,
        ),
        role=next((span.role for span in candidate.original_source_spans if span.role), None),
        structured_identity={
            "candidate_id": candidate.candidate_id,
            "compiler_rule": candidate.compiler_rule,
            "synthesized": bool(candidate.metadata.get("synthesized")),
        },
    )


def _mapping_indexes(
    mappings: Sequence[MappingRecord],
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    forward: dict[str, list[str]] = {}
    reverse: dict[str, list[str]] = {}
    for mapping in mappings:
        for span_id in mapping.from_span_ids:
            forward.setdefault(span_id, []).append(mapping.mapping_id)
        for span_id in mapping.to_span_ids:
            reverse.setdefault(span_id, []).append(mapping.mapping_id)
    return forward, reverse


def _raw_artifact(
    source: SourceArtifact,
    output: bytes,
    attempt_id: str,
) -> ArtifactRecord:
    index = SourceCoordinateIndex(output)
    return ArtifactRecord(
        artifact_id=f"artifact:raw_compressed:{attempt_id}",
        stage=ArtifactStage.RAW_COMPRESSED,
        source_id=None,
        attempt_id=attempt_id,
        media_type=source.media_type,
        encoding="utf-8",
        byte_length=index.byte_length,
        char_length=index.char_length,
        line_count=index.line_count,
        hash=sha256_domain(HashDomain.CONTEXT_ARTIFACT, output),
        file_path=source.file_path,
        message_id=source.message_id,
        role=source.role,
    )


def build_compressed_source_map(
    extraction: ExtractionResult,
    candidates: Sequence[CompressionCandidate],
    selected: Sequence[CompressionCandidate],
    omitted: Sequence[OmittedSpan],
    *,
    output_text: str,
    run_id: str,
    attempt_id: str,
    created_at: datetime = FIXED_CREATED_AT,
) -> SourceMap:
    if len(extraction.sources) != 1:
        raise SourceMapValidationError("Phase 3 compression requires one source")
    source = extraction.sources[0]
    base = build_source_map(
        extraction,
        run_id=run_id,
        attempt_id=attempt_id,
        created_at=created_at,
    )
    output = output_text.encode("utf-8", "strict")
    raw_artifact = _raw_artifact(source, output, attempt_id)
    artifacts = [*base.artifacts, raw_artifact]
    artifact_id = raw_artifact.artifact_id
    span_by_id = {span.span_id: span for span in base.spans}
    for candidate in candidates:
        for span in [*candidate.original_source_spans, *candidate.normalized_source_spans]:
            span_by_id.setdefault(span.span_id, span)
    mappings = list(base.mappings)
    output_spans: list[SourceSpan] = []
    ordered = sorted(selected, key=_candidate_sort_key)
    rendered = _render_candidates(ordered)
    if rendered != output_text:
        raise CompressionInvariantError("candidate rendering differs from output text")
    cursor = 0
    for ordinal, candidate in enumerate(ordered):
        if ordinal:
            cursor += 1
        start = cursor
        end = start + len(candidate.emitted_text)
        cursor = end
        synthesized = bool(candidate.metadata.get("synthesized"))
        kind = "synthesized" if synthesized else "text"
        output_span = _output_span(artifact_id, output, start, end, kind=kind, candidate=candidate)
        span_by_id[output_span.span_id] = output_span
        output_spans.append(output_span)
        from_ids = [span.span_id for span in candidate.original_source_spans]
        if not from_ids:
            raise CompressionInvariantError("emitted candidate has no source lineage")
        source_exact = False
        if len(from_ids) == 1 and not synthesized:
            original_span = candidate.original_source_spans[0]
            source_exact = (
                source.raw_bytes[original_span.byte_start : original_span.byte_end]
                == output[output_span.byte_start : output_span.byte_end]
            )
        if source_exact:
            transform = "exact_copy"
            exactness = "byte_exact"
        elif candidate.metadata.get("structurally_equivalent"):
            transform = "aggregate"
            exactness = "structurally_equivalent"
        else:
            transform = "synthesize_summary"
            exactness = "semantic_lineage_only"
        ordering = "many_to_one" if len(from_ids) > 1 else "preserved"
        mapping_id = (
            f"map:{transform}:{_digest({'from': from_ids, 'to': [output_span.span_id]})[:16]}"
        )
        mappings.append(
            MappingRecord(
                mapping_id=mapping_id,
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
                from_span_ids=from_ids,
                to_span_ids=[output_span.span_id],
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
                ordering=cast(
                    Literal[
                        "preserved",
                        "declared_reordered",
                        "many_to_one",
                        "one_to_many",
                        "not_applicable",
                    ],
                    ordering,
                ),
                reason_code=candidate.compiler_rule,
                obligation_ids=candidate.obligation_ids,
                relation_ids=candidate.relation_ids,
                transform_component="tracefold.compression",
                transform_version=COMPONENT_VERSION,
                metadata={"candidate_id": candidate.candidate_id, **candidate.metadata},
            )
        )
    candidate_by_id = {candidate.candidate_id: candidate for candidate in candidates}
    omitted_by_span = {item.original_span_id: item for item in omitted}
    for item in omitted:
        omitted_candidate = next(
            (
                candidate
                for candidate in candidate_by_id.values()
                if item.original_span_id
                in {span.span_id for span in candidate.original_source_spans}
            ),
            None,
        )
        if omitted_candidate is None:
            raise CompressionInvariantError("omitted span has no candidate source")
        mapping_payload = {
            "from": [item.original_span_id],
            "group": item.omission_group_id,
        }
        mapping_id = f"map:delete:{_digest(mapping_payload)[:16]}"
        mappings.append(
            MappingRecord(
                mapping_id=mapping_id,
                transform="delete",
                from_span_ids=[item.original_span_id],
                to_span_ids=[],
                exactness="none_deleted",
                ordering="not_applicable",
                reason_code=item.omission_reason,
                obligation_ids=item.obligation_ids,
                relation_ids=item.relation_ids,
                transform_component="tracefold.compression",
                transform_version=COMPONENT_VERSION,
            )
        )
    unique_mappings: dict[str, MappingRecord] = {}
    for mapping in mappings:
        previous = unique_mappings.get(mapping.mapping_id)
        if previous is None:
            unique_mappings[mapping.mapping_id] = mapping
        else:
            unique_mappings[mapping.mapping_id] = previous.model_copy(
                update={
                    "obligation_ids": list(
                        dict.fromkeys([*previous.obligation_ids, *mapping.obligation_ids])
                    ),
                    "relation_ids": list(
                        dict.fromkeys([*previous.relation_ids, *mapping.relation_ids])
                    ),
                }
            )
    mappings = list(unique_mappings.values())
    output_exact_bytes = 0
    for mapping in mappings:
        if mapping.exactness != "byte_exact" or len(mapping.to_span_ids) != 1:
            continue
        span = span_by_id[mapping.to_span_ids[0]]
        if span.artifact_id == artifact_id:
            output_exact_bytes += span.byte_end - span.byte_start
    original_length = len(source.raw_bytes)
    omitted_bytes = sum(
        span_by_id[item.original_span_id].byte_end - span_by_id[item.original_span_id].byte_start
        for item in omitted_by_span.values()
        if item.original_span_id in span_by_id
    )
    represented = len({item for candidate in selected for item in candidate.obligation_ids})
    protected = len(extraction.obligations)
    coverage = MapCoverage(
        lineage_coverage=_ratio(len(output), len(output)),
        exact_copy_coverage=_ratio(output_exact_bytes, len(output)),
        protected_item_map_coverage=_ratio(represented, protected),
        original_deletion_coverage=_ratio(omitted_bytes, original_length),
        synthesized_span_count=sum(1 for span in output_spans if span.kind == "synthesized"),
        restored_span_count=0,
    )
    forward, reverse = _mapping_indexes(mappings)
    result = SourceMap(
        schema_id=base.schema_id,
        source_map_version=base.source_map_version,
        map_id="pending",
        run_id=base.run_id,
        attempt_id=base.attempt_id,
        source_manifest_hash=base.source_manifest_hash,
        query_hash=base.query_hash,
        artifacts=artifacts,
        spans=[*span_by_id.values()],
        mappings=mappings,
        forward_index=forward,
        reverse_index=reverse,
        coverage=coverage,
        normalization_profile=base.normalization_profile,
        component_version=SOURCE_MAP_COMPONENT_VERSION,
        created_at=base.created_at,
    )
    identity = result.model_dump(mode="json", exclude={"map_id", "created_at"})
    map_hash = sha256_domain(HashDomain.SOURCE_MAP, canonical_json_bytes(identity))
    result = result.model_copy(update={"map_id": f"map:source-map:{map_hash[7:23]}"})
    bytes_by_artifact: dict[str, bytes] = {}
    normalized_by_source = {item.source.source_id: item for item in extraction.normalized_sources}
    for artifact in artifacts:
        if artifact.stage == ArtifactStage.ORIGINAL and artifact.source_id is not None:
            bytes_by_artifact[artifact.artifact_id] = next(
                item.raw_bytes
                for item in extraction.sources
                if item.source_id == artifact.source_id
            )
        elif artifact.stage == ArtifactStage.NORMALIZED and artifact.source_id is not None:
            bytes_by_artifact[artifact.artifact_id] = normalized_by_source[
                artifact.source_id
            ].normalized_bytes
        elif artifact.stage == ArtifactStage.RAW_COMPRESSED:
            bytes_by_artifact[artifact.artifact_id] = output
    validation = validate_source_map(result, artifacts=bytes_by_artifact)
    if not validation.valid:
        raise SourceMapValidationError("; ".join(validation.errors))
    return result


def _attempt_id(request: RawCompressionRequest) -> str:
    return f"attempt:raw:{_digest(request.model_dump(mode='json'))[:16]}"


def _failed_result(
    request: RawCompressionRequest,
    *,
    source_hash: HashValue | None,
    original_token_count: int,
    code: str,
    message: str,
    normalized_source_hash: HashValue | None = None,
) -> RawCompressionResult:
    return RawCompressionResult(
        run_id=request.run_id,
        attempt_id=_attempt_id(request),
        source_id=request.source_id,
        source_hash=source_hash,
        normalized_source_hash=normalized_source_hash,
        tokenizer_id=request.tokenizer_id,
        original_token_count=original_token_count,
        requested_token_budget=request.target_token_budget,
        requested_reduction=request.requested_reduction,
        status=CompressionStatus.FAILED,
        compiler_strategy=request.compiler_strategy,
        minimum_mandatory_token_count=0,
        failure=CompressionFailure(code=code, message=message, source_ids=[request.source_id]),
        component_version=COMPONENT_VERSION,
    )


def _warning_from_extraction(extraction: ExtractionResult) -> list[CompressionWarning]:
    return sorted(
        [
            CompressionWarning(
                code=warning.code,
                message=warning.message,
                severity=warning.severity,
                source_ids=warning.source_ids,
            )
            for warning in extraction.warnings
        ],
        key=lambda warning: (warning.code, warning.message),
    )


def _assert_preserved(
    extraction: ExtractionResult,
    selected: Sequence[CompressionCandidate],
) -> None:
    selected_obligations = {item for candidate in selected for item in candidate.obligation_ids}
    selected_relations = {item for candidate in selected for item in candidate.relation_ids}
    missing_obligations = _hard_obligation_ids(extraction) - selected_obligations
    missing_relations = _mandatory_relation_ids(extraction) - selected_relations
    if missing_obligations:
        raise CompressionInvariantError(
            f"mandatory obligations omitted: {','.join(sorted(missing_obligations))}"
        )
    if missing_relations:
        raise CompressionInvariantError(
            f"mandatory relations omitted: {','.join(sorted(missing_relations))}"
        )


def _source_hash(source: SourceArtifact) -> HashValue:
    return sha256_domain(HashDomain.SOURCE_ARTIFACT, source.raw_bytes)


def compress_source(
    request: RawCompressionRequest,
    source: SourceArtifact,
    registry: TokenizerRegistry,
    extraction: ExtractionResult | None = None,
) -> RawCompressionResult:
    source_hash = _source_hash(source)
    if source.source_id != request.source_id:
        return _failed_result(
            request,
            source_hash=source_hash,
            original_token_count=0,
            code="SOURCE_ID_MISMATCH",
            message="request source_id does not match source artifact",
        )
    try:
        tokenizer = registry.resolve(request.tokenizer_id)
    except UnknownTokenizerError:
        return _failed_result(
            request,
            source_hash=source_hash,
            original_token_count=0,
            code="UNKNOWN_TOKENIZER",
            message="requested tokenizer identity is not registered",
        )
    try:
        text = _source_text(source)
        original_tokens = tokenizer.count(text)
    except (UnicodeDecodeError, SourceCoordinateError, ValueError) as exc:
        return _failed_result(
            request,
            source_hash=source_hash,
            original_token_count=0,
            code="INVALID_SOURCE",
            message=type(exc).__name__,
        )
    if extraction is None:
        try:
            extraction = extract_obligations(source, request.source_kind)
        except (UnicodeDecodeError, SourceCoordinateError, ValueError, SyntaxError) as exc:
            return _failed_result(
                request,
                source_hash=source_hash,
                original_token_count=original_tokens,
                code="EXTRACTION_FAILURE",
                message=type(exc).__name__,
            )
    normalized_hash = next(
        (
            item.normalized_hash
            for item in extraction.normalized_sources
            if item.source.source_id == source.source_id
        ),
        None,
    )
    if extraction.failure is not None or extraction.coverage.value == "failed":
        failure = extraction.failure
        return _failed_result(
            request,
            source_hash=source_hash,
            normalized_source_hash=normalized_hash,
            original_token_count=original_tokens,
            code=failure.code if failure is not None else "EXTRACTION_FAILURE",
            message=failure.message if failure is not None else "extraction failed",
        )
    if len(extraction.sources) != 1:
        return _failed_result(
            request,
            source_hash=source_hash,
            normalized_source_hash=normalized_hash,
            original_token_count=original_tokens,
            code="MULTI_SOURCE_UNSUPPORTED",
            message="raw compression request accepts one source",
        )
    budget = request.target_token_budget
    if budget is None:
        assert request.requested_reduction is not None
        budget = max(1, int(original_tokens * (1 - request.requested_reduction)))
    actual_strategy = (
        CompilerStrategy.DETERMINISTIC_EXTRACTIVE
        if request.compiler_strategy == CompilerStrategy.AUTO
        else request.compiler_strategy
    )
    try:
        candidates = build_candidates(source, extraction, tokenizer)
        mandatory = calculate_mandatory_set(candidates, tokenizer)
        selection = select_candidates(candidates, mandatory, budget, tokenizer)
        if not selection.fits_budget:
            obligations, relations = _coverage(
                extraction,
                [
                    next(item for item in candidates if item.candidate_id == candidate_id)
                    for candidate_id in selection.selected_candidate_ids
                ],
            )
            return RawCompressionResult(
                run_id=request.run_id,
                attempt_id=_attempt_id(request),
                source_id=source.source_id,
                source_hash=source_hash,
                normalized_source_hash=normalized_hash,
                tokenizer_id=request.tokenizer_id,
                original_token_count=original_tokens,
                requested_token_budget=budget,
                requested_reduction=request.requested_reduction,
                status=CompressionStatus.INCOMPRESSIBLE,
                compiler_strategy=actual_strategy,
                selected_candidate_ids=selection.selected_candidate_ids,
                obligation_coverage=obligations,
                relation_coverage=relations,
                minimum_mandatory_token_count=selection.minimum_token_count,
                warnings=_warning_from_extraction(extraction),
                component_version=COMPONENT_VERSION,
            )
        selected, omitted_candidates, output_text, floor, fits = _fit_selection(
            source,
            extraction,
            candidates,
            selection,
            budget,
            tokenizer,
        )
        if not fits:
            obligations, relations = _coverage(extraction, selected)
            return RawCompressionResult(
                run_id=request.run_id,
                attempt_id=_attempt_id(request),
                source_id=source.source_id,
                source_hash=source_hash,
                normalized_source_hash=normalized_hash,
                tokenizer_id=request.tokenizer_id,
                original_token_count=original_tokens,
                requested_token_budget=budget,
                requested_reduction=request.requested_reduction,
                status=CompressionStatus.INCOMPRESSIBLE,
                compiler_strategy=actual_strategy,
                selected_candidate_ids=[item.candidate_id for item in selected],
                omitted_spans=_omitted_spans(candidates, selected),
                obligation_coverage=obligations,
                relation_coverage=relations,
                minimum_mandatory_token_count=floor,
                warnings=_warning_from_extraction(extraction),
                component_version=COMPONENT_VERSION,
            )
        _assert_preserved(extraction, selected)
        if extraction.content_type == ContentType.PYTHON:
            ast.parse(output_text, filename=source.file_path or "<tracefold>")
        output_tokens = tokenizer.count(output_text)
        if output_tokens >= original_tokens:
            if text:
                full = _candidate_for_full_source(source, extraction, tokenizer)
                selected = [full]
                candidates_for_map = [full]
            else:
                selected = []
                candidates_for_map = []
            output_text = text
            omitted = []
            status = CompressionStatus.UNCHANGED
            output_tokens = original_tokens
            minimum = original_tokens
        else:
            candidates_for_map = list(candidates)
            candidates_for_map.extend(
                candidate
                for candidate in selected
                if candidate.candidate_id not in {item.candidate_id for item in candidates}
            )
            omitted = _omitted_spans(omitted_candidates, selected)
            status = CompressionStatus.COMPRESSED
            minimum = floor
        attempt_id = _attempt_id(request)
        source_map = build_compressed_source_map(
            extraction,
            candidates_for_map,
            selected,
            omitted,
            output_text=output_text,
            run_id=request.run_id,
            attempt_id=attempt_id,
            created_at=FIXED_CREATED_AT,
        )
        output_hash = sha256_domain(HashDomain.CONTEXT_ARTIFACT, output_text.encode("utf-8"))
        obligations, relations = _coverage(extraction, selected)
        achieved = 0.0 if original_tokens == 0 else round(1 - output_tokens / original_tokens, 6)
        return RawCompressionResult(
            run_id=request.run_id,
            attempt_id=attempt_id,
            source_id=source.source_id,
            source_hash=source_hash,
            normalized_source_hash=normalized_hash,
            tokenizer_id=request.tokenizer_id,
            original_token_count=original_tokens,
            requested_token_budget=budget,
            requested_reduction=request.requested_reduction,
            compressed_token_count=output_tokens,
            achieved_reduction=achieved,
            status=status,
            compiler_strategy=actual_strategy,
            compressed_text=output_text,
            selected_candidate_ids=[
                item.candidate_id for item in sorted(selected, key=_candidate_sort_key)
            ],
            omitted_spans=omitted,
            obligation_coverage=obligations,
            relation_coverage=relations,
            minimum_mandatory_token_count=minimum,
            compressed_hash=output_hash,
            source_map=source_map,
            warnings=_warning_from_extraction(extraction),
            component_version=COMPONENT_VERSION,
        )
    except (SourceMapValidationError, CompressionInvariantError, SyntaxError, ValueError) as exc:
        return _failed_result(
            request,
            source_hash=source_hash,
            normalized_source_hash=normalized_hash,
            original_token_count=original_tokens,
            code="COMPRESSION_FAILURE",
            message=type(exc).__name__,
        )


__all__ = [
    "CompressionInvariantError",
    "build_candidates",
    "build_compressed_source_map",
    "calculate_mandatory_set",
    "compile_document",
    "compile_json",
    "compile_logs",
    "compile_python",
    "compress_source",
    "select_candidates",
]
