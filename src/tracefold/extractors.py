import ast
import hashlib
import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from tracefold.obligations import SpanCollector, make_obligation, make_source_span
from tracefold.relations import make_relation, validate_relations
from tracefold.schemas.common import DiscoveryStatus
from tracefold.schemas.phase2 import (
    ContentType,
    CoverageState,
    DialogueMessage,
    ExtractionConfidence,
    ExtractionFailure,
    ExtractionResult,
    ExtractionWarning,
    Obligation,
    Relation,
    RelationExactness,
    SourceArtifact,
)
from tracefold.schemas.source import SourceInput
from tracefold.serialization import parse_json_strict
from tracefold.sources import (
    SourceCoordinateError,
    SourceCoordinateIndex,
    SourceNormalizationError,
    ingest_source,
    normalize_source,
)

NUMBER_PATTERN = re.compile(r"(?<![\w.])[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?(?![\w.])")
DATE_PATTERN = re.compile(r"\b\d{4}[-/]\d{2}[-/]\d{2}\b")
TIME_PATTERN = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?\b")
VERSION_PATTERN = re.compile(r"(?<![\w])v?\d+\.\d+(?:\.\d+)+(?:[-+][0-9A-Za-z.-]+)?\b")
UUID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
)
HASH_PATTERN = re.compile(r"\b[0-9a-fA-F]{32,64}\b")
CURRENCY_PATTERN = re.compile(
    r"(?:[$€£₹]\s*[+-]?\d+(?:\.\d+)?|[+-]?\d+(?:\.\d+)?\s+"
    r"(?:USD|EUR|GBP|INR|JPY|CAD|AUD)\b)",
    re.IGNORECASE,
)
PERCENT_PATTERN = re.compile(r"(?<![\w.])[+-]?\d+(?:\.\d+)?\s*%")
UNIT_PATTERN = re.compile(
    r"(?<![\w.])([+-]?(?:\d+(?:\.\d+)?|\.\d+))\s*"
    r"(ms|milliseconds?|seconds?|minutes?|hours?|days?|kg|g|mg|mb|gb|"
    r"kb|bytes?|px|meters?|m|cm|mm|hz|khz|%)\b",
    re.IGNORECASE,
)
IDENTIFIER_PATTERN = re.compile(
    r"\b(?:CVE-\d{4}-\d+|(?:ID|REQ|TICKET|TRACE|SPAN|SESSION)[-_][A-Za-z0-9._-]+)\b",
    re.IGNORECASE,
)
NEGATION_PATTERN = re.compile(
    r"\b(?:not|no|never|without|cannot|can't|didn't|doesn't|isn't|won't|"
    r"shouldn't|mustn't)\b",
    re.IGNORECASE,
)
QUANTIFIER_PATTERN = re.compile(
    r"\b(?:all|any|some|none|only|each|every|at\s+least|at\s+most|exactly)\b",
    re.IGNORECASE,
)
PERMISSION_PATTERN = re.compile(
    r"\b(?:may|can|allowed|permitted|authori[sz]ed|shall)\b", re.IGNORECASE
)
PROHIBITION_PATTERN = re.compile(
    r"\b(?:must\s+not|do\s+not|don't|prohibited|forbidden|cannot|can't)\b",
    re.IGNORECASE,
)
CONDITION_PATTERN = re.compile(
    r"\b(?:if|when|provided\s+that|only\s+if|as\s+long\s+as)\b", re.IGNORECASE
)
EXCEPTION_PATTERN = re.compile(r"\b(?:unless|except|other\s+than|excluding)\b", re.IGNORECASE)
CORRECTION_PATTERN = re.compile(
    r"\b(?:actually|instead|correction|corrected|supersedes|updated?|update)\b",
    re.IGNORECASE,
)
COMMITMENT_PATTERN = re.compile(
    r"\b(?:will|shall|promise|promised|agree(?:d)?|commit(?:ted)?|must)\b",
    re.IGNORECASE,
)
ROLE_PATTERN = re.compile(r"(?im)^(system|developer|user|assistant|tool)\s*:")
COMMON_CAPITALIZED = {
    "The",
    "A",
    "An",
    "This",
    "That",
    "Use",
    "Limit",
    "Error",
    "Warning",
    "Info",
}


def _failure_result(
    content_type: ContentType,
    sources: list[SourceArtifact],
    code: str,
    message: str,
) -> ExtractionResult:
    return ExtractionResult(
        content_type=content_type,
        sources=sources,
        normalized_sources=[],
        spans=[],
        obligations=[],
        relations=[],
        coverage=CoverageState.FAILED,
        failure=ExtractionFailure(
            code=code, message=message, source_ids=[s.source_id for s in sources]
        ),
    )


def _content_type(source: SourceArtifact, requested: ContentType | None) -> ContentType:
    if requested is not None:
        return requested
    kind = source.kind.lower()
    media = source.media_type.lower()
    if kind in {"dialogue", "conversation", "messages"}:
        return ContentType.DIALOGUE
    if kind in {"python", "code"} or media in {"text/x-python", "application/x-python"}:
        return ContentType.PYTHON
    if kind in {"json", "structured"} or "json" in media:
        return ContentType.JSON
    if kind in {"log", "logs"} or "log" in media:
        return ContentType.LOG
    if source.file_path is not None and source.file_path.endswith(".py"):
        return ContentType.PYTHON
    if kind in {"text", "document", "markdown", "plain"} or media in {
        "text/plain",
        "text/markdown",
    }:
        return ContentType.DOCUMENT
    return ContentType.UNKNOWN


def _line_bounds(text: str, position: int) -> tuple[int, int]:
    start = text.rfind("\n", 0, position) + 1
    end = text.find("\n", position)
    return start, len(text) if end < 0 else end


def _inside(position: int, ranges: Iterable[tuple[int, int]]) -> bool:
    return any(start <= position < end for start, end in ranges)


def _append_unique(items: list[Any], seen: set[str], item: Any, key: str) -> None:
    if key not in seen:
        seen.add(key)
        items.append(item)


def _extract_document(
    source: SourceArtifact,
) -> tuple[
    list[Any],
    list[Obligation],
    list[Relation],
    list[ExtractionWarning],
    CoverageState,
]:
    text = source.raw_bytes.decode("utf-8", "strict")
    spans = SpanCollector(source)
    obligations: list[Obligation] = []
    obligation_seen: set[str] = set()
    relation_specs: list[
        tuple[str, list[Obligation], list[str], RelationExactness, DiscoveryStatus, dict[str, Any]]
    ] = []
    warnings: list[ExtractionWarning] = []

    def add(
        class_name: str,
        start: int,
        end: int,
        *,
        value: object | None = None,
        method: str,
        confidence: ExtractionConfidence = ExtractionConfidence.EXACT,
        status: DiscoveryStatus = DiscoveryStatus.KNOWN,
        kind: str = "text",
        lexeme: str | None = None,
        owner_spans: list[Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Obligation:
        span = spans.add(
            start,
            end,
            kind=kind,
            role=source.role,
            conversation_message_id=source.message_id,
        )
        item = make_obligation(
            class_name=class_name,
            value=text[start:end] if value is None else value,
            source=source,
            spans=[span],
            extraction_method=method,
            confidence=confidence,
            discovery_status=status,
            lexeme=text[start:end] if lexeme is None else lexeme,
            owner_spans=owner_spans,
            metadata={"char_start": start, "char_end": end, **(metadata or {})},
        )
        _append_unique(obligations, obligation_seen, item, item.obligation_id)
        return next(
            existing for existing in obligations if existing.obligation_id == item.obligation_id
        )

    def relation(
        relation_type: str,
        endpoints: list[Obligation],
        evidence: list[str],
        *,
        exactness: RelationExactness,
        status: DiscoveryStatus = DiscoveryStatus.KNOWN,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        relation_specs.append(
            (relation_type, endpoints, evidence, exactness, status, metadata or {})
        )

    role_obligations: list[Obligation] = []
    for match in ROLE_PATTERN.finditer(text):
        role = match.group(1).lower()
        role_span = spans.add(
            match.start(1),
            match.end(1),
            kind="boundary",
            role=role,
            conversation_message_id=source.message_id,
        )
        boundary = make_obligation(
            class_name="role.boundary",
            value=role,
            source=source,
            spans=[role_span],
            extraction_method="role-label-parser",
            confidence=ExtractionConfidence.EXACT,
            discovery_status=DiscoveryStatus.KNOWN,
            lexeme=match.group(0),
            metadata={"role": role},
        )
        _append_unique(obligations, obligation_seen, boundary, boundary.obligation_id)
        role_obligations.append(boundary)
        if role in {"system", "developer"}:
            line_start, line_end = _line_bounds(text, match.end())
            instruction = add(
                "instruction.system_developer",
                match.end(),
                line_end,
                method="role-boundary-parser",
                metadata={"role": role},
            )
            relation(
                "relation.instruction_scope",
                [boundary, instruction],
                [role_span.span_id, instruction.source_span_ids[0]],
                exactness=RelationExactness.EXACT,
                metadata={"scope": "line"},
            )

    if source.authority.lower() in {"system", "developer"} and not role_obligations:
        boundary = add(
            "role.boundary",
            0,
            len(text),
            value=source.authority.lower(),
            method="source-authority",
            kind="boundary",
            metadata={"role": source.authority.lower()},
        )
        instruction = add(
            "instruction.system_developer",
            0,
            len(text),
            method="source-authority",
            metadata={"role": source.authority.lower()},
        )
        relation(
            "relation.instruction_scope",
            [boundary, instruction],
            [boundary.source_span_ids[0], instruction.source_span_ids[0]],
            exactness=RelationExactness.EXACT,
            metadata={"scope": "source"},
        )
    elif source.role and not role_obligations:
        role_obligations.append(
            add(
                "role.boundary",
                0,
                len(text),
                value=source.role,
                method="message-metadata",
                kind="boundary",
                metadata={"role": source.role},
            )
        )

    date_ranges: list[tuple[int, int]] = []
    for match in DATE_PATTERN.finditer(text):
        date_ranges.append((match.start(), match.end()))
        add("temporal.date", match.start(), match.end(), method="date-lexical-parser")

    version_ranges: list[tuple[int, int]] = []
    for match in VERSION_PATTERN.finditer(text):
        version_ranges.append((match.start(), match.end()))
        add("identifier.version", match.start(), match.end(), method="version-lexical-parser")

    for match in TIME_PATTERN.finditer(text):
        add("temporal.timestamp", match.start(), match.end(), method="time-lexical-parser")

    number_by_start: dict[int, Obligation] = {}
    for match in NUMBER_PATTERN.finditer(text):
        if _inside(match.start(), date_ranges + version_ranges):
            continue
        item = add("numeric.number", match.start(), match.end(), method="number-lexical-parser")
        number_by_start[match.start()] = item

    for match in CURRENCY_PATTERN.finditer(text):
        add("numeric.currency", match.start(), match.end(), method="currency-lexical-parser")

    percentage_by_start: dict[int, Obligation] = {}
    for match in PERCENT_PATTERN.finditer(text):
        item = add(
            "numeric.percentage", match.start(), match.end(), method="percentage-lexical-parser"
        )
        percentage_by_start[match.start()] = item

    def owner_span(start: int, end: int) -> Any | None:
        line_start, _ = _line_bounds(text, start)
        prefix = text[line_start:start]
        label = re.search(r"([A-Za-z_][\w .-]{0,50})\s*[:=]\s*$", prefix)
        if label:
            owner_start = line_start + label.start(1)
            return spans.add(owner_start, line_start + label.end(1), kind="text")
        after = text[end : min(len(text), end + 80)]
        target = re.search(r"\bfor\s+([A-Za-z_][\w.-]*)", after, re.IGNORECASE)
        if target:
            return spans.add(end + target.start(1), end + target.end(1), kind="text")
        return None

    unit_obligations: list[Obligation] = []
    for match in UNIT_PATTERN.finditer(text):
        unit_start, unit_end = match.start(2), match.end(2)
        owner = owner_span(match.start(), match.end())
        unit = add(
            "numeric.unit",
            unit_start,
            unit_end,
            method="unit-lexical-parser",
            owner_spans=[owner] if owner is not None else None,
            metadata={"number_start": match.start(1), "unit": match.group(2).lower()},
        )
        unit_obligations.append(unit)
        number = number_by_start.get(match.start(1))
        if number is not None and owner is not None:
            owner_obligation = make_obligation(
                class_name="identifier.generic",
                value=text[owner.char_start : owner.char_end],
                source=source,
                spans=[owner],
                extraction_method="label-owner-parser",
                confidence=ExtractionConfidence.EXACT,
                discovery_status=DiscoveryStatus.PARTIAL,
                lexeme=text[owner.char_start : owner.char_end],
                metadata={"owner_for": unit.obligation_id},
            )
            _append_unique(
                obligations, obligation_seen, owner_obligation, owner_obligation.obligation_id
            )
            relation(
                "relation.value_unit_owner",
                [number, unit, owner_obligation],
                [number.source_span_ids[0], unit.source_span_ids[0], owner.span_id],
                exactness=RelationExactness.EXACT,
                metadata={"ownership": "label"},
            )

    for match in UUID_PATTERN.finditer(text):
        add("identifier.generic", match.start(), match.end(), method="uuid-lexical-parser")
    for match in HASH_PATTERN.finditer(text):
        if not _inside(match.start(), date_ranges + version_ranges):
            add("identifier.generic", match.start(), match.end(), method="hex-identity-parser")
    for match in IDENTIFIER_PATTERN.finditer(text):
        add("identifier.generic", match.start(), match.end(), method="identifier-lexical-parser")

    for match in re.finditer(
        r"\b[A-Z][a-z][A-Za-z0-9_-]*\b(?:\s+\b[A-Z][a-z][A-Za-z0-9_-]*\b)*", text
    ):
        if match.group(0) not in COMMON_CAPITALIZED:
            add(
                "entity.named",
                match.start(),
                match.end(),
                method="capitalization-signal",
                confidence=ExtractionConfidence.INFERRED,
                status=DiscoveryStatus.PARTIAL,
            )

    for pattern, class_name, method in (
        (NEGATION_PATTERN, "logic.negation", "negation-lexical-parser"),
        (QUANTIFIER_PATTERN, "logic.quantifier", "quantifier-lexical-parser"),
        (PERMISSION_PATTERN, "policy.permission", "permission-lexical-parser"),
        (PROHIBITION_PATTERN, "policy.prohibition", "prohibition-lexical-parser"),
        (CONDITION_PATTERN, "logic.condition", "condition-lexical-parser"),
        (EXCEPTION_PATTERN, "logic.exception", "exception-lexical-parser"),
    ):
        for match in pattern.finditer(text):
            add(class_name, match.start(), match.end(), method=method)

    sentences = list(re.finditer(r"[^.!?\n]+(?:[.!?]|$)", text))
    correction_sentences: list[tuple[Any, Obligation]] = []
    for sentence in sentences:
        sentence_text = sentence.group(0)
        correction_marker = CORRECTION_PATTERN.search(sentence_text)
        if correction_marker:
            current = add(
                "temporal.correction",
                sentence.start(),
                sentence.end(),
                method="correction-marker-parser",
                metadata={"marker": correction_marker.group(0)},
            )
            correction_sentences.append((sentence, current))
        if COMMITMENT_PATTERN.search(sentence_text):
            add(
                "dialogue.commitment",
                sentence.start(),
                sentence.end(),
                method="commitment-marker-parser",
                status=DiscoveryStatus.PARTIAL,
                confidence=ExtractionConfidence.INFERRED,
            )

        condition = CONDITION_PATTERN.search(sentence_text)
        if condition and re.search(
            r"(?:,|\bthen\b)", sentence_text[condition.end() :], re.IGNORECASE
        ):
            condition_obligation = add(
                "logic.condition",
                sentence.start() + condition.start(),
                sentence.start() + condition.end(),
                method="condition-consequence-parser",
            )
            consequence_start = sentence.start() + condition.end()
            comma = text.find(",", consequence_start, sentence.end())
            consequence_start = comma + 1 if comma >= 0 else consequence_start
            consequence = add(
                "logic.condition",
                consequence_start,
                sentence.end(),
                method="condition-consequence-parser",
                metadata={"role": "consequence"},
            )
            relation(
                "relation.condition_consequence",
                [condition_obligation, consequence],
                [condition_obligation.source_span_ids[0], consequence.source_span_ids[0]],
                exactness=RelationExactness.EXACT,
            )

        exception = EXCEPTION_PATTERN.search(sentence_text)
        if exception:
            rule = add(
                "logic.condition",
                sentence.start(),
                sentence.start() + exception.start(),
                method="rule-exception-parser",
                metadata={"role": "rule"},
            )
            exception_obligation = add(
                "logic.exception",
                sentence.start() + exception.start(),
                sentence.start() + exception.end(),
                method="rule-exception-parser",
            )
            relation(
                "relation.rule_exception",
                [rule, exception_obligation],
                [rule.source_span_ids[0], exception_obligation.source_span_ids[0]],
                exactness=RelationExactness.EXACT,
            )

    for index, (current_sentence, current) in enumerate(correction_sentences):
        prior = next(
            (
                sentence
                for sentence in reversed(sentences[: sentences.index(current_sentence)])
                if sentence.group(0).strip()
            ),
            None,
        )
        if prior is not None:
            previous = add(
                "temporal.correction",
                prior.start(),
                prior.end(),
                method="correction-order-parser",
                confidence=ExtractionConfidence.INFERRED,
                status=DiscoveryStatus.PARTIAL,
                metadata={"role": "superseded"},
            )
            relation(
                "relation.statement_correction",
                [previous, current],
                [previous.source_span_ids[0], current.source_span_ids[0]],
                exactness=RelationExactness.INFERRED,
                status=DiscoveryStatus.PARTIAL,
                metadata={"order": index},
            )

    relations: list[Relation] = []
    relation_seen: set[str] = set()
    for relation_type, endpoints, evidence, exactness, status, metadata in relation_specs:
        relation_item = make_relation(
            relation_type=relation_type,
            obligations=endpoints,
            evidence_span_ids=evidence,
            extraction_method="deterministic-document-parser",
            discovery_status=status,
            exactness=exactness,
            metadata=metadata,
        )
        _append_unique(relations, relation_seen, relation_item, relation_item.relation_id)
    validate_relations(relations, obligations, {span.span_id for span in spans.values()})
    return spans.values(), obligations, relations, warnings, CoverageState.PARTIAL


def _base_source(
    source: SourceArtifact, content_type: ContentType
) -> tuple[Any, ExtractionResult | None]:
    try:
        normalized = normalize_source(source)
    except SourceNormalizationError as exc:
        return None, _failure_result(content_type, [source], "INVALID_UTF8", str(exc))
    return normalized, None


def _extract_document_result(source: SourceArtifact, content_type: ContentType) -> ExtractionResult:
    normalized, failure = _base_source(source, content_type)
    if failure is not None:
        return failure
    try:
        spans, obligations, relations, warnings, coverage = _extract_document(source)
    except (UnicodeDecodeError, SourceCoordinateError) as exc:
        return _failure_result(content_type, [source], "SOURCE_COORDINATE_FAILURE", str(exc))
    assert normalized is not None
    return ExtractionResult(
        content_type=content_type,
        sources=[source],
        normalized_sources=[normalized],
        spans=spans,
        obligations=obligations,
        relations=relations,
        coverage=coverage,
        warnings=warnings,
    )


@dataclass
class _JsonNode:
    path: str
    start: int
    end: int
    value: Any
    kind: str
    children: list["_JsonNode"] = field(default_factory=list)
    key: str | None = None
    key_start: int | None = None
    key_end: int | None = None


class _JsonParseError(ValueError):
    pass


class _JsonParser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.decoder = json.JSONDecoder()
        self.position = 0

    def _skip(self) -> None:
        while self.position < len(self.text) and self.text[self.position] in " \t\r\n":
            self.position += 1

    def parse(self) -> _JsonNode:
        node = self.value("")
        self._skip()
        if self.position != len(self.text):
            raise _JsonParseError("trailing JSON data")
        return node

    def value(self, path: str) -> _JsonNode:
        self._skip()
        start = self.position
        if start >= len(self.text):
            raise _JsonParseError("missing JSON value")
        char = self.text[start]
        if char == "{":
            self.position += 1
            children: list[_JsonNode] = []
            keys: set[str] = set()
            self._skip()
            if self.position < len(self.text) and self.text[self.position] == "}":
                self.position += 1
                return _JsonNode(path, start, self.position, {}, "object", children)
            while True:
                self._skip()
                key_start = self.position
                try:
                    key, key_end = self.decoder.raw_decode(self.text, self.position)
                except ValueError as exc:
                    raise _JsonParseError("invalid JSON object key") from exc
                if not isinstance(key, str):
                    raise _JsonParseError("JSON object key is not a string")
                if key in keys:
                    raise _JsonParseError("duplicate JSON object key")
                keys.add(key)
                self.position = key_end
                self._skip()
                if self.position >= len(self.text) or self.text[self.position] != ":":
                    raise _JsonParseError("missing JSON object colon")
                self.position += 1
                child_path = f"{path}/{_escape_pointer(key)}"
                child = self.value(child_path)
                child.key = key
                child.key_start = key_start
                child.key_end = key_end
                children.append(child)
                self._skip()
                if self.position < len(self.text) and self.text[self.position] == "}":
                    self.position += 1
                    break
                if self.position >= len(self.text) or self.text[self.position] != ",":
                    raise _JsonParseError("missing JSON object comma")
                self.position += 1
            value = {str(child.key): child.value for child in children}
            return _JsonNode(path, start, self.position, value, "object", children)
        if char == "[":
            self.position += 1
            children = []
            self._skip()
            if self.position < len(self.text) and self.text[self.position] == "]":
                self.position += 1
                return _JsonNode(path, start, self.position, [], "array", children)
            index = 0
            while True:
                child = self.value(f"{path}/{index}")
                children.append(child)
                index += 1
                self._skip()
                if self.position < len(self.text) and self.text[self.position] == "]":
                    self.position += 1
                    break
                if self.position >= len(self.text) or self.text[self.position] != ",":
                    raise _JsonParseError("missing JSON array comma")
                self.position += 1
            return _JsonNode(
                path, start, self.position, [child.value for child in children], "array", children
            )
        if self.text.startswith(("NaN", "Infinity", "-Infinity"), start):
            raise _JsonParseError("non-finite JSON number")
        try:
            value, end = self.decoder.raw_decode(self.text, self.position)
        except ValueError as exc:
            raise _JsonParseError("invalid JSON value") from exc
        self.position = end
        kind = "null" if value is None else "boolean" if isinstance(value, bool) else "value"
        return _JsonNode(path, start, end, value, kind)


def _escape_pointer(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _json_result(source: SourceArtifact) -> ExtractionResult:
    normalized, failure = _base_source(source, ContentType.JSON)
    if failure is not None:
        return failure
    try:
        text = source.raw_bytes.decode("utf-8", "strict")
        parse_text = text[1:] if text.startswith("\ufeff") else text
        parse_json_strict(parse_text)
        root = _JsonParser(parse_text).parse()
        if parse_text != text:

            def shift_offsets(node: _JsonNode) -> None:
                node.start += 1
                node.end += 1
                if node.key_start is not None:
                    node.key_start += 1
                if node.key_end is not None:
                    node.key_end += 1
                for child in node.children:
                    shift_offsets(child)

            shift_offsets(root)
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        return _failure_result(ContentType.JSON, [source], "INVALID_JSON", str(exc))
    assert normalized is not None
    spans = SpanCollector(source)
    obligations: list[Obligation] = []
    obligation_seen: set[str] = set()
    nodes: list[_JsonNode] = []
    by_path: dict[str, _JsonNode] = {}
    path_obligations: dict[str, Obligation] = {}
    key_obligations: dict[str, Obligation] = {}

    def add(
        class_name: str,
        node: _JsonNode,
        *,
        start: int | None = None,
        end: int | None = None,
        value: object | None = None,
        kind: str = "json_value",
        method: str = "json-offset-parser",
        metadata: dict[str, Any] | None = None,
        confidence: ExtractionConfidence = ExtractionConfidence.EXACT,
        status: DiscoveryStatus = DiscoveryStatus.KNOWN,
    ) -> Obligation:
        span = spans.add(
            node.start if start is None else start,
            node.end if end is None else end,
            kind=kind,
            json_path=node.path,
            structured_identity={"json_path": node.path, **(metadata or {})},
        )
        item = make_obligation(
            class_name=class_name,
            value=node.value if value is None else value,
            source=source,
            spans=[span],
            extraction_method=method,
            confidence=confidence,
            discovery_status=status,
            lexeme=text[span.char_start : span.char_end],
            metadata={"json_path": node.path, "node_kind": node.kind, **(metadata or {})},
        )
        _append_unique(obligations, obligation_seen, item, item.obligation_id)
        return next(
            existing for existing in obligations if existing.obligation_id == item.obligation_id
        )

    def walk(node: _JsonNode) -> None:
        nodes.append(node)
        by_path[node.path] = node
        structural = add(
            "structured.json_schema_path",
            node,
            kind="json_container" if node.kind in {"object", "array"} else "json_value",
            value={"path": node.path, "type": node.kind, "present": True},
        )
        path_obligations[node.path] = structural
        if node.key is not None and node.key_start is not None and node.key_end is not None:
            key_span = spans.add(
                node.key_start,
                node.key_end,
                kind="json_key",
                json_path=node.path,
                structured_identity={"key": node.key, "parent_path": node.path.rsplit("/", 1)[0]},
            )
            key_obligation = make_obligation(
                class_name="structured.json_schema_path",
                value={"path": node.path, "key": node.key, "present": True},
                source=source,
                spans=[key_span],
                extraction_method="json-key-parser",
                confidence=ExtractionConfidence.EXACT,
                discovery_status=DiscoveryStatus.KNOWN,
                lexeme=text[node.key_start : node.key_end],
                metadata={"json_path": node.path, "kind": "key"},
            )
            _append_unique(
                obligations, obligation_seen, key_obligation, key_obligation.obligation_id
            )
            key_obligations[node.path] = key_obligation
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            number = add(
                "numeric.number",
                node,
                value=node.value,
                metadata={"json_path": node.path},
            )
            path_obligations[node.path] = number
        if isinstance(node.value, str) and PERCENT_PATTERN.fullmatch(node.value.strip()):
            add("numeric.percentage", node, value=node.value)
        if node.key is not None:
            key_lower = node.key.lower()
            if key_lower in {"unit", "units", "duration_unit"}:
                unit = add("numeric.unit", node, value=node.value)
                path_obligations[node.path] = unit
            if key_lower in {"owner", "service", "name", "entity", "account"}:
                owner = add(
                    "identifier.generic",
                    node,
                    value=node.value,
                    metadata={"role": "owner"},
                )
                path_obligations[node.path] = owner
            if key_lower in {"timestamp", "time", "date", "created_at", "updated_at"}:
                timestamp = add("temporal.timestamp", node, value=node.value)
                path_obligations[node.path] = timestamp
            if key_lower in {"trace_id", "request_id", "span_id", "correlation_id"}:
                trace = add("identifier.trace_request", node, value=node.value)
                path_obligations[node.path] = trace
            if key_lower in {"error_code", "status_code", "code"}:
                add("identifier.generic", node, value=node.value, metadata={"role": "error_code"})
        for child in node.children:
            walk(child)

    walk(root)
    relation_specs: list[
        tuple[str, list[Obligation], list[str], RelationExactness, DiscoveryStatus, dict[str, Any]]
    ] = []
    anomaly_paths: set[str] = set()
    for node in nodes:
        if node.kind != "array":
            continue
        records = [child for child in node.children if child.kind == "object"]
        if len(records) < 2:
            continue
        all_keys = {
            child.key for record in records for child in record.children if child.key is not None
        }
        for key in sorted(all_keys):
            values = []
            present = []
            for record in records:
                child = next((item for item in record.children if item.key == key), None)
                present.append(child)
                if child is not None:
                    values.append(child.value)
            distinct = {json.dumps(value, sort_keys=True, ensure_ascii=False) for value in values}
            if len(present) != len(values) or (len(values) > 1 and len(distinct) > 1):
                for record, child in zip(records, present, strict=True):
                    if child is None or (
                        len(values) > 1 and len(distinct) > 1 and child.value == values[-1]
                    ):
                        anomaly_paths.add(record.path)
        for record in records:
            status_node = next(
                (child for child in record.children if child.key and child.key.lower() == "status"),
                None,
            )
            if (
                status_node is not None
                and isinstance(status_node.value, str)
                and re.search(
                    r"\b(?:error|failed|failure|critical)\b",
                    status_node.value,
                    re.IGNORECASE,
                )
            ):
                anomaly_paths.add(record.path)

    for path in sorted(anomaly_paths):
        node = by_path[path]
        add(
            "structured.anomalous_row",
            node,
            value={"path": path, "reason": "deterministic-peer-deviation"},
            kind="json_container",
            method="json-anomaly-rule:peer-deviation",
            confidence=ExtractionConfidence.EXACT,
            status=DiscoveryStatus.PARTIAL,
        )

    for node in nodes:
        if node.kind != "object":
            continue
        fields = {child.key.lower(): child for child in node.children if child.key is not None}
        value_node = next(
            (fields[key] for key in ("value", "amount", "limit") if key in fields), None
        )
        unit_node = next((fields[key] for key in ("unit", "units") if key in fields), None)
        owner_node = next(
            (fields[key] for key in ("owner", "service", "name", "entity") if key in fields), None
        )
        if value_node and unit_node and owner_node:
            value_obligation = path_obligations[value_node.path]
            unit_obligation = path_obligations[unit_node.path]
            owner_obligation = path_obligations[owner_node.path]
            relation_specs.append(
                (
                    "relation.value_unit_owner",
                    [value_obligation, unit_obligation, owner_obligation],
                    [
                        value_obligation.source_span_ids[0],
                        unit_obligation.source_span_ids[0],
                        owner_obligation.source_span_ids[0],
                    ],
                    RelationExactness.EXACT,
                    DiscoveryStatus.KNOWN,
                    {"json_object": node.path},
                )
            )
        timestamp_node = next(
            (fields[key] for key in ("timestamp", "time", "date", "created_at") if key in fields),
            None,
        )
        trace_node = next(
            (
                fields[key]
                for key in ("trace_id", "request_id", "span_id", "correlation_id")
                if key in fields
            ),
            None,
        )
        if timestamp_node is not None:
            event = path_obligations[node.path]
            timestamp = path_obligations[timestamp_node.path]
            relation_specs.append(
                (
                    "relation.event_timestamp",
                    [event, timestamp],
                    [event.source_span_ids[0], timestamp.source_span_ids[0]],
                    RelationExactness.EXACT,
                    DiscoveryStatus.KNOWN,
                    {"json_path": node.path},
                )
            )
        if trace_node is not None:
            event = path_obligations[node.path]
            trace = path_obligations[trace_node.path]
            relation_specs.append(
                (
                    "relation.event_trace",
                    [event, trace],
                    [event.source_span_ids[0], trace.source_span_ids[0]],
                    RelationExactness.EXACT,
                    DiscoveryStatus.KNOWN,
                    {"json_path": node.path},
                )
            )

    relations: list[Relation] = []
    relation_seen: set[str] = set()
    for relation_type, endpoints, evidence, exactness, status, metadata in relation_specs:
        relation_item = make_relation(
            relation_type=relation_type,
            obligations=endpoints,
            evidence_span_ids=evidence,
            extraction_method="deterministic-json-parser",
            discovery_status=status,
            exactness=exactness,
            metadata=metadata,
        )
        _append_unique(relations, relation_seen, relation_item, relation_item.relation_id)
    validate_relations(relations, obligations, {span.span_id for span in spans.values()})
    return ExtractionResult(
        content_type=ContentType.JSON,
        sources=[source],
        normalized_sources=[normalized],
        spans=spans.values(),
        obligations=obligations,
        relations=relations,
        coverage=CoverageState.KNOWN,
    )


SEVERITY_LEVELS = {
    "trace": 0,
    "debug": 1,
    "info": 2,
    "notice": 2,
    "warn": 3,
    "warning": 3,
    "error": 4,
    "critical": 5,
    "fatal": 6,
}
TIMESTAMP_LOG_PATTERN = re.compile(
    r"\b\d{4}-\d{2}-\d{2}[T ][0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.\d+)?(?:Z|[+-][0-9]{2}:?[0-9]{2})?\b"
)
SEVERITY_LOG_PATTERN = re.compile(
    r"\b(?:TRACE|DEBUG|INFO|NOTICE|WARN|WARNING|ERROR|CRITICAL|FATAL)\b"
)
FIELD_PATTERN = re.compile(
    r"\b(?P<key>request_id|request|trace_id|trace|span_id|correlation_id|"
    r"error_code|code|event_id|caused_by|previous_event|service)="
    r"(?P<value>[A-Za-z0-9_.:/-]+)"
)
EXCEPTION_PATTERN_LOG = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*(?:Error|Exception)\b")


@dataclass
class _LogEvent:
    ordinal: int
    start: int
    end: int
    event_id: str
    severity: str | None
    trace: str | None
    request: str | None
    fields: dict[str, tuple[int, int, str]] = field(default_factory=dict)
    event_obligation: Obligation | None = None
    severity_obligation: Obligation | None = None


def _log_result(source: SourceArtifact) -> ExtractionResult:
    normalized, failure = _base_source(source, ContentType.LOG)
    if failure is not None:
        return failure
    try:
        text = source.raw_bytes.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        return _failure_result(ContentType.LOG, [source], "INVALID_UTF8", str(exc))
    assert normalized is not None
    spans = SpanCollector(source)
    obligations: list[Obligation] = []
    obligation_seen: set[str] = set()
    relations: list[Relation] = []
    relation_seen: set[str] = set()
    events: list[_LogEvent] = []
    offset = 0
    for ordinal, line in enumerate(text.splitlines(keepends=True)):
        content = line.rstrip("\r\n")
        start = offset
        end = start + len(content)
        offset += len(line)
        raw_event = source.raw_bytes[
            SourceCoordinateIndex(source.raw_bytes).char_to_byte(start) : SourceCoordinateIndex(
                source.raw_bytes
            ).char_to_byte(end)
        ]
        event_id = f"log:{source.source_id}:{ordinal}:{hashlib.sha256(raw_event).hexdigest()[:16]}"
        event_span = spans.add(
            start,
            end,
            kind="log_event",
            log_event_id=event_id,
            role=source.role,
        )
        severity_match = SEVERITY_LOG_PATTERN.search(content)
        event = _LogEvent(
            ordinal=ordinal,
            start=start,
            end=end,
            event_id=event_id,
            severity=severity_match.group(0).lower() if severity_match is not None else None,
            trace=None,
            request=None,
        )
        event_obligation = make_obligation(
            class_name="identifier.generic",
            value=event_id,
            source=source,
            spans=[event_span],
            extraction_method="log-line-parser",
            confidence=ExtractionConfidence.EXACT,
            discovery_status=DiscoveryStatus.PARTIAL,
            lexeme=content,
            metadata={"event_id": event_id, "ordinal": ordinal, "severity": event.severity},
        )
        _append_unique(
            obligations, obligation_seen, event_obligation, event_obligation.obligation_id
        )
        event.event_obligation = event_obligation
        for field_match in FIELD_PATTERN.finditer(content):
            key = field_match.group("key").lower()
            value = field_match.group("value")
            field_start = start + field_match.start("value")
            field_end = start + field_match.end("value")
            event.fields[key] = (field_start, field_end, value)
            if key in {"trace_id", "trace", "span_id", "correlation_id"}:
                event.trace = value
            if key in {"request_id", "request"}:
                event.request = value
        events.append(event)

        timestamp_match = TIMESTAMP_LOG_PATTERN.search(content)
        if timestamp_match:
            timestamp_span = spans.add(
                start + timestamp_match.start(),
                start + timestamp_match.end(),
                kind="text",
                log_event_id=event_id,
            )
            timestamp = make_obligation(
                class_name="temporal.timestamp",
                value=timestamp_match.group(0),
                source=source,
                spans=[timestamp_span],
                extraction_method="log-timestamp-parser",
                confidence=ExtractionConfidence.EXACT,
                discovery_status=DiscoveryStatus.KNOWN,
                lexeme=timestamp_match.group(0),
                metadata={"event_id": event_id, "ordinal": ordinal},
            )
            _append_unique(obligations, obligation_seen, timestamp, timestamp.obligation_id)
            relations.append(
                make_relation(
                    relation_type="relation.event_timestamp",
                    obligations=[event_obligation, timestamp],
                    evidence_span_ids=[event_span.span_id, timestamp_span.span_id],
                    extraction_method="log-event-parser",
                    discovery_status=DiscoveryStatus.KNOWN,
                    exactness=RelationExactness.EXACT,
                    metadata={"event_id": event_id},
                )
            )

        severity_match = SEVERITY_LOG_PATTERN.search(content)
        if severity_match:
            severity_span = spans.add(
                start + severity_match.start(),
                start + severity_match.end(),
                kind="text",
                log_event_id=event_id,
            )
            severity = make_obligation(
                class_name="log.severity_change",
                value=severity_match.group(0).lower(),
                source=source,
                spans=[severity_span],
                extraction_method="log-severity-parser",
                confidence=ExtractionConfidence.EXACT,
                discovery_status=DiscoveryStatus.KNOWN,
                lexeme=severity_match.group(0),
                metadata={"event_id": event_id, "ordinal": ordinal},
            )
            _append_unique(obligations, obligation_seen, severity, severity.obligation_id)
            event.severity_obligation = severity
            previous = next(
                (
                    previous_event
                    for previous_event in reversed(events[:-1])
                    if previous_event.severity is not None
                    and (
                        previous_event.trace == event.trace
                        or (previous_event.trace is None and event.trace is None)
                    )
                ),
                None,
            )
            if (
                previous is not None
                and previous.severity != event.severity
                and previous.severity_obligation is not None
            ):
                previous_span = next(
                    item
                    for item in spans.values()
                    if item.span_id == previous.severity_obligation.source_span_ids[0]
                )
                transition = make_obligation(
                    class_name="log.severity_change",
                    value={"from": previous.severity, "to": event.severity},
                    source=source,
                    spans=[previous_span, severity_span],
                    extraction_method="log-severity-transition-parser",
                    confidence=ExtractionConfidence.EXACT,
                    discovery_status=DiscoveryStatus.KNOWN,
                    metadata={"from": previous.severity, "to": event.severity},
                )
                _append_unique(obligations, obligation_seen, transition, transition.obligation_id)

        for key, (field_start, field_end, value) in event.fields.items():
            field_span = spans.add(field_start, field_end, kind="text", log_event_id=event_id)
            if key in {"trace_id", "trace", "span_id", "correlation_id", "request_id", "request"}:
                identifier = make_obligation(
                    class_name="identifier.trace_request",
                    value=value,
                    source=source,
                    spans=[field_span],
                    extraction_method="log-correlation-field-parser",
                    confidence=ExtractionConfidence.EXACT,
                    discovery_status=DiscoveryStatus.KNOWN,
                    lexeme=value,
                    metadata={"event_id": event_id, "field": key},
                )
                _append_unique(obligations, obligation_seen, identifier, identifier.obligation_id)
                relations.append(
                    make_relation(
                        relation_type="relation.event_trace",
                        obligations=[event_obligation, identifier],
                        evidence_span_ids=[event_span.span_id, field_span.span_id],
                        extraction_method="log-correlation-field-parser",
                        discovery_status=DiscoveryStatus.KNOWN,
                        exactness=RelationExactness.EXACT,
                        metadata={"field": key, "event_id": event_id},
                    )
                )
            if key in {"error_code", "code"}:
                error_code = make_obligation(
                    class_name="identifier.generic",
                    value=value,
                    source=source,
                    spans=[field_span],
                    extraction_method="log-error-code-parser",
                    confidence=ExtractionConfidence.EXACT,
                    discovery_status=DiscoveryStatus.KNOWN,
                    lexeme=value,
                    metadata={"event_id": event_id, "field": key},
                )
                _append_unique(obligations, obligation_seen, error_code, error_code.obligation_id)
            if key in {"event_id", "caused_by", "previous_event"}:
                event_id_obligation = make_obligation(
                    class_name="identifier.generic",
                    value=value,
                    source=source,
                    spans=[field_span],
                    extraction_method="log-event-link-parser",
                    confidence=ExtractionConfidence.EXACT,
                    discovery_status=DiscoveryStatus.KNOWN,
                    lexeme=value,
                    metadata={"event_id": event_id, "field": key},
                )
                _append_unique(
                    obligations,
                    obligation_seen,
                    event_id_obligation,
                    event_id_obligation.obligation_id,
                )
        for exception_match in EXCEPTION_PATTERN_LOG.finditer(content):
            exception_span = spans.add(
                start + exception_match.start(),
                start + exception_match.end(),
                kind="text",
                log_event_id=event_id,
            )
            exception = make_obligation(
                class_name="identifier.generic",
                value=exception_match.group(0),
                source=source,
                spans=[exception_span],
                extraction_method="log-exception-parser",
                confidence=ExtractionConfidence.EXACT,
                discovery_status=DiscoveryStatus.KNOWN,
                lexeme=exception_match.group(0),
                metadata={"event_id": event_id, "kind": "exception"},
            )
            _append_unique(obligations, obligation_seen, exception, exception.obligation_id)

    event_by_id = {event.event_id: event for event in events}
    for event in events:
        declared_event = event.fields.get("event_id")
        if declared_event is not None:
            event_by_id[declared_event[2]] = event
        link = event.fields.get("caused_by") or event.fields.get("previous_event")
        if link is None or event.event_obligation is None:
            continue
        predecessor = event_by_id.get(link[2])
        if predecessor is None or predecessor.event_obligation is None:
            continue
        relations.append(
            make_relation(
                relation_type="relation.error_causal_predecessor",
                obligations=[predecessor.event_obligation, event.event_obligation],
                evidence_span_ids=[
                    predecessor.event_obligation.source_span_ids[0],
                    event.event_obligation.source_span_ids[0],
                ],
                extraction_method="explicit-log-causal-link-parser",
                discovery_status=DiscoveryStatus.KNOWN,
                exactness=RelationExactness.EXACT,
                metadata={"predecessor": predecessor.event_id, "error": event.event_id},
            )
        )

    unique_relations: list[Relation] = []
    for relation in relations:
        _append_unique(unique_relations, relation_seen, relation, relation.relation_id)
    validate_relations(unique_relations, obligations, {span.span_id for span in spans.values()})
    return ExtractionResult(
        content_type=ContentType.LOG,
        sources=[source],
        normalized_sources=[normalized],
        spans=spans.values(),
        obligations=obligations,
        relations=unique_relations,
        coverage=CoverageState.PARTIAL,
    )


class _PythonExtractor:
    def __init__(self, source: SourceArtifact, text: str, tree: ast.Module) -> None:
        self.source = source
        self.text = text
        self.tree = tree
        self.index = SourceCoordinateIndex(source.raw_bytes)
        self.spans = SpanCollector(source)
        self.obligations: list[Obligation] = []
        self.obligation_seen: set[str] = set()
        self.relations: list[Relation] = []
        self.relation_seen: set[str] = set()
        self.scopes: dict[int, tuple[str, ...]] = {}
        self.symbols: dict[tuple[tuple[str, ...], str], Obligation] = {}
        self.definitions: list[tuple[ast.AST, tuple[str, ...], Obligation]] = []

    def node_range(self, node: ast.AST) -> tuple[int, int] | None:
        lineno = getattr(node, "lineno", None)
        end_lineno = getattr(node, "end_lineno", None)
        col_offset = getattr(node, "col_offset", None)
        end_col_offset = getattr(node, "end_col_offset", None)
        if not all(
            isinstance(value, int) for value in (lineno, end_lineno, col_offset, end_col_offset)
        ):
            return None
        line_starts = [0]
        for match in re.finditer(r"\r\n|\r|\n", self.text):
            line_starts.append(match.end())
        assert isinstance(lineno, int)
        assert isinstance(end_lineno, int)
        assert isinstance(col_offset, int)
        assert isinstance(end_col_offset, int)
        start_line = line_starts[lineno - 1]
        end_line = line_starts[end_lineno - 1]
        try:
            start_char = self.index.byte_to_char(self.index.char_to_byte(start_line) + col_offset)
            end_char = self.index.byte_to_char(self.index.char_to_byte(end_line) + end_col_offset)
        except SourceCoordinateError:
            return None
        return start_char, end_char

    def add(
        self,
        class_name: str,
        node: ast.AST,
        *,
        value: object,
        method: str,
        kind: str = "code_node",
        confidence: ExtractionConfidence = ExtractionConfidence.EXACT,
        status: DiscoveryStatus = DiscoveryStatus.KNOWN,
        metadata: dict[str, Any] | None = None,
        span_range: tuple[int, int] | None = None,
        symbol_id: str | None = None,
    ) -> Obligation | None:
        coordinates = span_range or self.node_range(node)
        if coordinates is None:
            return None
        span = self.spans.add(
            coordinates[0],
            coordinates[1],
            kind=kind,
            code_symbol_id=symbol_id,
            structured_identity=metadata,
        )
        item = make_obligation(
            class_name=class_name,
            value=value,
            source=self.source,
            spans=[span],
            extraction_method=method,
            confidence=confidence,
            discovery_status=status,
            lexeme=self.text[coordinates[0] : coordinates[1]],
            metadata={"char_start": coordinates[0], "char_end": coordinates[1], **(metadata or {})},
        )
        _append_unique(self.obligations, self.obligation_seen, item, item.obligation_id)
        return next(
            existing
            for existing in self.obligations
            if existing.obligation_id == item.obligation_id
        )

    def relation(
        self,
        relation_type: str,
        endpoints: list[Obligation],
        evidence: list[str],
        *,
        exactness: RelationExactness,
        status: DiscoveryStatus,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        item = make_relation(
            relation_type=relation_type,
            obligations=endpoints,
            evidence_span_ids=evidence,
            extraction_method="deterministic-python-ast",
            discovery_status=status,
            exactness=exactness,
            metadata=metadata,
        )
        _append_unique(self.relations, self.relation_seen, item, item.relation_id)

    def collect_definitions(self, node: ast.AST, scope: tuple[str, ...]) -> None:
        self.scopes[id(node)] = scope
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = node.name
            qualified = ".".join((*scope, name))
            kind = "class" if isinstance(node, ast.ClassDef) else "function"
            coordinates = self.node_range(node)
            if coordinates is not None:
                symbol_id = (
                    f"py:{self.source.source_id}:{qualified}:{kind}:"
                    f"{self.index.char_to_byte(coordinates[0])}"
                )
                item = self.add(
                    "code.definition",
                    node,
                    value={"name": name, "qualified_name": qualified, "kind": kind},
                    method="python-ast-definition",
                    metadata={
                        "name": name,
                        "qualified_name": qualified,
                        "kind": kind,
                        "symbol_id": symbol_id,
                    },
                    symbol_id=symbol_id,
                )
                if item is not None:
                    self.symbols[(scope, name)] = item
                    self.definitions.append((node, scope, item))
                child_scope = (*scope, name)
            else:
                child_scope = (*scope, name)
            arguments = (
                (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                else ()
            )
            for argument in arguments:
                parameter_range = self.node_range(argument)
                if parameter_range is not None:
                    parameter_id = (
                        f"py:{self.source.source_id}:{qualified}.{argument.arg}:parameter:"
                        f"{self.index.char_to_byte(parameter_range[0])}"
                    )
                    parameter = self.add(
                        "code.definition",
                        argument,
                        value={
                            "name": argument.arg,
                            "kind": "parameter",
                            "qualified_name": qualified,
                        },
                        method="python-ast-parameter",
                        metadata={
                            "name": argument.arg,
                            "qualified_name": qualified,
                            "kind": "parameter",
                            "symbol_id": parameter_id,
                        },
                        span_range=parameter_range,
                        symbol_id=parameter_id,
                    )
                    if parameter is not None:
                        self.symbols[(child_scope, argument.arg)] = parameter
            for child in ast.iter_child_nodes(node):
                self.collect_definitions(child, child_scope)
            return
        for child in ast.iter_child_nodes(node):
            self.collect_definitions(child, scope)

    def resolve(self, name: str, scope: tuple[str, ...]) -> Obligation | None:
        for length in range(len(scope), -1, -1):
            item = self.symbols.get((scope[:length], name))
            if item is not None:
                return item
        return self.symbols.get(((), name))

    def process(self, node: ast.AST, scope: tuple[str, ...]) -> None:
        node_scope = self.scopes.get(id(node), scope)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            node_scope = (*scope, node.name)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            import_item = self.add(
                "code.import",
                node,
                value=ast.unparse(node),
                method="python-ast-import",
                metadata={"scope": ".".join(scope), "module": getattr(node, "module", None)},
            )
            if import_item is not None:
                aliases = node.names
                for alias in aliases:
                    local_name = alias.asname or alias.name.split(".")[0]
                    binding = self.add(
                        "code.definition",
                        node,
                        value={"name": local_name, "kind": "import_binding", "import": alias.name},
                        method="python-ast-import-binding",
                        metadata={
                            "name": local_name,
                            "import": alias.name,
                            "scope": ".".join(scope),
                        },
                    )
                    if binding is not None:
                        self.relation(
                            "relation.import_symbol",
                            [import_item, binding],
                            [import_item.source_span_ids[0], binding.source_span_ids[0]],
                            exactness=RelationExactness.EXACT,
                            status=DiscoveryStatus.KNOWN,
                        )
        if isinstance(node, ast.Call):
            call = self.add(
                "code.call",
                node,
                value=ast.unparse(node.func),
                method="python-ast-call",
                metadata={"scope": ".".join(scope)},
            )
            if call is not None:
                callee_name = node.func.id if isinstance(node.func, ast.Name) else None
                callee = self.resolve(callee_name, scope) if callee_name else None
                caller = (
                    self.resolve(scope[-1], scope[:-1])
                    if scope
                    else self.symbols.get(((), "__module__"))
                )
                if caller is None:
                    caller = next(
                        (
                            item
                            for _, _, item in self.definitions
                            if item.metadata.get("kind") == "module"
                        ),
                        None,
                    )
                if callee is not None and caller is not None:
                    self.relation(
                        "relation.caller_callee",
                        [caller, call, callee],
                        [
                            caller.source_span_ids[0],
                            call.source_span_ids[0],
                            callee.source_span_ids[0],
                        ],
                        exactness=RelationExactness.EXACT,
                        status=DiscoveryStatus.KNOWN,
                        metadata={"resolution": "local"},
                    )
                elif caller is not None:
                    self.relation(
                        "relation.caller_callee",
                        [caller, call],
                        [caller.source_span_ids[0], call.source_span_ids[0]],
                        exactness=RelationExactness.INFERRED,
                        status=DiscoveryStatus.PARTIAL,
                        metadata={
                            "resolution": "attribute"
                            if isinstance(node.func, ast.Attribute)
                            else "dynamic"
                        },
                    )
        if isinstance(node, (ast.If, ast.While, ast.IfExp)):
            guard_node = node.test if hasattr(node, "test") else node.test
            guard = self.add(
                "code.branch_guard",
                guard_node,
                value=ast.unparse(guard_node),
                method="python-ast-guard",
                metadata={"scope": ".".join(scope)},
            )
            body = getattr(node, "body", None)
            if guard is not None and isinstance(body, list) and body:
                first = self.node_range(body[0])
                last = self.node_range(body[-1])
                if first is not None and last is not None:
                    body_span = self.spans.add(first[0], last[1], kind="code_node")
                    body_obligation = make_obligation(
                        class_name="code.definition",
                        value={"kind": "branch_body", "scope": ".".join(scope)},
                        source=self.source,
                        spans=[body_span],
                        extraction_method="python-ast-branch-body",
                        confidence=ExtractionConfidence.EXACT,
                        discovery_status=DiscoveryStatus.KNOWN,
                        lexeme=self.text[first[0] : last[1]],
                        metadata={"kind": "branch_body"},
                    )
                    _append_unique(
                        self.obligations,
                        self.obligation_seen,
                        body_obligation,
                        body_obligation.obligation_id,
                    )
                    self.relation(
                        "relation.condition_consequence",
                        [guard, body_obligation],
                        [guard.source_span_ids[0], body_span.span_id],
                        exactness=RelationExactness.EXACT,
                        status=DiscoveryStatus.KNOWN,
                    )
        if isinstance(node, ast.match_case) and node.guard is not None:
            guard = self.add(
                "code.branch_guard",
                node.guard,
                value=ast.unparse(node.guard),
                method="python-ast-match-guard",
                metadata={"scope": ".".join(scope), "kind": "match_guard"},
            )
            if guard is not None and node.body:
                first = self.node_range(node.body[0])
                last = self.node_range(node.body[-1])
                if first is not None and last is not None:
                    body_span = self.spans.add(first[0], last[1], kind="code_node")
                    body_obligation = make_obligation(
                        class_name="code.definition",
                        value={"kind": "match_body", "scope": ".".join(scope)},
                        source=self.source,
                        spans=[body_span],
                        extraction_method="python-ast-match-body",
                        confidence=ExtractionConfidence.EXACT,
                        discovery_status=DiscoveryStatus.KNOWN,
                        lexeme=self.text[first[0] : last[1]],
                        metadata={"kind": "match_body"},
                    )
                    _append_unique(
                        self.obligations,
                        self.obligation_seen,
                        body_obligation,
                        body_obligation.obligation_id,
                    )
                    self.relation(
                        "relation.condition_consequence",
                        [guard, body_obligation],
                        [guard.source_span_ids[0], body_span.span_id],
                        exactness=RelationExactness.EXACT,
                        status=DiscoveryStatus.KNOWN,
                    )
        if isinstance(node, (ast.Raise, ast.Try, ast.ExceptHandler, ast.Return)):
            kind = (
                "raise"
                if isinstance(node, ast.Raise)
                else "handler"
                if isinstance(node, ast.ExceptHandler)
                else "return_path"
                if isinstance(node, ast.Return)
                else "try"
            )
            self.add(
                "code.exception_path",
                node,
                value={
                    "kind": kind,
                    "text": ast.unparse(node)
                    if not isinstance(node, ast.ExceptHandler)
                    else "except",
                },
                method="python-ast-exception-path",
                metadata={"kind": kind, "scope": ".".join(scope)},
            )
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Name) and target.id.isupper() for target in targets):
                self.add(
                    "code.constant",
                    node,
                    value=ast.unparse(node),
                    method="python-ast-constant",
                    metadata={"scope": ".".join(scope)},
                )
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            definition = self.resolve(node.id, scope)
            if definition is not None and not isinstance(node, ast.Call):
                use = self.add(
                    "code.definition",
                    node,
                    value={"name": node.id, "kind": "use"},
                    method="python-ast-use",
                    metadata={"name": node.id, "kind": "use"},
                )
                if use is not None:
                    self.relation(
                        "relation.definition_use",
                        [definition, use],
                        [definition.source_span_ids[0], use.source_span_ids[0]],
                        exactness=RelationExactness.EXACT,
                        status=DiscoveryStatus.KNOWN,
                    )
        for child in ast.iter_child_nodes(node):
            self.process(child, node_scope)

    def run(self) -> tuple[list[Any], list[Obligation], list[Relation], CoverageState]:
        module_span = self.spans.add(0, len(self.text), kind="code_node")
        module_id = f"py:{self.source.source_id}:<module>:module:0"
        module = make_obligation(
            class_name="code.definition",
            value={"name": "<module>", "kind": "module"},
            source=self.source,
            spans=[module_span],
            extraction_method="python-ast-module",
            confidence=ExtractionConfidence.EXACT,
            discovery_status=DiscoveryStatus.KNOWN,
            lexeme=self.text,
            metadata={"kind": "module", "symbol_id": module_id},
        )
        _append_unique(self.obligations, self.obligation_seen, module, module.obligation_id)
        self.symbols[((), "__module__")] = module
        self.definitions.append((self.tree, (), module))
        self.collect_definitions(self.tree, ())
        self.process(self.tree, ())
        validate_relations(
            self.relations, self.obligations, {span.span_id for span in self.spans.values()}
        )
        unresolved = any(
            relation.discovery_status == DiscoveryStatus.PARTIAL for relation in self.relations
        )
        return (
            self.spans.values(),
            self.obligations,
            self.relations,
            CoverageState.PARTIAL if unresolved else CoverageState.KNOWN,
        )


def _python_result(source: SourceArtifact) -> ExtractionResult:
    normalized, failure = _base_source(source, ContentType.PYTHON)
    if failure is not None:
        return failure
    try:
        text = source.raw_bytes.decode("utf-8", "strict")
        tree = ast.parse(text, filename=source.file_path or "<tracefold>")
        extractor = _PythonExtractor(source, text, tree)
        spans, obligations, relations, coverage = extractor.run()
    except SyntaxError:
        return _failure_result(
            ContentType.PYTHON, [source], "PYTHON_SYNTAX_ERROR", "Python syntax is invalid"
        )
    except (UnicodeDecodeError, SourceCoordinateError, ValueError) as exc:
        return _failure_result(ContentType.PYTHON, [source], "PYTHON_EXTRACTION_FAILURE", str(exc))
    assert normalized is not None
    return ExtractionResult(
        content_type=ContentType.PYTHON,
        sources=[source],
        normalized_sources=[normalized],
        spans=spans,
        obligations=obligations,
        relations=relations,
        coverage=coverage,
    )


def extract_obligations(
    source: SourceArtifact,
    content_type: ContentType | None = None,
) -> ExtractionResult:
    selected = _content_type(source, content_type)
    if selected == ContentType.JSON:
        return _json_result(source)
    if selected == ContentType.LOG:
        return _log_result(source)
    if selected == ContentType.PYTHON:
        return _python_result(source)
    if selected == ContentType.UNKNOWN:
        normalized, failure = _base_source(source, selected)
        if failure is not None:
            return failure
        assert normalized is not None
        return ExtractionResult(
            content_type=selected,
            sources=[source],
            normalized_sources=[normalized],
            spans=[],
            obligations=[],
            relations=[],
            coverage=CoverageState.UNKNOWN,
            warnings=[
                ExtractionWarning(
                    code="UNKNOWN_CONTENT_TYPE",
                    message="content type is outside Phase 2 parser support",
                    source_ids=[source.source_id],
                    severity="unknown_coverage",
                )
            ],
        )
    return _extract_document_result(source, selected)


def extract_dialogue(messages: Sequence[DialogueMessage]) -> ExtractionResult:
    if not messages:
        return _failure_result(
            ContentType.DIALOGUE,
            [],
            "EMPTY_DIALOGUE",
            "dialogue contains no messages",
        )
    results: list[ExtractionResult] = []
    for message in messages:
        source = ingest_source(
            SourceInput(
                input_ordinal=message.ordinal,
                kind="dialogue",
                authority=message.role,
                media_type="text/plain",
                text=message.text,
                file_path=None,
                message_id=message.message_id,
                role=message.role,
            )
        )
        if source.message_id is None:
            source = source.model_copy(
                update={
                    "message_id": (
                        f"msg:{message.ordinal}:{message.role}:"
                        f"{hashlib.sha256(source.raw_bytes).hexdigest()[:16]}"
                    )
                }
            )
        results.append(_extract_document_result(source, ContentType.DIALOGUE))
    if any(result.failure is not None for result in results):
        return _failure_result(
            ContentType.DIALOGUE,
            [source for result in results for source in result.sources],
            "DIALOGUE_MESSAGE_FAILURE",
            "one or more dialogue messages could not be extracted",
        )
    sources = [source for result in results for source in result.sources]
    normalized = [item for result in results for item in result.normalized_sources]
    spans = [span for result in results for span in result.spans]
    obligations = [item for result in results for item in result.obligations]
    relations = [item for result in results for item in result.relations]
    seen_obligations = {item.obligation_id for item in obligations}
    seen_relations = {item.relation_id for item in relations}
    correction_messages = [
        (index, result)
        for index, result in enumerate(results)
        if any(item.class_name == "temporal.correction" for item in result.obligations)
    ]
    for index, current_result in correction_messages:
        if index == 0:
            continue
        previous_result = results[index - 1]
        previous_source = previous_result.sources[0]
        current_source = current_result.sources[0]
        previous_span = make_source_span(
            previous_source, 0, len(previous_source.raw_bytes.decode("utf-8"))
        )
        current_span = next(
            span
            for span in current_result.spans
            if span.conversation_message_id == current_source.message_id
        )
        previous_obligation = make_obligation(
            class_name="temporal.correction",
            value=previous_source.raw_bytes.decode("utf-8"),
            source=previous_source,
            spans=[previous_span],
            extraction_method="dialogue-correction-order",
            confidence=ExtractionConfidence.INFERRED,
            discovery_status=DiscoveryStatus.PARTIAL,
            metadata={"role": "superseded", "message_id": previous_source.message_id},
        )
        current_obligation = next(
            item for item in current_result.obligations if item.class_name == "temporal.correction"
        )
        if previous_obligation.obligation_id not in seen_obligations:
            obligations.append(previous_obligation)
            seen_obligations.add(previous_obligation.obligation_id)
        correction_relation = make_relation(
            relation_type="relation.statement_correction",
            obligations=[previous_obligation, current_obligation],
            evidence_span_ids=[
                previous_span.span_id,
                current_obligation.source_span_ids[0],
                current_span.span_id,
            ],
            extraction_method="dialogue-correction-order",
            discovery_status=DiscoveryStatus.PARTIAL,
            exactness=RelationExactness.INFERRED,
            metadata={
                "previous_message_id": previous_source.message_id,
                "current_message_id": current_source.message_id,
            },
        )
        if correction_relation.relation_id not in seen_relations:
            relations.append(correction_relation)
            seen_relations.add(correction_relation.relation_id)
        spans.append(previous_span)
    validate_relations(relations, obligations, {span.span_id for span in spans})
    return ExtractionResult(
        content_type=ContentType.DIALOGUE,
        sources=sources,
        normalized_sources=normalized,
        spans=spans,
        obligations=obligations,
        relations=relations,
        coverage=CoverageState.PARTIAL,
    )


def extract_relations(result: ExtractionResult) -> tuple[Relation, ...]:
    validate_relations(
        result.relations,
        result.obligations,
        {span.span_id for span in result.spans},
    )
    return tuple(result.relations)


__all__ = ["extract_dialogue", "extract_obligations", "extract_relations"]
